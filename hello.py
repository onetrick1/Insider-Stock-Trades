import yfinance as yf
import pandas as pd
from dateutil.relativedelta import relativedelta


data = yf.download("AAPL", start="2026-01-01", end="2026-07-01", auto_adjust=True)
print(data["Close"])


# function that returns the date after a selected time period 
# (if user selects 3 months, 3 months from june 3, 2025 might be a holiday/weekend. Function returns nearest trading day)
# (function also checks if time is in the future -> doesn't return anything if it is) 
def price_on_or_after(prices, target_date):
    """prices: a pandas Series indexed by date. target_date: 'YYYY-MM-DD' string."""
    # Convert the text date into a real date object pandas can compare against.
    target = pd.to_datetime(target_date)

    # Keep only the trading days on or after the date we want.
    available = prices[prices.index >= target]

    # If nothing is left, the date is in the future (or has no data) — signal that.
    if len(available) == 0:
        return None

    # Otherwise take the FIRST remaining day = the nearest trading day on/after target.
    return float(available.iloc[0])



HORIZONS = {"1m": 1, "3m": 3, "6m": 6, "12m": 12}   # label → number of months


# based on if the selection was available, function returns the percentage increase for that stock
def forward_returns(ticker, buy_date):
    buy = pd.to_datetime(buy_date)   # the purchase date as a real date object

    # Download a wide window of prices: from the buy date to ~13 months later
    # (13, not 12, to be sure the 12-month price exists in the data).
    end = (buy + relativedelta(months=13)).strftime("%Y-%m-%d")
    data = yf.download(ticker, start=buy_date, end=end, auto_adjust=True, progress=False)
    if data.empty:
        return {}                    # no price data for this ticker — give up gracefully
    prices = data["Close"]           # the adjusted closing prices, indexed by date

    # The starting price: the stock's price on (or just after) the buy date.
    buy_price = price_on_or_after(prices, buy_date)
    if buy_price is None:
        return {}

    # For each horizon, find the price that many months later and compute the return.
    results = {}
    for label, months in HORIZONS.items():
        target = (buy + relativedelta(months=months)).strftime("%Y-%m-%d")
        later_price = price_on_or_after(prices, target)
        if later_price is None:
            results[label] = None              # window hasn't elapsed yet — honest blank
        else:
            # return = how much higher (or lower) the price is, as a fraction.
            results[label] = later_price / buy_price - 1
            # calculating the forward return
            # forward return = (price later / price on buy date) − 1
    return results

# returns a dictionary of every stocks' excess return percentages
def excess_returns(ticker, buy_date):
    # The stock's own returns at each horizon...
    stock = forward_returns(ticker, buy_date)
    # ...and the market's returns over the exact same dates.
    spy   = forward_returns("SPY", buy_date)

    out = {}
    for label in HORIZONS:
        s = stock.get(label)   # the stock's return at this horizon (may be None)
        b = spy.get(label)     # the benchmark's return at this horizon (may be None)
        # If either side is missing, we can't compare — leave it blank.
        if s is None or b is None:
            out[label] = None
        else:
            out[label] = s - b      # the insider's edge vs. the market
        # calculating overall (excess) return
        # excess return = stock forward return − SPY forward return

    return out