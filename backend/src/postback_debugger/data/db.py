"""SQLite connection helpers."""

import os
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
# backend/data/mmp.db, resolved from backend/src/postback_debugger/data/db.py
DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "data" / "mmp.db"


def default_db_path() -> Path:
    """Database location; override with the POSTBACK_DB_PATH environment variable."""
    return Path(os.environ.get("POSTBACK_DB_PATH") or DEFAULT_DB_PATH)


def connect(
    path: Path | str, *, read_only: bool = False, check_same_thread: bool = True
) -> sqlite3.Connection:
    """Open a connection that returns rows as sqlite3.Row and enforces foreign keys.

    With read_only=True the file is opened in SQLite's read-only mode: any write raises
    sqlite3.OperationalError, and a missing file is an error instead of a new empty DB.
    check_same_thread=False allows handing the connection to another thread (web server
    workers); the caller must still use it from one thread at a time.
    """
    if read_only:
        uri = f"{Path(path).resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=check_same_thread)
    else:
        conn = sqlite3.connect(path, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Drop and recreate all tables inside a new transaction.

    The transaction is left open so the caller can insert data and then commit (or roll
    back) the schema reset and the inserts together.
    """
    conn.executescript("BEGIN;\n" + SCHEMA_PATH.read_text())
