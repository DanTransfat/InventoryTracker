"""Data-access plumbing: connections, transactions and a tiny dialect adapter.

The app talks to MySQL 8 in every real deployment. The test suite can also run on
SQLite so it needs no server. Repositories write SQL with ``:name`` parameters and
``FOR UPDATE``; this module translates the few things that differ between the two.

Locking model
-------------
* MySQL: each transaction runs at READ COMMITTED. Business logic takes row locks
  with ``SELECT ... FOR UPDATE`` on the item it is changing, which serialises all
  writers for that item while leaving other items untouched. READ COMMITTED avoids
  InnoDB gap locks, which removes a whole class of cross-item deadlocks.
* SQLite: has no row locks. ``BEGIN IMMEDIATE`` takes the database write lock up
  front, which is a stricter (whole-database) version of the same guarantee.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar
from urllib.parse import unquote, urlparse

log = logging.getLogger(__name__)

T = TypeVar("T")

_NAMED_PARAM = re.compile(r"(?<![:\w]):([a-zA-Z_][a-zA-Z0-9_]*)")


class DuplicateKeyError(Exception):
    """A UNIQUE constraint was violated. ``constraint`` names it when known."""

    def __init__(self, constraint: str | None, original: Exception):
        super().__init__(str(original))
        self.constraint = constraint
        self.original = original


class RetryableError(Exception):
    """Deadlock or lock-wait timeout: the whole transaction can be retried."""


@dataclass(frozen=True)
class DatabaseConfig:
    dialect: str  # "mysql" | "sqlite"
    host: str = ""
    port: int = 3306
    user: str = ""
    password: str = ""
    database: str = ""
    sqlite_path: str = ""


def parse_database_url(url: str) -> DatabaseConfig:
    """Accepts ``mysql://user:pass@host:3306/db`` or ``sqlite:///path/to/file.db``."""
    parsed = urlparse(url)
    scheme = parsed.scheme.split("+")[0]
    if scheme == "mysql":
        return DatabaseConfig(
            dialect="mysql",
            host=parsed.hostname or "localhost",
            port=parsed.port or 3306,
            user=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            database=parsed.path.lstrip("/"),
        )
    if scheme == "sqlite":
        path = url.split("sqlite:///", 1)[1] if "sqlite:///" in url else ":memory:"
        return DatabaseConfig(dialect="sqlite", sqlite_path=path or ":memory:")
    raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme!r}")


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _sqlite_datetime(raw: bytes) -> datetime:
    return datetime.fromisoformat(raw.decode().replace(" ", "T"))


sqlite3.register_converter("DATETIME", _sqlite_datetime)
sqlite3.register_adapter(datetime, lambda d: d.astimezone(timezone.utc).replace(tzinfo=None).isoformat(" "))


class Tx:
    """A unit of work bound to one open database transaction."""

    def __init__(self, conn: Any, dialect: str):
        self._conn = conn
        self.dialect = dialect

    def _translate(self, sql: str) -> str:
        if self.dialect == "mysql":
            return _NAMED_PARAM.sub(r"%(\1)s", sql)
        # SQLite: the write lock is already held (BEGIN IMMEDIATE), so FOR UPDATE is moot.
        return re.sub(r"\s+FOR\s+UPDATE\b", "", sql, flags=re.IGNORECASE)

    def _run(self, sql: str, params: dict[str, Any] | None):
        cur = self._conn.cursor()
        try:
            cur.execute(self._translate(sql), params or {})
        except Exception as exc:  # noqa: BLE001 - re-raised as a portable error
            _raise_portable(exc, self.dialect)
            raise
        return cur

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        """Run a statement and return the new row id (INSERT) or affected rows."""
        cur = self._run(sql, params)
        try:
            if sql.lstrip().upper().startswith("INSERT"):
                return int(cur.lastrowid)
            return int(cur.rowcount)
        finally:
            cur.close()

    def fetch_one(self, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        cur = self._run(sql, params)
        try:
            row = cur.fetchone()
            return self._row(cur, row) if row is not None else None
        finally:
            cur.close()

    def fetch_all(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        cur = self._run(sql, params)
        try:
            return [self._row(cur, r) for r in cur.fetchall()]
        finally:
            cur.close()

    def fetch_value(self, sql: str, params: dict[str, Any] | None = None) -> Any:
        row = self.fetch_one(sql, params)
        return None if row is None else next(iter(row.values()))

    @staticmethod
    def _row(cur: Any, row: Any) -> dict[str, Any]:
        if isinstance(row, dict):
            data = dict(row)
        else:
            data = {d[0]: v for d, v in zip(cur.description, row)}
        for key, value in data.items():
            if isinstance(value, datetime):
                data[key] = _utc(value)
        return data


def _raise_portable(exc: Exception, dialect: str) -> None:
    """Translate driver-specific errors into DuplicateKeyError / RetryableError."""
    if dialect == "sqlite":
        if isinstance(exc, sqlite3.IntegrityError) and "UNIQUE" in str(exc):
            # "UNIQUE constraint failed: items.sku" -> map column to constraint name
            column = str(exc).rsplit(":", 1)[-1].strip()
            constraint = {
                "items.sku": "uq_items_sku",
                "stock_transactions.idempotency_key": "uq_txn_idempotency_key",
                "alerts.active_item_id": "uq_alerts_one_active_per_item",
            }.get(column, column)
            raise DuplicateKeyError(constraint, exc) from exc
        if isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc):
            raise RetryableError(str(exc)) from exc
        return
    import pymysql  # imported lazily so SQLite-only runs don't need the driver

    if isinstance(exc, pymysql.err.IntegrityError) and exc.args and exc.args[0] == 1062:
        match = re.search(r"for key '(?:[\w]+\.)?([\w]+)'", str(exc.args[1]))
        raise DuplicateKeyError(match.group(1) if match else None, exc) from exc
    if isinstance(exc, pymysql.err.OperationalError) and exc.args and exc.args[0] in (1205, 1213):
        raise RetryableError(str(exc)) from exc


class Database:
    def __init__(self, url: str):
        self.config = parse_database_url(url)
        self.dialect = self.config.dialect

    def connect(self) -> Any:
        cfg = self.config
        if cfg.dialect == "mysql":
            import pymysql

            return pymysql.connect(
                host=cfg.host,
                port=cfg.port,
                user=cfg.user,
                password=cfg.password,
                database=cfg.database,
                charset="utf8mb4",
                autocommit=True,  # transactions are opened explicitly with BEGIN
                cursorclass=pymysql.cursors.DictCursor,
                init_command="SET SESSION transaction_isolation = 'READ-COMMITTED', time_zone = '+00:00'",
            )
        conn = sqlite3.connect(
            cfg.sqlite_path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level=None,  # we issue BEGIN/COMMIT ourselves
            timeout=30,
            check_same_thread=False,
        )
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @contextmanager
    def transaction(self, conn: Any, readonly: bool = False) -> Iterator[Tx]:
        """Open a transaction on ``conn``; commit on success, roll back on error."""
        if self.dialect == "mysql":
            conn.begin()
        else:
            try:
                conn.execute("BEGIN" if readonly else "BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                raise RetryableError(str(exc)) from exc
        try:
            yield Tx(conn, self.dialect)
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()

    def run_in_transaction(self, conn: Any, fn: Callable[[Tx], T], attempts: int = 3) -> T:
        """Run ``fn`` inside a transaction, retrying on deadlock / lock timeout.

        ``fn`` must be safe to re-run from scratch: everything it did in a failed
        attempt was rolled back, so it simply starts over.
        """
        for attempt in range(1, attempts + 1):
            try:
                with self.transaction(conn) as tx:
                    return fn(tx)
            except RetryableError:
                if attempt == attempts:
                    raise
                log.warning("Retrying transaction after lock conflict (attempt %s)", attempt)
                time.sleep(0.05 * attempt)
        raise AssertionError("unreachable")


def migrations_dir(dialect: str) -> Path:
    return Path(__file__).resolve().parent.parent / "migrations" / dialect


def split_mysql_statements(sql: str) -> list[str]:
    """Split a migration file on ';' at end of line, ignoring '--' comment lines."""
    statements: list[str] = []
    buf: list[str] = []
    for line in sql.splitlines():
        if line.strip().startswith("--") and not buf:
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            if stmt:
                statements.append(stmt)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def apply_migrations(db: Database, conn: Any) -> list[str]:
    """Apply any ``migrations/<dialect>/*.sql`` files not yet recorded. Returns applied names."""
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version VARCHAR(255) NOT NULL PRIMARY KEY,"
        " applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    cur.execute("SELECT version FROM schema_migrations")
    done = {r["version"] if isinstance(r, dict) else r[0] for r in cur.fetchall()}
    cur.close()

    applied: list[str] = []
    for path in sorted(migrations_dir(db.dialect).glob("*.sql")):
        if path.name in done:
            continue
        sql = path.read_text(encoding="utf-8")
        if db.dialect == "sqlite":
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (path.name,))
        else:
            # MySQL DDL auto-commits, so a migration is not atomic. Keep each file small
            # and idempotent-friendly; the version row is written only after it succeeds.
            cur = conn.cursor()
            for stmt in split_mysql_statements(sql):
                cur.execute(stmt)
            cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
            cur.close()
        applied.append(path.name)
        log.info("Applied migration %s", path.name)
    return applied
