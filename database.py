import os
import psycopg                       # psycopg v3 — the PostgreSQL driver
from psycopg.rows import dict_row    # makes every row come back as a plain dict
from dotenv import load_dotenv       # reads the .env file into os.environ

# my commit
# Load .env so DATABASE_URL is available before we try to connect.
# Never hardcode the connection string — credentials belong in the environment.
load_dotenv()

# psycopg.connect() opens one persistent connection for the lifetime of the script.
# row_factory=dict_row replaces sqlite3's conn.row_factory = sqlite3.Row —
# both give you row["ticker"] style access, but the psycopg way is set at connect time.
conn = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)

# Create the table if it isn't already there.
# Two syntax changes from SQLite:
#   INTEGER PRIMARY KEY AUTOINCREMENT  →  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY
#   (PostgreSQL's standard way to auto-number rows — "AUTOINCREMENT" is a SQLite keyword)
conn.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id        INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    accession TEXT,
    company   TEXT,
    ticker    TEXT,
    insider   TEXT,
    role      TEXT,
    code      TEXT,
    shares    REAL,
    price     REAL,
    date      TEXT,
    ret_1m    REAL,
    ret_3m    REAL,
    ret_6m    REAL,
    ret_12m   REAL,
    exc_1m    REAL,
    exc_3m    REAL,
    exc_6m    REAL,
    exc_12m   REAL,
    UNIQUE(accession, ticker, code, shares, price, date)
)
""")

conn.commit()   # DDL is transactional in PostgreSQL — must commit to make the table permanent
print("Database ready.")


def save_transaction(conn, t, commit=True):
    # Two changes from the SQLite version:
    #   ?  →  %s   (psycopg uses %s as the placeholder, not ?)
    #   INSERT OR IGNORE  →  INSERT ... ON CONFLICT DO NOTHING
    #     "ON CONFLICT (the_unique_columns) DO NOTHING" tells PostgreSQL:
    #     if a row with the same (accession, ticker, code, shares, price, date)
    #     already exists, silently skip this insert instead of raising an error.
    cursor = conn.execute("""
        INSERT INTO transactions
            (accession, company, ticker, insider, role, code, shares, price, date)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (accession, ticker, code, shares, price, date) DO NOTHING
    """, (
        t["accession"], t["company"], t["ticker"], t["insider"],
        t["role"], t["code"], t["shares"], t["price"], t["date"],
    ))
    # commit=False lets the caller batch many inserts under a single commit,
    # which is much faster when writing to a remote PostgreSQL server.
    if commit:
        conn.commit()
    return cursor.rowcount  # 1 if the row was inserted, 0 if it was a duplicate and skipped


def get_all_transactions(conn):
    return conn.execute("SELECT * FROM transactions ORDER BY date DESC").fetchall()
