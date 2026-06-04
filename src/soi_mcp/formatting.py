"""Helpers that shape stored SOI bracket-rows into the tool return models.

A ZIP's data is six rows (one per AGI bracket). Aggregate tools sum across the
brackets; ``get_agi_distribution`` keeps them apart. Derived figures — averages
per return, bracket shares, percent itemizing — are simple, transparent ratios of
public SOI fields, never the private scoring models that live elsewhere.

Suppression note: a 0 in the source can mean a true zero, a suppressed cell
(<20 returns), or a value collapsed into another bracket — these are
indistinguishable, so summed totals slightly understate reality and won't match
the state 00000 rollup. We sum the non-null cells and surface the caveat in docs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .fields import AGI_STUBS, COLUMN, KIND, LABEL
from .models import (
    AgiBracket,
    AgiDistribution,
    Comparison,
    Credits,
    Deductions,
    EitcTier,
    FilingStatus,
    Income,
    StateTotals,
    Tax,
    ZipInfo,
    ZipMetric,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

Row = dict[str, object]


def _num(value: object) -> int | None:
    """A stored cell as an int, or None if missing (bool is never a count)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def agg(rows: Sequence[Row], code: str) -> int | None:
    """Sum a SOI field across bracket rows; None if no bracket has a value."""
    col = COLUMN[code]
    total = 0
    seen = False
    for r in rows:
        v = _num(r.get(col))
        if v is not None:
            total += v
            seen = True
    return total if seen else None


def avg(total: int | None, count: int | None) -> int | None:
    """``total / count`` rounded to a whole number, or None if not computable."""
    if total is None or not count:
        return None
    return round(total / count)


def pct(part: int | None, whole: int | None, digits: int = 1) -> float | None:
    """``part / whole`` as a 0-100 percentage, or None if either is missing/zero."""
    if part is None or not whole:
        return None
    return round(100.0 * part / whole, digits)


def _state(rows: Sequence[Row]) -> str | None:
    if not rows:
        return None
    s = rows[0].get("state")
    return s if isinstance(s, str) else None


def to_zip_info(zipcode: str, rows: Sequence[Row], tax_year: int) -> ZipInfo:
    return ZipInfo(
        zipcode=zipcode,
        state=_state(rows),
        returns=agg(rows, "N1"),
        individuals=agg(rows, "N2"),
        tax_year=tax_year,
    )


def to_income(zipcode: str, rows: Sequence[Row], tax_year: int) -> Income:
    returns = agg(rows, "N1")
    agi = agg(rows, "A00100")
    return Income(
        zipcode=zipcode,
        state=_state(rows),
        returns=returns,
        adjusted_gross_income=agi,
        avg_agi_per_return=avg(agi, returns),
        total_income=agg(rows, "A02650"),
        salaries_and_wages=agg(rows, "A00200"),
        taxable_interest=agg(rows, "A00300"),
        ordinary_dividends=agg(rows, "A00600"),
        business_net_income=agg(rows, "A00900"),
        net_capital_gain=agg(rows, "A01000"),
        tax_year=tax_year,
    )


def _brackets(rows: Sequence[Row]) -> tuple[list[AgiBracket], int | None, int | None]:
    """Build per-bracket entries plus the totals used for their shares."""
    total_returns = agg(rows, "N1")
    total_agi = agg(rows, "A00100")
    # Group rows by bracket and SUM within each (not last-write-wins): if a ZIP
    # ever carried two rows for one bracket — e.g. a 5-digit ZIP split across two
    # states — the per-bracket figures still reconcile with the totals.
    by_stub: dict[int, list[Row]] = {}
    for r in rows:
        stub = _num(r.get("agi_stub"))
        if stub is not None:
            by_stub.setdefault(stub, []).append(r)
    brackets = []
    for stub in sorted(AGI_STUBS):
        srows = by_stub.get(stub, [])
        n = agg(srows, "N1")
        a = agg(srows, "A00100")
        brackets.append(
            AgiBracket(
                agi_stub=stub,
                label=AGI_STUBS[stub][0],
                returns=n,
                returns_pct=pct(n, total_returns),
                adjusted_gross_income=a,
                agi_pct=pct(a, total_agi),
            )
        )
    return brackets, total_returns, total_agi


def to_agi_distribution(
    zipcode: str, rows: Sequence[Row], tax_year: int
) -> AgiDistribution:
    brackets, total_returns, total_agi = _brackets(rows)
    return AgiDistribution(
        zipcode=zipcode,
        state=_state(rows),
        total_returns=total_returns,
        total_agi=total_agi,
        brackets=brackets,
        tax_year=tax_year,
    )


def to_tax(zipcode: str, rows: Sequence[Row], tax_year: int) -> Tax:
    returns = agg(rows, "N1")
    total_liability = agg(rows, "A10300")
    return Tax(
        zipcode=zipcode,
        state=_state(rows),
        returns=returns,
        income_tax=agg(rows, "A06500"),
        income_tax_before_credits=agg(rows, "A05800"),
        total_tax_liability=total_liability,
        total_tax_payments=agg(rows, "A10600"),
        avg_total_tax_per_return=avg(total_liability, returns),
        tax_year=tax_year,
    )


_EITC_TIERS = (
    ("none", "N59661", "A59661"),
    ("one", "N59662", "A59662"),
    ("two", "N59663", "A59663"),
    ("three or more", "N59664", "A59664"),
)


def to_credits(zipcode: str, rows: Sequence[Row], tax_year: int) -> Credits:
    return Credits(
        zipcode=zipcode,
        state=_state(rows),
        eitc_returns=agg(rows, "N59660"),
        eitc_amount=agg(rows, "A59660"),
        eitc_by_children=[
            EitcTier(
                qualifying_children=label,
                returns=agg(rows, n_code),
                amount=agg(rows, a_code),
            )
            for label, n_code, a_code in _EITC_TIERS
        ],
        additional_ctc_returns=agg(rows, "N11070"),
        additional_ctc_amount=agg(rows, "A11070"),
        tax_year=tax_year,
    )


def to_deductions(zipcode: str, rows: Sequence[Row], tax_year: int) -> Deductions:
    returns = agg(rows, "N1")
    itemized_returns = agg(rows, "N04470")
    return Deductions(
        zipcode=zipcode,
        state=_state(rows),
        returns=returns,
        standard_deduction_returns=agg(rows, "N04450"),
        standard_deduction_amount=agg(rows, "A04450"),
        itemized_returns=itemized_returns,
        itemized_amount=agg(rows, "A04470"),
        salt_returns=agg(rows, "N18300"),
        salt_amount=agg(rows, "A18300"),
        itemizing_pct=pct(itemized_returns, returns),
        tax_year=tax_year,
    )


def to_filing_status(zipcode: str, rows: Sequence[Row], tax_year: int) -> FilingStatus:
    total_returns = agg(rows, "N1")
    e_filed = agg(rows, "ELF")
    return FilingStatus(
        zipcode=zipcode,
        state=_state(rows),
        total_returns=total_returns,
        single_returns=agg(rows, "MARS1"),
        married_joint_returns=agg(rows, "MARS2"),
        head_of_household_returns=agg(rows, "MARS4"),
        elderly_returns=agg(rows, "ELDERLY"),
        electronically_filed_returns=e_filed,
        electronically_filed_pct=pct(e_filed, total_returns),
        tax_year=tax_year,
    )


def to_state_totals(state: str, rows: Sequence[Row], tax_year: int) -> StateTotals:
    brackets, total_returns, total_agi = _brackets(rows)
    return StateTotals(
        state=state,
        returns=total_returns,
        individuals=agg(rows, "N2"),
        adjusted_gross_income=total_agi,
        avg_agi_per_return=avg(total_agi, total_returns),
        income_tax=agg(rows, "A06500"),
        total_tax_liability=agg(rows, "A10300"),
        brackets=brackets,
        tax_year=tax_year,
    )


def _returns_200k_plus_pct(rows: Sequence[Row]) -> float | None:
    """Share of returns in the top AGI bracket ($200k+), 0-100."""
    total = agg(rows, "N1")
    top_rows = [r for r in rows if _num(r.get("agi_stub")) == 6]
    return pct(agg(top_rows, "N1"), total)


# Scalar metrics rankable across ZIPs: name -> extractor(bracket-rows).
# Aggregates and the same derived figures the single-ZIP tools expose.
_METRICS: dict[str, Callable[[Sequence[Row]], float | None]] = {
    "total_returns": lambda rows: agg(rows, "N1"),
    "adjusted_gross_income": lambda rows: agg(rows, "A00100"),
    "avg_agi_per_return": lambda rows: avg(agg(rows, "A00100"), agg(rows, "N1")),
    "pct_returns_200k_plus": _returns_200k_plus_pct,
    "total_income": lambda rows: agg(rows, "A02650"),
    "salaries_and_wages": lambda rows: agg(rows, "A00200"),
    "income_tax": lambda rows: agg(rows, "A06500"),
    "total_tax_liability": lambda rows: agg(rows, "A10300"),
    "avg_total_tax_per_return": lambda rows: avg(agg(rows, "A10300"), agg(rows, "N1")),
    "eitc_amount": lambda rows: agg(rows, "A59660"),
}


def available_metrics() -> list[str]:
    """The metric names accepted by ``compare_zips``."""
    return list(_METRICS)


def metric_value(rows: Sequence[Row], metric: str) -> float | None:
    """The value of ``metric`` for one ZIP's rows. Raises ValueError if unknown."""
    try:
        extractor = _METRICS[metric]
    except KeyError:
        raise ValueError(
            f"Unknown metric {metric!r}. Choose one of: "
            f"{', '.join(available_metrics())}."
        ) from None
    v = extractor(rows)
    return float(v) if v is not None else None


def to_comparison(
    rows_by_zip: Sequence[tuple[str, Sequence[Row]]], metric: str, tax_year: int
) -> Comparison:
    """Build a ranked Comparison from (zipcode, bracket-rows) pairs.

    Sorted by the metric value descending; ZIPs with no data are listed last.
    """
    results = [
        ZipMetric(zipcode=zipcode, value=metric_value(rows, metric) if rows else None)
        for zipcode, rows in rows_by_zip
    ]
    results.sort(key=lambda m: (m.value is None, -(m.value or 0.0)))
    return Comparison(metric=metric, tax_year=tax_year, results=results)


def field_unit(code: str) -> str:
    """'USD' for amount fields, 'count' for return counts."""
    return "USD" if KIND[code] == "amount" else "count"


def field_label(code: str) -> str:
    """The human-readable label for a SOI field code."""
    return LABEL[code]
