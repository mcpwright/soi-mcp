"""Tests for the formatting / derivation layer."""

from __future__ import annotations

import pytest

from soi_mcp import formatting as F
from soi_mcp.store import Store


def test_agg_sums_and_skips_none() -> None:
    rows = [{"n1": 10}, {"n1": None}, {"n1": 5}]
    assert F.agg(rows, "N1") == 15


def test_agg_all_none_is_none() -> None:
    rows = [{"n1": None}, {}]
    assert F.agg(rows, "N1") is None


def test_avg_and_pct_edges() -> None:
    assert F.avg(1000, 4) == 250
    assert F.avg(1000, 0) is None
    assert F.avg(None, 4) is None
    assert F.pct(25, 100) == 25.0
    assert F.pct(1, 0) is None
    assert F.pct(None, 10) is None


def test_to_income_aggregates_and_averages(seeded_store: Store) -> None:
    rows = seeded_store.zip_stubs("90210")
    inc = F.to_income("90210", rows, 2022)
    assert inc.returns == 1500
    assert inc.adjusted_gross_income == 387_000_000
    assert inc.avg_agi_per_return == 258_000
    assert inc.state == "CA"


def test_agi_distribution_shares(seeded_store: Store) -> None:
    rows = seeded_store.zip_stubs("90210")
    dist = F.to_agi_distribution("90210", rows, 2022)
    assert [b.agi_stub for b in dist.brackets] == [1, 2, 3, 4, 5, 6]
    assert dist.total_returns == 1500
    top = dist.brackets[-1]
    assert top.returns == 330
    assert top.returns_pct == 22.0
    # bracket return shares should sum to ~100%.
    assert round(sum(b.returns_pct or 0 for b in dist.brackets)) == 100


def test_filing_status_efile_pct(seeded_store: Store) -> None:
    rows = seeded_store.zip_stubs("90210")
    fs = F.to_filing_status("90210", rows, 2022)
    assert fs.single_returns == 730
    assert fs.electronically_filed_returns == 1440
    assert fs.electronically_filed_pct == 96.0


def test_credits_eitc_breakdown(seeded_store: Store) -> None:
    rows = seeded_store.zip_stubs("90210")
    cr = F.to_credits("90210", rows, 2022)
    assert cr.eitc_returns == 50
    none_tier = next(t for t in cr.eitc_by_children if t.qualifying_children == "none")
    assert none_tier.returns == 40


def test_suppressed_agi_is_none(seeded_store: Store) -> None:
    rows = seeded_store.zip_stubs("90211")  # single bracket, blank AGI cell
    inc = F.to_income("90211", rows, 2022)
    assert inc.returns == 40
    assert inc.adjusted_gross_income is None
    assert inc.avg_agi_per_return is None


def test_state_totals(seeded_store: Store) -> None:
    rows = seeded_store.state_total_stubs("CA")
    st = F.to_state_totals("CA", rows, 2022)
    assert st.returns == 10_000_000  # 8M + 2M
    assert st.adjusted_gross_income == 1_590_000_000_000  # (90,000,000 + 1,500,000,000) ×1000
    assert len(st.brackets) == 6


def test_compare_ranks_descending(seeded_store: Store) -> None:
    pairs = [
        ("90210", seeded_store.zip_stubs("90210")),
        ("10001", seeded_store.zip_stubs("10001")),
        ("00601", seeded_store.zip_stubs("00601")),  # no data
    ]
    comp = F.to_comparison(pairs, "avg_agi_per_return", 2022)
    assert comp.results[0].zipcode == "90210"
    assert comp.results[0].value == 258_000.0
    # ZIPs with no data sort last with a null value.
    assert comp.results[-1].zipcode == "00601"
    assert comp.results[-1].value is None


def test_pct_returns_200k_plus_metric(seeded_store: Store) -> None:
    rows = seeded_store.zip_stubs("90210")
    val = F.metric_value(rows, "pct_returns_200k_plus")
    assert val == 22.0


def test_metric_value_unknown_raises(seeded_store: Store) -> None:
    with pytest.raises(ValueError, match="Unknown metric"):
        F.metric_value(seeded_store.zip_stubs("90210"), "nope")


def test_available_metrics_nonempty() -> None:
    metrics = F.available_metrics()
    assert "avg_agi_per_return" in metrics
    assert "pct_returns_200k_plus" in metrics


def test_field_unit_and_label() -> None:
    assert F.field_unit("A00100") == "USD"
    assert F.field_unit("N1") == "count"
    assert "adjusted gross income" in F.field_label("A00100").lower()


def test_brackets_reconcile_with_totals_on_duplicate_stub() -> None:
    # Two rows share agi_stub=1 (e.g. a ZIP split across states). The bracket
    # figures must SUM, not last-write-wins, so they reconcile with the totals.
    rows = [
        {"agi_stub": 1, "n1": 100, "a00100": 1_000, "state": "KS"},
        {"agi_stub": 1, "n1": 50, "a00100": 500, "state": "MO"},
        {"agi_stub": 6, "n1": 10, "a00100": 9_000, "state": "KS"},
    ]
    dist = F.to_agi_distribution("66413", rows, 2022)
    bracket1 = next(b for b in dist.brackets if b.agi_stub == 1)
    assert bracket1.returns == 150  # summed, not 50
    assert dist.total_returns == 160
    # Per-bracket returns sum back to the total.
    assert sum(b.returns or 0 for b in dist.brackets) == dist.total_returns


def test_negative_aggregate_preserved() -> None:
    # Net capital loss / business loss aggregates are legitimately negative.
    rows = [{"agi_stub": 6, "n1": 100, "a01000": -250_000}]
    inc = F.to_income("90210", rows, 2022)
    assert inc.net_capital_gain == -250_000
