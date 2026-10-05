"""One database interface for SQLite (local development, tests) and Postgres (production).

Store and AgentRuns are written against sqlite3's API: ``?`` placeholders, rows readable by
column name, ``cursor.lastrowid``. ``PostgresConnection`` keeps that API on top of psycopg so
the same SQL runs on Supabase Postgres. Only portable SQL is used by callers: ``ON CONFLICT``
upserts, no ``INSERT OR``, no SQLite date functions.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

try:  # Postgres support is optional for local SQLite development.
    import psycopg
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
except ImportError:  # pragma: no cover - exercised only without the dependency
    psycopg = None
    dict_row = None
    ConnectionPool = None

_POOLS: dict = {}


def _pool(url: str):
    """One small pool per process: opening a TLS connection to Supabase costs several round trips."""
    if url not in _POOLS:
        _POOLS[url] = ConnectionPool(
            url,
            min_size=0,
            max_size=4,
            kwargs={"row_factory": dict_row, "prepare_threshold": None},
            check=ConnectionPool.check_connection,
            open=True,
        )
    return _POOLS[url]

POSTGRES_PREFIXES = ("postgres://", "postgresql://")
# Tables whose integer primary key callers read back through cursor.lastrowid.
ID_TABLES = {"users", "messages", "artifacts", "operator_adjustments"}

if psycopg is not None:
    IntegrityError = (sqlite3.IntegrityError, psycopg.IntegrityError)
else:  # pragma: no cover
    IntegrityError = (sqlite3.IntegrityError,)


def is_postgres(database) -> bool:
    return isinstance(database, str) and database.startswith(POSTGRES_PREFIXES)


class Row(dict):
    """A dict row that also supports positional access, like sqlite3.Row."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)

    def keys(self):  # sqlite3.Row exposes keys(); dict(row) keeps working
        return super().keys()


class PostgresCursor:
    def __init__(self, cursor, lastrowid=None):
        self._cursor = cursor
        self.lastrowid = lastrowid
        self.rowcount = cursor.rowcount

    def fetchone(self):
        row = self._cursor.fetchone() if self._cursor.description else None
        return Row(row) if row is not None else None

    def fetchall(self):
        if not self._cursor.description:
            return []
        return [Row(row) for row in self._cursor.fetchall()]


_INSERT_TABLE = re.compile(r"^\s*INSERT\s+INTO\s+(\w+)", re.IGNORECASE)


def translate(sql: str) -> str:
    """sqlite3 placeholders to psycopg placeholders; literal % must be doubled first."""
    return sql.replace("%", "%%").replace("?", "%s")


class PostgresConnection:
    def __init__(self, url: str):
        if psycopg is None:  # pragma: no cover
            raise RuntimeError("psycopg is required for a Postgres DATABASE_URL")
        # prepare_threshold=None keeps connections usable through Supabase's transaction pooler.
        self._pool = _pool(url)
        self._connection = self._pool.getconn()

    def execute(self, sql: str, parameters=()):
        statement = translate(sql)
        table = _INSERT_TABLE.match(statement)
        wants_id = bool(table and table.group(1).lower() in ID_TABLES and "RETURNING" not in statement.upper())
        if wants_id:
            statement = statement.rstrip().rstrip(";") + " RETURNING id"
        cursor = self._connection.execute(statement, tuple(parameters))
        lastrowid = None
        if wants_id:
            row = cursor.fetchone()
            lastrowid = row["id"] if row else None
        return PostgresCursor(cursor, lastrowid)

    def executescript(self, script: str) -> None:
        for statement in (part.strip() for part in script.split(";")):
            if statement:
                self._connection.execute(statement)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        if self._connection is None:
            return
        try:
            if self._connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                self._connection.rollback()
        finally:
            self._pool.putconn(self._connection)
            self._connection = None

    @property
    def raw(self):
        return self._connection


def connect(database):
    if is_postgres(database):
        return PostgresConnection(database)
    connection = sqlite3.connect(Path(database))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
