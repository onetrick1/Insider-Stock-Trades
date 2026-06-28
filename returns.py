import time
import yfinance as yf
import pandas as pd
from dateutil.relativedelta import relativedelta
from database import conn   # reuse the same connection opened (and authenticated) by database.py
from dotenv import load_dotenv
load_dotenv()      # reads .env into environment variables

HORIZONS = {"1m": 1, "3m": 3, "6m": 6, "12m": 12}   # label → number of months


def price_on_or_after(prices, target_date):
    """Nearest trading-day price on or after target_date, or None if it's in the future."""
    target = pd.to_datetime(target_date)
    available = prices[prices.index >= target]
    if len(available) == 0:
        return None
    return float(available.iloc[0])


def forward_returns(ticker, buy_date):
    """Return {horizon: return} for one stock, measured from its buy date."""
    buy = pd.to_datetime(buy_date)
    end = (buy + relativedelta(months=13)).strftime("%Y-%m-%d")
    data = yf.download(ticker, start=buy_date, end=end, auto_adjust=True, progress=False)
    if data.empty:
        return {}

    prices = data["Close"]
    if isinstance(prices, pd.DataFrame):
        prices = prices.iloc[:, 0]

    buy_price = price_on_or_after(prices, buy_date)
    if buy_price is None:
        return {}

    results = {}
    for label, months in HORIZONS.items():
        target = (buy + relativedelta(months=months)).strftime("%Y-%m-%d")
        later = price_on_or_after(prices, target)
        results[label] = (later / buy_price - 1) if later is not None else None

    return results


def fill_returns():
    rows = conn.execute(
        "SELECT id, ticker, date FROM transactions WHERE code = 'P' AND exc_12m IS NULL"
    ).fetchall()
    # With dict_row, each row is a plain dict — row["ticker"] and row["id"] work as before.
    print(f"Computing returns for {len(rows)} transactions...")

    for row in rows:
        stock = forward_returns(row["ticker"], row["date"])
        spy   = forward_returns("SPY", row["date"])

        exc = {}
        for label in HORIZONS:
            s, b = stock.get(label), spy.get(label)
            exc[label] = (s - b) if (s is not None and b is not None) else None

        # The only change here is ? → %s (all nine placeholders).
        conn.execute("""
            UPDATE transactions
            SET ret_1m=%s, ret_3m=%s, ret_6m=%s, ret_12m=%s,
                exc_1m=%s, exc_3m=%s, exc_6m=%s, exc_12m=%s
            WHERE id=%s
        """, (
            stock.get("1m"), stock.get("3m"), stock.get("6m"), stock.get("12m"),
            exc.get("1m"), exc.get("3m"), exc.get("6m"), exc.get("12m"),
            row["id"],
        ))
        conn.commit()
        print(f"  {row['ticker']} on {row['date']}: 3-month excess = {exc.get('3m')}")

    print("Done.")


if __name__ == "__main__":

    start_time = time.perf_counter()

    fill_returns()

    end_time = time.perf_counter()
    final_time = end_time - start_time
    print(f"Done. Finished in {final_time} seconds")
