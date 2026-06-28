import time
import json
from pathlib import Path
from fetcher import get_form4_paths        # your refactored Section 1
from parse_filing import parse_filing       # your refactored Section 2
from database import conn, save_transaction   # your Section 3
from datetime import date as dt_date, timedelta, datetime as dt_datetime
from dotenv import load_dotenv
load_dotenv()      # reads .env into environment variables

# Path to the JSON file that remembers which filing dates have been fetched.
# Path(__file__).parent means "the same folder this script lives in", so the
# state file always sits next to pipeline.py regardless of where you launch it from.
STATE_FILE = Path(__file__).parent / "pipeline_state.json"


# ── Core fetch logic ───────────────────────────────────────────────────────

# Saving every single filing from that specific date
def process_day(date, quarter):
    # Step 1: get every Form 4 filing path for this day.
    paths = get_form4_paths(date, quarter)
    print(f"{date}: found {len(paths)} Form 4 filings")

    saved = 0
    # Step 2: visit each filing, parse it, and store its transactions.
    for path in paths:
        # parse_filing returns a list (a filing can hold several transactions).
        for t in parse_filing(path):
            saved += save_transaction(conn, t)   # only counts rows actually inserted
        time.sleep(0.15)   # be polite: stay well under SEC's rate limit
    # time.sleep(0.15) pauses 0.15 s between filings — the SEC asks for under ~10 req/s

    print(f"{date}: saved {saved} open-market transactions")


def quarter_for(d):
    # Turn a month (1-12) into its quarter: Jan-Mar->1, Apr-Jun->2, etc.
    return f"QTR{(d.month - 1) // 3 + 1}"

def backfill(num_days):
    today = dt_date.today()
    # Walk backwards one day at a time, from yesterday to num_days ago.
    for i in range(1, num_days + 1):
        d = today - timedelta(days=i)        # the date i days before today
        if d.weekday() >= 5:                 # 5 = Saturday, 6 = Sunday — skip weekends
            continue
        date_str = d.strftime("%Y%m%d")      # format the date as YYYYMMDD for the URL
        process_day(date_str, quarter_for(d))


# ── State file helpers ─────────────────────────────────────────────────────
# pipeline_state.json stores two dates that define the window we've already fetched:
#   "oldest_fetched_date" — how far back in history we've gone.
#   "newest_fetched_date" — the most recent filing date we've requested.
# Tracking both ends lets extend_to() fill in exactly the gaps that are missing,
# without re-requesting the SEC for days already in the database.

def load_state():
    """Return the saved fetch state, or an empty dict if no state file exists yet."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}   # first-ever run — treat as if nothing has been fetched

def save_state(state):
    # Overwrite the state file on disk so the next run can pick up where this one left off.
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


# ── Smart incremental fetch ────────────────────────────────────────────────

def fetch_range(start, end):
    """Fetch all weekdays between start and end dates (inclusive), walking backwards."""
    d = end
    while d >= start:
        if d.weekday() < 5:   # skip Saturday (5) and Sunday (6) — no SEC filings on weekends
            process_day(d.strftime("%Y%m%d"), quarter_for(d))
        d -= timedelta(days=1)


def extend_to(target_days):
    """
    Fetch only the filing dates not yet processed, covering two gaps:
      1. New recent days since the last run (the 'front' gap).
      2. Older days not yet fetched for the historical backfill (the 'back' gap).

    pipeline_state.json tracks:
      - newest_fetched_date: the most recent filing date we've fetched.
      - oldest_fetched_date: how far back into history we've gone.
    """
    today     = dt_date.today()
    yesterday = today - timedelta(days=1)
    cutoff    = today - timedelta(days=target_days)  # the oldest date we want to cover

    state      = load_state()
    oldest_str = state.get("oldest_fetched_date")
    newest_str = state.get("newest_fetched_date")

    if oldest_str is None or newest_str is None:
        # State file is missing or incomplete — fetch the entire window from scratch.
        print(f"No fetch history found. Fetching the last {target_days} days...")
        fetch_range(cutoff, yesterday)
        # Record both ends of the window we just covered so future runs know what to skip.
        state["oldest_fetched_date"] = str(cutoff)
        state["newest_fetched_date"] = str(yesterday)
        save_state(state)
        return

    # Convert the stored date strings back into Python date objects for comparison.
    oldest = dt_datetime.strptime(oldest_str, "%Y-%m-%d").date()
    newest = dt_datetime.strptime(newest_str, "%Y-%m-%d").date()
    fetched_any = False

    # Gap 1 — new days at the recent end (e.g. you ran this 2 days ago).
    # newest < yesterday means filing days have appeared since the last run.
    if newest < yesterday:
        print(f"Fetching new days: {newest + timedelta(days=1)} → {yesterday}")
        fetch_range(newest + timedelta(days=1), yesterday)
        state["newest_fetched_date"] = str(yesterday)  # push the recent boundary forward
        fetched_any = True

    # Gap 2 — older days for historical backfill (e.g. extending 30 → 90 days).
    # oldest > cutoff means our history doesn't reach as far back as target_days requires.
    if oldest > cutoff:
        print(f"Extending history: {cutoff} → {oldest - timedelta(days=1)}")
        fetch_range(cutoff, oldest - timedelta(days=1))
        state["oldest_fetched_date"] = str(cutoff)     # push the history boundary back
        fetched_any = True

    if not fetched_any:
        # Both boundaries already cover the full requested window — nothing to do.
        print(f"Already up to date ({cutoff} → {yesterday}). Nothing to fetch.")
        return

    # Persist the updated boundaries so the next run knows exactly where to resume.
    save_state(state)


# Only runs when you launch this file directly (python pipeline.py),
# not when another file imports/uses it
# prevents extend_to() from being called unintentionally when pipeline is imported elsewhere
if __name__ == "__main__":

    start_time = time.perf_counter() # tracking how long it takes to fetch all data and import to database

    extend_to(37)   # fetch up to __ days back FROM TODAY, skipping days already fetched

    end_time = time.perf_counter()
    print(f"Done. Finished in {end_time - start_time:.1f} seconds")

'''When Python runs a file, it sets a built-in variable __name__:
Run directly → __name__ is "__main__"
Imported as a module → __name__ is the module's filename (e.g. "pipeline")'''
