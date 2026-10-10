"""Read-only access to ridewise.db. Never opens the file for writing."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "ridewise.db"


def get_connection() -> sqlite3.Connection:
    """Open ridewise.db strictly read-only via SQLite URI mode=ro."""
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con
