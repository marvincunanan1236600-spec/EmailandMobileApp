import os
import socket
import psycopg
from psycopg.rows import dict_row
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

def _ensure_sslmode(url: str) -> str:
    # Ensure sslmode=require exists in query string
    parsed = urlparse(url)
    qs = dict(parse_qsl(parsed.query, keep_blank_values=True))
    qs.setdefault("sslmode", "require")
    new_query = urlencode(qs)
    return urlunparse(parsed._replace(query=new_query))

def _resolve_ipv4(hostname: str) -> str:
    # Forces an IPv4 address (A record). This bypasses IPv6.
    # If your DNS only has IPv6, this will fail (but Supabase has IPv4).
    return socket.gethostbyname(hostname)

def get_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")

    url = _ensure_sslmode(url)

    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise RuntimeError("DATABASE_URL missing hostname")

    ipv4 = _resolve_ipv4(host)

    # KEY PART:
    # hostaddr forces the TCP connection to use that IP, even if DNS prefers IPv6.
    return psycopg.connect(
        url,
        hostaddr=ipv4,
        row_factory=dict_row
    )

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