import os
import math
import psycopg                       # psycopg v3
from psycopg.rows import dict_row
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
load_dotenv()      # reads .env into environment variables


def _safe(v):
    """Return None for NaN/Inf floats so the JSON response is always valid."""
    if v is None:
        return None
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return v

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    # Opens a fresh connection for each request and closes it when the handler finishes.
    # row_factory=dict_row replaces sqlite3's conn.row_factory = sqlite3.Row —
    # rows come back as plain dicts so row["ticker"] keeps working everywhere.
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


@app.get("/")
def home():
    return {"message": "Insider Trading Pattern Explorer API is running."}


@app.get("/transactions")
def get_transactions(
    ticker: str = None,
    role: str = None,
    code: str = None,
    company: str = None,
    insider: str = None,
    date_from: str = None,
    date_to: str = None,
    limit: int = 200,
    offset: int = 0,
):
    conn = get_db()
    # All ? placeholders replaced with %s — that's the only placeholder syntax
    # psycopg (and PostgreSQL in general) recognises.
    query = "SELECT * FROM transactions WHERE 1=1"
    params = []

    if ticker:
        query += " AND ticker = %s"
        params.append(ticker.upper())
    if role:
        query += " AND role LIKE %s"
        params.append(f"%{role}%")
    if code:
        query += " AND code = %s"
        params.append(code.upper())
    if company:
        query += " AND company LIKE %s"
        params.append(f"%{company}%")
    if insider:
        query += " AND insider LIKE %s"
        params.append(f"%{insider}%")
    if date_from:
        query += " AND date >= %s"
        params.append(date_from)
    if date_to:
        query += " AND date <= %s"
        params.append(date_to)

    query += " ORDER BY date DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [{k: _safe(v) if isinstance(v, float) else v for k, v in row.items()}
            for row in rows]


@app.get("/summary")
def get_summary():
    conn = get_db()
    stats = {}

    # sqlite3 let you do fetchone()[0] to grab the first column by position.
    # With dict_row every row is a dict, so we need to access columns by name.
    # Adding explicit aliases (AS total, AS n, etc.) makes the column name predictable.
    stats["total"] = conn.execute(
        "SELECT COUNT(*) AS total FROM transactions"
    ).fetchone()["total"]

    stats["tickers"] = conn.execute(
        "SELECT COUNT(DISTINCT ticker) AS n FROM transactions"
    ).fetchone()["n"]

    stats["insiders"] = conn.execute(
        "SELECT COUNT(DISTINCT insider) AS n FROM transactions"
    ).fetchone()["n"]

    row = conn.execute(
        "SELECT MIN(date) AS date_min, MAX(date) AS date_max FROM transactions"
    ).fetchone()
    stats["date_min"] = row["date_min"]
    stats["date_max"] = row["date_max"]

    stats["with_returns"] = conn.execute(
        "SELECT COUNT(*) AS n FROM transactions WHERE exc_3m IS NOT NULL"
    ).fetchone()["n"]

    top_tickers = conn.execute(
        "SELECT ticker, COUNT(*) AS n FROM transactions GROUP BY ticker ORDER BY n DESC LIMIT 10"
    ).fetchall()
    stats["top_tickers"] = [dict(r) for r in top_tickers]

    conn.close()
    return stats


# Column names are built from this fixed list — never interpolated from user input.
HORIZONS = ["1m", "3m", "6m", "12m"]


@app.get("/stats")
def get_stats(
    ticker: str = None,
    role: str = None,
    insider: str = None,
):
    conn = get_db()

    select_parts = ["COUNT(*) AS total"]
    for h in HORIZONS:
        select_parts += [
            f"COUNT(exc_{h}) AS n_{h}",
            f"AVG(ret_{h}) AS avg_ret_{h}",
            f"AVG(exc_{h}) AS avg_exc_{h}",
            f"CAST(SUM(CASE WHEN exc_{h} > 0 THEN 1 ELSE 0 END) AS REAL)"
            f" / NULLIF(COUNT(exc_{h}), 0) AS hit_{h}",
        ]

    query = "SELECT " + ", ".join(select_parts) + " FROM transactions WHERE 1=1"
    params = []

    if ticker:
        query += " AND ticker = %s"
        params.append(ticker.upper())
    if role:
        query += " AND role LIKE %s"
        params.append(f"%{role}%")
    if insider:
        query += " AND insider LIKE %s"
        params.append(f"%{insider}%")

    row = conn.execute(query, params).fetchone()
    conn.close()

    return {
        "total": row["total"],
        "horizons": [
            {
                "label": h,
                "n":        row[f"n_{h}"],
                "avg_ret":  _safe(row[f"avg_ret_{h}"]),
                "avg_exc":  _safe(row[f"avg_exc_{h}"]),
                "hit_rate": _safe(row[f"hit_{h}"]),
            }
            for h in HORIZONS
        ],
    }
