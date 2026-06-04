"""Tests for the local SQLite store."""

from __future__ import annotations

from soi_mcp.store import Store


def test_loaded_and_tax_year(seeded_store: Store) -> None:
    assert seeded_store.is_loaded() is True
    assert seeded_store.tax_year() == 2022


def test_zip_stubs_ordered_and_excludes_rollups(seeded_store: Store) -> None:
    rows = seeded_store.zip_stubs("90210")
    assert [r["agi_stub"] for r in rows] == [1, 2, 3, 4, 5, 6]
    # zip_stubs must never return the reserved 00000 / 99999 rows.
    assert seeded_store.zip_stubs("00000") == []
    assert seeded_store.zip_stubs("99999") == []


def test_zip_stubs_unknown_zip_empty(seeded_store: Store) -> None:
    assert seeded_store.zip_stubs("00601") == []


def test_state_total_stubs(seeded_store: Store) -> None:
    rows = seeded_store.state_total_stubs("CA")
    assert {r["agi_stub"] for r in rows} == {1, 6}
    assert all(r["zipcode"] == "00000" for r in rows)


def test_states_list(seeded_store: Store) -> None:
    # Only states that carry a 00000 rollup are reported (CA in the seed).
    assert seeded_store.states() == ["CA"]


def test_metadata_counts(seeded_store: Store) -> None:
    meta = seeded_store.metadata()
    assert meta["tax_year"] == "2022"
    # Distinct real ZIPs: 90210, 10001, 90211 — the 00000/99999 rows excluded.
    assert meta["zip_count"] == "3"


def test_replace_all_is_idempotent(seeded_store: Store) -> None:
    before = seeded_store.metadata()["row_count"]
    # Re-seeding with the same rows must not duplicate (atomic rebuild).
    rows = seeded_store.zip_stubs("90210")
    seeded_store.replace_all(rows, 2022)
    after = seeded_store.metadata()["row_count"]
    assert int(after) == len(rows)
    assert int(before) >= int(after)


def test_amounts_stored_as_usd(seeded_store: Store) -> None:
    rows = seeded_store.zip_stubs("90210")
    stub6 = next(r for r in rows if r["agi_stub"] == 6)
    # Seed had A00100=300000 (thousands) → 300,000,000 USD.
    assert stub6["a00100"] == 300_000_000
