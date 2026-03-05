import os
import psycopg
from psycopg.rows import dict_row

def get_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")

    if "sslmode=" not in url:
        url += "?sslmode=require"

    # Adds stability on cloud platforms
    if "connect_timeout=" not in url:
        joiner = "&" if "?" in url else "?"
        url += f"{joiner}connect_timeout=10&keepalives=1&keepalives_idle=30&keepalives_interval=10&keepalives_count=5"

    return psycopg.connect(url, row_factory=dict_row)

def fetchone(query, params=()):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()

def fetchall(query, params=()):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()

def execute(query, params=()):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            conn.commit()