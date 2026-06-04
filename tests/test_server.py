"""Tests for the MCP tools (called directly with a fake Context)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from soi_mcp import server


def test_normalize_zip_variants() -> None:
    assert server._normalize_zip("90210") == "90210"
    assert server._normalize_zip("90210-1234") == "90210"  # ZIP+4 trimmed
    with pytest.raises(ValueError, match="Not a 5-digit"):
        server._normalize_zip("abc")


def test_normalize_zip_rejects_rollups() -> None:
    with pytest.raises(ValueError, match="reserved SOI rollup"):
        server._normalize_zip("00000")
    with pytest.raises(ValueError, match="reserved SOI rollup"):
        server._normalize_zip("99999")


async def test_lookup_zip(ctx: SimpleNamespace) -> None:
    info = await server.lookup_zip("90210", ctx)
    assert info.zipcode == "90210"
    assert info.state == "CA"
    assert info.returns == 1500
    assert info.tax_year == 2022


async def test_lookup_unknown_zip_errors(ctx: SimpleNamespace) -> None:
    with pytest.raises(ValueError, match="No SOI data for ZIP"):
        await server.lookup_zip("00601", ctx)


async def test_get_income(ctx: SimpleNamespace) -> None:
    inc = await server.get_income("90210", ctx)
    assert inc.adjusted_gross_income == 387_000_000
    assert inc.avg_agi_per_return == 258_000


async def test_get_agi_distribution(ctx: SimpleNamespace) -> None:
    dist = await server.get_agi_distribution("90210", ctx)
    assert len(dist.brackets) == 6
    assert dist.brackets[-1].agi_stub == 6
    assert dist.brackets[-1].returns_pct == 22.0


async def test_get_tax(ctx: SimpleNamespace) -> None:
    tax = await server.get_tax("90210", ctx)
    # A10300 across stubs: 260+600+800+1000+9000+90000 = 101,660 (×1000 USD).
    assert tax.total_tax_liability == 101_660_000
    assert tax.avg_total_tax_per_return == round(101_660_000 / 1500)


async def test_get_credits(ctx: SimpleNamespace) -> None:
    cr = await server.get_credits("90210", ctx)
    assert cr.eitc_returns == 50
    assert {t.qualifying_children for t in cr.eitc_by_children} == {
        "none",
        "one",
        "two",
        "three or more",
    }


async def test_get_deductions(ctx: SimpleNamespace) -> None:
    ded = await server.get_deductions("90210", ctx)
    assert ded.itemized_returns == 260  # 30+30+0+0+0+200
    assert ded.itemizing_pct == pytest.approx(260 / 1500 * 100, abs=0.1)


async def test_get_filing_status(ctx: SimpleNamespace) -> None:
    fs = await server.get_filing_status("90210", ctx)
    assert fs.single_returns == 730
    assert fs.electronically_filed_pct == 96.0


async def test_compare_zips_ranks(ctx: SimpleNamespace) -> None:
    comp = await server.compare_zips(["10001", "90210"], "avg_agi_per_return", ctx)
    assert comp.results[0].zipcode == "90210"
    assert comp.metric == "avg_agi_per_return"


async def test_compare_zips_empty_errors(ctx: SimpleNamespace) -> None:
    with pytest.raises(ValueError, match="at least one ZIP"):
        await server.compare_zips([], "total_returns", ctx)


async def test_compare_zips_unknown_metric_errors(ctx: SimpleNamespace) -> None:
    with pytest.raises(ValueError, match="Unknown metric"):
        await server.compare_zips(["90210"], "bogus", ctx)


async def test_get_state_totals(ctx: SimpleNamespace) -> None:
    st = await server.get_state_totals("California", ctx)  # full name resolves
    assert st.state == "CA"
    assert st.returns == 10_000_000
    assert len(st.brackets) == 6


async def test_get_state_totals_missing_rollup_errors(ctx: SimpleNamespace) -> None:
    # NY has ZIP rows in the seed but no 00000 state-total rollup.
    with pytest.raises(ValueError, match="No SOI state-total data"):
        await server.get_state_totals("NY", ctx)


async def test_get_state_totals_unknown_state_errors(ctx: SimpleNamespace) -> None:
    with pytest.raises(ValueError, match="Unknown state"):
        await server.get_state_totals("Atlantis", ctx)


async def test_get_soi_field(ctx: SimpleNamespace) -> None:
    val = await server.get_soi_field("90210", "a00100", ctx)
    assert val.field == "A00100"
    assert val.unit == "USD"
    assert val.value == 387_000_000


async def test_get_soi_field_count_unit(ctx: SimpleNamespace) -> None:
    val = await server.get_soi_field("90210", "N1", ctx)
    assert val.unit == "count"
    assert val.value == 1500


async def test_get_soi_field_unknown_errors(ctx: SimpleNamespace) -> None:
    with pytest.raises(ValueError, match="Unknown SOI field"):
        await server.get_soi_field("90210", "ZZZ", ctx)


async def test_get_soi_field_all_suppressed_is_none(ctx: SimpleNamespace) -> None:
    # 90211's single bracket has a blank A00100 → value propagates to None.
    val = await server.get_soi_field("90211", "A00100", ctx)
    assert val.value is None


async def test_compare_zips_dedupes(ctx: SimpleNamespace) -> None:
    comp = await server.compare_zips(["90210", "90210"], "total_returns", ctx)
    assert len(comp.results) == 1
