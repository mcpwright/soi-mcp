"""Local SQLite store for IRS SOI ZIP-code data — download-once, serve offline.

The SOI individual-income ZIP file is a static annual release (~166k rows, one
tax year, ~200 MB as CSV). Rather than re-download per query, we stream it once,
keep the curated columns in a local SQLite file under the OS cache dir, and serve
every lookup locally — instant and offline. ``refresh [year]`` re-pulls (a new
year drops yearly, ~2–3 years behind; older years stay available for comparison).

Each stored row is a (state, ZIP, AGI bracket) cell — all six brackets per ZIP
are kept so the distribution survives. Reads are synchronous (local SQLite); only
the one-time *load* touches the network, via the async ``SoiClient``.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from .fields import DATA_COLUMNS, OTHER_ZIP, STATE_TOTAL_ZIP, parse_csv

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from .soi_client import SoiClient

_APP_DIR = "mcpwright-soi"
_DB_NAME = "soi.sqlite3"

# Dimension columns stored alongside the data columns.
_DIM_COLUMNS = ["statefips", "state", "zipcode", "agi_stub"]
_ALL_COLUMNS = _DIM_COLUMNS + DATA_COLUMNS


def _cache_dir() -> Path:
    """The per-user cache directory for this platform."""
    # Bind to a local so mypy doesn't prune the other branches as unreachable
    # (it narrows direct `sys.platform` comparisons to the checking platform).
    platform = sys.platform
    if platform == "darwin":
        return Path.home() / "Library" / "Caches"
    if platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA")
        return Path(base) if base else Path.home() / "AppData" / "Local"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")


def default_store_path() -> Path:
    """Where the SQLite store lives (override with ``SOI_MCP_STORE``)."""
    override = os.environ.get("SOI_MCP_STORE")
    if override:
        return Path(override)
    return _cache_dir() / _APP_DIR / _DB_NAME


class Store:
    """A SQLite-backed local store of SOI data, keyed by (state, ZIP, bracket)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_store_path()
        self._conn: sqlite3.Connection | None = None

    # --- connection lifecycle ----------------------------------------------
    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            self._conn = conn
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # --- state -------------------------------------------------------------
    def is_loaded(self) -> bool:
        """True once the soi table exists and holds at least one row."""
        conn = self.connect()
        if not self._table_exists("soi"):
            return False
        count = conn.execute("SELECT COUNT(*) FROM soi").fetchone()[0]
        return bool(count)

    def tax_year(self) -> int | None:
        """The SOI tax year currently loaded, if any."""
        v = self._meta("tax_year")
        return int(v) if v is not None else None

    def metadata(self) -> dict[str, str]:
        conn = self.connect()
        if not self._table_exists("meta"):
            return {}
        return {
            str(r["key"]): str(r["value"])
            for r in conn.execute("SELECT key, value FROM meta")
        }

    # --- reads -------------------------------------------------------------
    def zip_stubs(self, zipcode: str) -> list[dict[str, object]]:
        """All AGI-bracket rows for one real ZIP, ordered by bracket (1–6).

        Excludes the reserved state-total (00000) and other (99999) rows so a
        plain ZIP lookup never collides with a rollup.
        """
        conn = self.connect()
        if not self._table_exists("soi"):
            return []
        rows = conn.execute(
            "SELECT * FROM soi WHERE zipcode = ? AND zipcode NOT IN (?, ?) "
            "ORDER BY agi_stub",
            (zipcode, STATE_TOTAL_ZIP, OTHER_ZIP),
        )
        return [self._row_dict(r) for r in rows]

    def state_total_stubs(self, state: str) -> list[dict[str, object]]:
        """The state-total (zipcode 00000) AGI-bracket rows for a USPS state."""
        conn = self.connect()
        if not self._table_exists("soi"):
            return []
        rows = conn.execute(
            "SELECT * FROM soi WHERE state = ? AND zipcode = ? ORDER BY agi_stub",
            (state, STATE_TOTAL_ZIP),
        )
        return [self._row_dict(r) for r in rows]

    def states(self) -> list[str]:
        """The USPS state codes present in the store (those with a 00000 rollup)."""
        conn = self.connect()
        if not self._table_exists("soi"):
            return []
        rows = conn.execute(
            "SELECT DISTINCT state FROM soi WHERE zipcode = ? ORDER BY state",
            (STATE_TOTAL_ZIP,),
        )
        return [str(r["state"]) for r in rows]

    # --- writes ------------------------------------------------------------
    def replace_all(
        self, records: Iterable[dict[str, object]], tax_year: int
    ) -> tuple[int, int]:
        """Atomically rebuild the store from ``records``.

        Returns ``(row_count, zip_count)`` — total bracket-rows stored and the
        number of distinct real ZIPs (excluding the 00000/99999 rollups).
        """
        conn = self.connect()
        col_defs = ", ".join(f'"{c}" INTEGER' for c in ("agi_stub", *DATA_COLUMNS))
        placeholders = ", ".join("?" for _ in _ALL_COLUMNS)
        with conn:  # one transaction
            conn.execute("DROP TABLE IF EXISTS soi")
            conn.execute(
                "CREATE TABLE soi ("
                "statefips TEXT, state TEXT, zipcode TEXT, "
                f"{col_defs}, "
                "PRIMARY KEY (state, zipcode, agi_stub))"
            )
            conn.executemany(
                f"INSERT OR REPLACE INTO soi ({', '.join(_ALL_COLUMNS)}) "
                f"VALUES ({placeholders})",
                self._tuples(records),
            )
            conn.execute("CREATE INDEX idx_soi_zip ON soi (zipcode)")
            row_count = conn.execute("SELECT COUNT(*) FROM soi").fetchone()[0]
            zip_count = conn.execute(
                "SELECT COUNT(DISTINCT zipcode) FROM soi WHERE zipcode NOT IN (?, ?)",
                (STATE_TOTAL_ZIP, OTHER_ZIP),
            ).fetchone()[0]
            conn.execute(
                "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
            )
            for key, value in (
                ("tax_year", str(tax_year)),
                ("row_count", str(row_count)),
                ("zip_count", str(zip_count)),
            ):
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                    (key, value),
                )
        return int(row_count), int(zip_count)

    # --- internals ---------------------------------------------------------
    @staticmethod
    def _row_dict(row: sqlite3.Row) -> dict[str, object]:
        # sqlite3.Row iterates VALUES, not column names — .keys() is required.
        return {key: row[key] for key in row.keys()}  # noqa: SIM118

    @staticmethod
    def _tuples(
        records: Iterable[dict[str, object]],
    ) -> Iterator[tuple[object, ...]]:
        for rec in records:
            yield tuple(rec.get(c) for c in _ALL_COLUMNS)

    def _table_exists(self, name: str) -> bool:
        conn = self.connect()
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()
            is not None
        )

    def _meta(self, key: str) -> str | None:
        conn = self.connect()
        if not self._table_exists("meta"):
            return None
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        return str(row["value"])


async def load_store(
    store: Store, client: SoiClient, *, year: int | None = None
) -> int:
    """Download a SOI ZIP-code year and (re)build the local store.

    Resolves the latest published tax year unless ``year`` is given, streams the
    CSV to a temp file, parses the curated columns, and writes them locally.
    Returns the tax year loaded.
    """
    tax_year = year if year is not None else await client.latest_year()
    with tempfile.TemporaryDirectory(prefix="soi-mcp-") as tmp:
        csv_path = Path(tmp) / f"{tax_year % 100:02d}zpallagi.csv"
        await client.download_csv(tax_year, csv_path)
        store.replace_all(parse_csv(csv_path), tax_year)
    return tax_year
