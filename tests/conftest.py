"""Shared fixtures: a CSV builder, a seeded SQLite store, and a fake MCP Context.

Tests never touch the network. The store is seeded from an in-memory list of
rows written through the real ``parse_csv`` path (so parsing is exercised too),
and the ``ctx`` fixture mirrors the lifespan-provided ``AppContext`` the tools
read from ``ctx.request_context.lifespan_context``.
"""

from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from soi_mcp.fields import FIELDS, parse_csv
from soi_mcp.server import AppContext
from soi_mcp.soi_client import SoiClient
from soi_mcp.store import Store

if TYPE_CHECKING:
    from collections.abc import Iterator

import asyncio

# Header = the dimension columns plus every curated SOI field code.
_HEADER = ["STATEFIPS", "STATE", "zipcode", "agi_stub"] + [
    code for code, _label, _kind in FIELDS
]


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    """Write a SOI-shaped CSV; missing field cells default to '0', blanks stay blank."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(_HEADER)
        for r in rows:
            writer.writerow([r.get(col, "0") for col in _HEADER])


def _row(state: str, fips: str, zipcode: str, stub: int, **fields: object) -> dict:
    base: dict[str, object] = {
        "STATEFIPS": fips,
        "STATE": state,
        "zipcode": zipcode,
        "agi_stub": stub,
    }
    base.update(fields)
    return base


# A small but representative seed: one rich CA ZIP (all 6 brackets), one NY ZIP,
# a CA state-total (00000) rollup, the 99999 "other" bucket, and a ZIP with a
# blank (suppressed) AGI cell.
SEED_ROWS: list[dict[str, object]] = [
    # 90210 CA — all six brackets, amounts in $thousands (×1000 = USD at load).
    _row("CA", "06", "90210", 1, N1=300, N2=400, A00100=4000, A02650=4200,
         A00200=3000, MARS1=250, MARS2=30, MARS4=20, ELF=280, ELDERLY=40,
         N04450=270, N04470=30, A04470=900, N18300=30, A18300=300,
         N59660=50, A59660=120, N59661=40, A59661=60, N59662=10, A59662=60,
         N11070=20, A11070=40, A06500=200, A05800=210, A10300=260, A10600=300),
    _row("CA", "06", "90210", 2, N1=200, N2=260, A00100=7500, A02650=7600,
         A00200=6000, MARS1=150, MARS2=40, MARS4=10, ELF=190, ELDERLY=30,
         N04450=170, N04470=30, A04470=800, A06500=500, A10300=600),
    _row("CA", "06", "90210", 3, N1=150, N2=200, A00100=9000, A00200=7000,
         MARS1=90, MARS2=50, MARS4=10, ELF=140, A06500=700, A10300=800),
    _row("CA", "06", "90210", 4, N1=120, N2=170, A00100=10500, A00200=8000,
         MARS1=60, MARS2=55, ELF=115, A06500=900, A10300=1000),
    _row("CA", "06", "90210", 5, N1=400, N2=600, A00100=56000, A00200=40000,
         MARS1=120, MARS2=260, ELF=390, A06500=8000, A10300=9000),
    _row("CA", "06", "90210", 6, N1=330, N2=520, A00100=300000, A00200=120000,
         A01000=90000, A00600=20000, MARS1=60, MARS2=260, ELF=325,
         A06500=70000, A05800=72000, A10300=90000, A10600=95000,
         N04470=200, A04470=18000, N18300=200, A18300=8000),
    # 10001 NY — two brackets.
    _row("NY", "36", "10001", 1, N1=500, N2=650, A00100=6000, A00200=4500,
         N59660=120, A59660=300, MARS1=420, ELF=470),
    _row("NY", "36", "10001", 6, N1=80, N2=120, A00100=42000, A00200=20000,
         A06500=9000, A10300=11000, MARS2=60, ELF=78),
    # CA state-total rollup (zipcode 00000) — two brackets.
    _row("CA", "06", "00000", 1, N1=8_000_000, N2=11_000_000, A00100=90_000_000,
         A06500=3_000_000, A10300=3_500_000),
    _row("CA", "06", "00000", 6, N1=2_000_000, N2=4_000_000, A00100=1_500_000_000,
         A06500=300_000_000, A10300=320_000_000),
    # 99999 "other" bucket (CA) — must be excluded from real-ZIP lookups.
    _row("CA", "06", "99999", 1, N1=1_500, N2=1_800, A00100=20_000),
    # 90211 CA — a single bracket whose AGI cell is blank (suppressed).
    _row("CA", "06", "90211", 6, N1=40, N2=60, A00100="", A00200=5000),
]


@pytest.fixture
def seeded_store(tmp_path: Path) -> Iterator[Store]:
    """A Store seeded from SEED_ROWS via the real parse_csv path, tax year 2022."""
    csv_path = tmp_path / "seed.csv"
    write_csv(csv_path, SEED_ROWS)
    store = Store(tmp_path / "soi.sqlite3")
    store.replace_all(parse_csv(csv_path), 2022)
    yield store
    store.close()


@pytest.fixture
def ctx(seeded_store: Store) -> Iterator[SimpleNamespace]:
    """A fake MCP Context whose lifespan_context is a seeded AppContext."""
    client = SoiClient()
    app = AppContext(store=seeded_store, client=client, load_lock=asyncio.Lock())
    yield SimpleNamespace(request_context=SimpleNamespace(lifespan_context=app))
    asyncio.run(client.aclose())
