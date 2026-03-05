import os
import socket
from urllib.parse import urlparse, parse_qs

import psycopg
from psycopg.rows import dict_row


def _force_ipv4_hostaddr(host: str, port: int) -> str | None:
    """
    Returns an IPv4 address for a hostname if available, otherwise None.
    """
    try:
        infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        if not infos:
            return None
        # infos[0][4] = (ip, port)
        return infos[0][4][0]
    except Exception:
        return None


def get_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")

    # Ensure sslmode=require (Supabase needs SSL)
    if "sslmode=" not in url:
        joiner = "&" if "?" in url else "?"
        url = f"{url}{joiner}sslmode=require"

    u = urlparse(url)

    if u.scheme not in ("postgres", "postgresql"):
        # If someone stored a non-url conninfo, just pass through
        return psycopg.connect(url, row_factory=dict_row)

    host = u.hostname
    port = u.port or 5432
    user = u.username or "postgres"
    password = u.password or ""
    dbname = (u.path or "").lstrip("/") or "postgres"

    q = parse_qs(u.query)
    sslmode = (q.get("sslmode", ["require"])[0])  # default require
    connect_timeout = (q.get("connect_timeout", ["10"])[0])

    # ✅ Force IPv4 address
    hostaddr = _force_ipv4_hostaddr(host, port) if host else None

    # Build libpq conninfo.
    # host= keeps TLS SNI correct; hostaddr= forces IPv4 route.
    if hostaddr:
        conninfo = (
            f"host={host} hostaddr={hostaddr} port={port} "
            f"dbname={dbname} user={user} password={password} "
            f"sslmode={sslmode} connect_timeout={connect_timeout}"
        )
    else:
        # fallback (still tries DNS normally)
        conninfo = (
            f"host={host} port={port} dbname={dbname} user={user} password={password} "
            f"sslmode={sslmode} connect_timeout={connect_timeout}"
        )

    return psycopg.connect(conninfo, row_factory=dict_row)


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