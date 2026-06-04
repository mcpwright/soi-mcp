"""Local SQLite store for IRS SOI ZIP-code data — download-once, serve offline.

The SOI individual-income ZIP file is a static annual release (~166k rows, one
tax year, ~200 MB as CSV). Rather than re-download per query, we stream it once,
keep the curated columns in a local SQLite file under the OS cache dir, and serve
every lookup locally — instant and offline. ``refresh [year]`` re-pulls (a new
year drops yearly, ~2–3 years behind; older years stay available for comparison).

Each stored row is a (state, ZIP, AGI bracket) cell — all six brackets per ZIP
are kept so the distribution survives. Reads are synchronous (local SQLite); only
the one-time *load* touches the network, via the async ``SoiClient``. The store
plumbing (connection, ``meta`` table, load-state) lives in
``mcpwright_core.BaseStore``; this adds the SOI schema and queries.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from mcpwright_core import BaseStore

from .fields import DATA_COLUMNS, OTHER_ZIP, STATE_TOTAL_ZIP, parse_csv

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from .soi_client import SoiClient

# Dimension columns stored alongside the data columns.
_DIM_COLUMNS = ["statefips", "state", "zipcode", "agi_stub"]
_ALL_COLUMNS = _DIM_COLUMNS + DATA_COLUMNS


class Store(BaseStore):
    """A SQLite-backed local store of SOI data, keyed by (state, ZIP, bracket)."""

    APP_DIR = "mcpwright-soi"
    DB_NAME = "soi.sqlite3"
    STORE_ENV_VAR = "SOI_MCP_STORE"
    DATA_TABLE = "soi"

    def tax_year(self) -> int | None:
        """The SOI tax year currently loaded, if any."""
        return self._int_meta("tax_year")

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
            self._write_meta(
                conn,
                {
                    "tax_year": tax_year,
                    "row_count": row_count,
                    "zip_count": zip_count,
                },
            )
        return int(row_count), int(zip_count)

    # --- internals ---------------------------------------------------------
    @staticmethod
    def _tuples(
        records: Iterable[dict[str, object]],
    ) -> Iterator[tuple[object, ...]]:
        for rec in records:
            yield tuple(rec.get(c) for c in _ALL_COLUMNS)


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
