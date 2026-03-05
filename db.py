import os
import psycopg
from psycopg.rows import dict_row

def get_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")

    # Supabase needs SSL
    if "sslmode=" not in url:
        url += "?sslmode=require"

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