"""Tests for SOI field definitions and CSV parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from soi_mcp.fields import (
    AGI_STUBS,
    KIND,
    available_fields,
    parse_csv,
    resolve_field,
)

_CSV = """\
STATEFIPS,STATE,zipcode,agi_stub,N1,A00100,A00200
06,CA,90210,1,300.0000,4000.0000,3000.0000
06,CA,90210,6,330.0000,300000.0000,120000.0000
06,CA,90210,0,5.0000,1.0000,1.0000
06,CA,90211,6,40.0000,,5000.0000
"""


def _write(tmp_path: Path) -> Path:
    p = tmp_path / "mini.csv"
    p.write_text(_CSV, encoding="utf-8")
    return p


def test_parse_scales_amounts_and_rounds_counts(tmp_path: Path) -> None:
    recs = list(parse_csv(_write(tmp_path)))
    first = recs[0]
    assert first["zipcode"] == "90210"
    assert first["state"] == "CA"
    assert first["agi_stub"] == 1
    # counts stay as-is (rounded); amounts are scaled ×1000 to whole USD.
    assert first["n1"] == 300
    assert first["a00100"] == 4_000_000
    assert first["a00200"] == 3_000_000


def test_parse_skips_out_of_range_stub(tmp_path: Path) -> None:
    stubs = [r["agi_stub"] for r in parse_csv(_write(tmp_path))]
    # agi_stub 0 is dropped; only 1–6 are kept.
    assert 0 not in stubs
    assert set(stubs) == {1, 6, 6}.union({1})  # {1, 6}
    assert stubs.count(6) == 2


def test_parse_blank_cell_is_none(tmp_path: Path) -> None:
    recs = list(parse_csv(_write(tmp_path)))
    suppressed = next(r for r in recs if r["zipcode"] == "90211")
    assert suppressed["a00100"] is None
    assert suppressed["a00200"] == 5_000_000


def test_parse_preserves_leading_zero_zip(tmp_path: Path) -> None:
    p = tmp_path / "z.csv"
    p.write_text(
        "STATEFIPS,STATE,zipcode,agi_stub,N1\n09,CT,06010,1,100.0000\n",
        encoding="utf-8",
    )
    rec = next(iter(parse_csv(p)))
    assert rec["zipcode"] == "06010"


def test_resolve_field_case_insensitive() -> None:
    assert resolve_field("a00100") == "A00100"
    assert resolve_field("  N1 ") == "N1"


def test_resolve_field_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown SOI field"):
        resolve_field("NOPE")


def test_agi_stubs_are_six() -> None:
    assert sorted(AGI_STUBS) == [1, 2, 3, 4, 5, 6]
    assert AGI_STUBS[6][0] == "$200,000 or more"


def test_kinds_cover_available_fields() -> None:
    for code in available_fields():
        assert KIND[code] in {"count", "amount"}
