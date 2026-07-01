import time
import logging
import threading
import yfinance as yf
import pandas as pd
from dateutil.relativedelta import relativedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from database import conn
from dotenv import load_dotenv
load_dotenv()

# Silence yfinance's "possibly delisted" and download-failure warnings.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

HORIZONS        = {"1m": 1, "3m": 3, "6m": 6, "12m": 12}
DOWNLOAD_WORKERS = 2    # keep low — Yahoo Finance rate-limits aggressive parallel requests

# Tickers stored in the DB that are not real stock symbols — skip before downloading.
_INVALID_TICKERS = {"NONE", "N/A", "NA", ""}   # checked after .upper(), so covers "none" etc.

# ── Yahoo Finance rate limiter ─────────────────────────────────────────────────
# Ensures threads collectively start no more than 1 download every 0.6 s (~1.6/s).
# Stays well under Yahoo's threshold while still being faster than sequential.
_rl_lock = threading.Lock()
_rl_last = [0.0]
_YF_INTERVAL = 0.6   # seconds between download starts


# ── Price helpers ──────────────────────────────────────────────────────────────

def _prices_from_data(data):
    """Extract a closing-price Series from a yfinance DataFrame."""
    if data is None or data.empty:
        return None
    prices = data["Close"]
    return prices.iloc[:, 0] if isinstance(prices, pd.DataFrame) else prices


def _is_rate_limit(exc):
    return "Too Many Requests" in str(exc) or "RateLimit" in type(exc).__name__


def _download_spy(start, end):
    """
    Download SPY with visible retry logic.
    - Caps end at today (yfinance can't return future prices).
    - Downloads in 10-year chunks if the range is very long (e.g. old transaction dates).
    - Retries up to 5 times with increasing pauses on rate-limit errors.
    """
    today     = pd.Timestamp.today().normalize()
    start_dt  = pd.to_datetime(start[:10])
    end_dt    = min(pd.to_datetime(end[:10]), today)

    # Split into 10-year chunks so yfinance doesn't choke on very long date ranges.
    all_chunks = []
    chunk_start = start_dt
    while chunk_start < end_dt:
        chunk_end = min(chunk_start + relativedelta(years=10), end_dt)
        s = chunk_start.strftime("%Y-%m-%d")
        e = chunk_end.strftime("%Y-%m-%d")

        for attempt in range(5):
            try:
                data = yf.download("SPY", start=s, end=e,
                                   auto_adjust=True, progress=False)
                chunk = _prices_from_data(data)
                if chunk is not None:
                    all_chunks.append(chunk)
                break   # success — move to next chunk
            except Exception as exc:
                if _is_rate_limit(exc):
                    pause = 60 * (attempt + 1)
                    print(f"  SPY rate limited (chunk {s}). Pausing {pause}s "
                          f"(attempt {attempt+1}/5)...")
                    time.sleep(pause)
                else:
                    print(f"  SPY chunk error ({s} → {e}): {type(exc).__name__}: {exc}")
                    break

        chunk_start = chunk_end

    if not all_chunks:
        return None
    combined = pd.concat(all_chunks)
    combined = combined[~combined.index.duplicated(keep="first")].sort_index()
    return combined


def _download(ticker, start, end):
    """
    Download adjusted closing prices for one stock ticker.
    Rate-limited via _rl_lock and retries on rate-limit errors. Returns a Series or None.
    """
    # Throttle: wait until at least _YF_INTERVAL has passed since the last request.
    with _rl_lock:
        now  = time.perf_counter()
        wait = _YF_INTERVAL - (now - _rl_last[0])
        if wait > 0:
            time.sleep(wait)
        _rl_last[0] = time.perf_counter()

    for attempt in range(3):
        try:
            data = yf.download(ticker, start=start, end=end,
                               auto_adjust=True, progress=False)
            result = _prices_from_data(data)
            if result is not None:
                return result
            return None   # empty — delisted or no data
        except Exception as exc:
            if _is_rate_limit(exc):
                pause = 60 * (attempt + 1)
                print(f"\n  Rate limited. Pausing {pause}s (attempt {attempt+1}/3)...")
                time.sleep(pause)
            else:
                return None   # bad ticker — give up
    return None


def price_on_or_after(prices, target_date):
    """
    Nearest trading-day closing price on or after target_date.
    Returns None if the date is in the future or the price is NaN.
    """
    import math
    target    = pd.to_datetime(target_date)
    available = prices[prices.index >= target]
    if len(available) == 0:
        return None
    price = float(available.iloc[0])
    return None if math.isnan(price) else price


def compute_returns(stock_prices, spy_prices, buy_date):
    """
    Using pre-loaded price Series, compute raw and excess returns at every horizon.
    Returns (stock_ret, exc_ret) — dicts mapping label -> float or None.
    None means that window hasn't elapsed yet.
    """
    buy       = pd.to_datetime(buy_date)
    buy_price = price_on_or_after(stock_prices, buy_date)
    spy_buy   = price_on_or_after(spy_prices,   buy_date)
    if buy_price is None or spy_buy is None:
        return {}, {}

    stock_ret, exc_ret = {}, {}
    for label, months in HORIZONS.items():
        target    = (buy + relativedelta(months=months)).strftime("%Y-%m-%d")
        s_later   = price_on_or_after(stock_prices, target)
        spy_later = price_on_or_after(spy_prices,   target)

        s = (s_later   / buy_price - 1) if s_later   is not None else None
        b = (spy_later / spy_buy   - 1) if spy_later is not None else None

        stock_ret[label] = s
        exc_ret[label]   = (s - b) if (s is not None and b is not None) else None

    return stock_ret, exc_ret


# ── Main functions ─────────────────────────────────────────────────────────────

def fill_returns():
    """
    Compute and store forward returns for all eligible open-market purchases.

    Key optimisations vs. the naive approach:
      - SPY is downloaded ONCE for the full date range, not once per transaction.
      - Each stock ticker is downloaded ONCE covering all its buy dates.
      - Ticker downloads run in parallel (DOWNLOAD_WORKERS threads).
      - All DB writes use executemany — one network round trip to PostgreSQL.
    """
    # ── 1. Fetch eligible rows ─────────────────────────────────────────────────
    # Only pick up rows where a horizon has matured but its column is still NULL.
    # This avoids re-downloading prices for recent trades with nothing to compute.
    rows = conn.execute("""
        SELECT id, ticker, date FROM transactions
        WHERE code = 'P'
          AND (
            (ret_1m  IS NULL AND SUBSTRING(date,1,10)::date <= CURRENT_DATE - INTERVAL  '1 month')  OR
            (ret_3m  IS NULL AND SUBSTRING(date,1,10)::date <= CURRENT_DATE - INTERVAL  '3 months') OR
            (ret_6m  IS NULL AND SUBSTRING(date,1,10)::date <= CURRENT_DATE - INTERVAL  '6 months') OR
            (ret_12m IS NULL AND SUBSTRING(date,1,10)::date <= CURRENT_DATE - INTERVAL '12 months')
          )
    """).fetchall()

    if not rows:
        print("Nothing to compute — no horizons have matured yet.")
        return

    print(f"{len(rows):,} transactions to process.")

    # ── 2. Download SPY once for the full date range ───────────────────────────
    all_dates = [row["date"] for row in rows]
    spy_start = min(all_dates)
    spy_end   = (pd.to_datetime(max(all_dates)) + relativedelta(months=14)).strftime("%Y-%m-%d")

    print(f"Downloading SPY ({spy_start} → {spy_end})...")
    spy_prices = _download_spy(spy_start, spy_end)
    if spy_prices is None:
        print("ERROR: Could not download SPY. Aborting.")
        return
    print("SPY ready.")

    # ── 3. Group transactions by ticker to find each ticker's date range ───────
    ticker_dates = defaultdict(list)
    for row in rows:
        if (row["ticker"] or "").upper() not in _INVALID_TICKERS:
                ticker_dates[row["ticker"]].append(row["date"])

    n_tickers = len(ticker_dates)
    print(f"Downloading {n_tickers:,} unique tickers ({DOWNLOAD_WORKERS} at a time)...")

    # ── 4. Download each ticker's price history in parallel ────────────────────
    price_cache = {}
    failed      = []
    done        = 0

    def fetch_ticker(ticker, dates):
        start = min(dates)
        end   = (pd.to_datetime(max(dates)) + relativedelta(months=14)).strftime("%Y-%m-%d")
        return ticker, _download(ticker, start, end)

    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
        futures = {
            pool.submit(fetch_ticker, ticker, dates): ticker
            for ticker, dates in ticker_dates.items()
        }
        for future in as_completed(futures):
            ticker, prices = future.result()
            done += 1
            if prices is not None:
                price_cache[ticker] = prices
            else:
                failed.append(ticker)
            if done % 200 == 0 or done == n_tickers:
                pct = done / n_tickers * 100
                print(f"  {done:,}/{n_tickers:,} ({pct:.0f}%)  —  {len(failed)} failed")

    if failed:
        sample = ", ".join(failed[:10]) + (f" … +{len(failed)-10} more" if len(failed) > 10 else "")
        print(f"  No price data for: {sample}")

    # ── 5. Compute returns for every row using cached prices ───────────────────
    print("Computing returns...")
    updates = []

    for row in rows:
        stock_prices = price_cache.get(row["ticker"])
        if stock_prices is None:
            continue   # no price data available for this ticker

        stock_ret, exc_ret = compute_returns(stock_prices, spy_prices, row["date"][:10])

        updates.append((
            stock_ret.get("1m"), stock_ret.get("3m"),
            stock_ret.get("6m"), stock_ret.get("12m"),
            exc_ret.get("1m"),   exc_ret.get("3m"),
            exc_ret.get("6m"),   exc_ret.get("12m"),
            row["id"],
        ))

    # ── 6. Write everything to the DB in one batch ─────────────────────────────
    print(f"Writing {len(updates):,} rows to database...")
    with conn.cursor() as cur:
        cur.executemany("""
            UPDATE transactions
            SET ret_1m=%s, ret_3m=%s, ret_6m=%s, ret_12m=%s,
                exc_1m=%s, exc_3m=%s, exc_6m=%s, exc_12m=%s
            WHERE id=%s
        """, updates)
    conn.commit()
    print(f"Done. Stored returns for {len(updates):,} transactions.")


def reset_returns():
    """
    Wipe all stored return values back to NULL so fill_returns() starts fresh.
    Use this when you want to recompute everything (e.g. after a fresh data load).
    """
    conn.execute("""
        UPDATE transactions
        SET ret_1m=NULL, ret_3m=NULL, ret_6m=NULL, ret_12m=NULL,
            exc_1m=NULL, exc_3m=NULL, exc_6m=NULL, exc_12m=NULL
    """)
    conn.commit()
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM transactions WHERE code='P'"
    ).fetchone()["n"]
    print(f"Reset returns for {n:,} transactions.")


if __name__ == "__main__":

    start_time = time.perf_counter()

    # Uncomment reset_returns() only when you want a clean slate.
    # reset_returns()

    fill_returns()

    print(f"Total time: {time.perf_counter() - start_time:.1f}s")
