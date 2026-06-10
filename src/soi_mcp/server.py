"""SOI MCP server — IRS income/tax statistics by ZIP, inside your agent.

Built on the official MCP Python SDK (``mcp.server.fastmcp``). All tools are
read-only. Data is the IRS Statistics of Income (SOI) individual-income ZIP-code
release, bulk-downloaded once into a local SQLite store and served offline; only
the one-time download touches the network (no API key needed).
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast

from mcp.server.fastmcp import Context, FastMCP
from mcpwright_core import READ_ONLY, app_context, ensure_loaded, run_cli

from .fields import OTHER_ZIP, STATE_TOTAL_ZIP, resolve_field
from .formatting import (
    agg,
    available_metrics,
    field_label,
    field_unit,
    to_agi_distribution,
    to_comparison,
    to_credits,
    to_deductions,
    to_filing_status,
    to_income,
    to_state_totals,
    to_tax,
    to_zip_info,
)
from .models import (
    AgiDistribution,
    Comparison,
    Credits,
    Deductions,
    FilingStatus,
    Income,
    SoiFieldValue,
    StateTotals,
    Tax,
    ZipInfo,
)
from .soi_client import SoiClient, SoiError
from .states import resolve_state
from .store import Store, load_store

_INSTRUCTIONS = """\
Read-only access to U.S. IRS Statistics of Income (SOI) individual income-tax
data by ZIP code — figures aggregated from filed Form 1040 returns.

Typical flow:
- `lookup_zip` confirms a ZIP has SOI data and gives its return and individual
  counts — a good first call to validate a ZIP.
- `get_income` returns AGI, average AGI per return, and income components
  (wages, interest, dividends, business income, capital gains).
- `get_agi_distribution` is the distinctive one: the ZIP's returns and AGI split
  across the six IRS AGI brackets (<$25k, $25-50k, $50-75k, $75-100k, $100-200k,
  $200k+) — the income *shape* of a ZIP, not just an average.
- `get_tax` returns income tax, total tax liability, and average tax per return.
- `get_credits` returns EITC take-up (including by number of qualifying children)
  and the additional child tax credit.
- `get_deductions` returns standard vs. itemized deductions and the SALT total.
- `get_filing_status` returns single / married-joint / head-of-household and
  e-filing counts.
- `compare_zips` ranks several ZIPs by one metric (e.g. avg_agi_per_return,
  pct_returns_200k_plus, total_tax_liability).
- `get_state_totals` returns a whole state's totals and bracket mix.
- `get_soi_field` is an escape hatch: the raw value of one SOI field code (e.g.
  A00100) for a ZIP, limited to the fields in the store.

Notes:
- All dollar amounts are returned in whole USD (the source reports thousands).
  Counts are returns, rounded by the IRS to the nearest 10.
- Each result carries its `tax_year`. The SOI ZIP release lags ~2-3 years; the
  latest available year is loaded by default. Use `refresh <year>` for an older
  year (the data goes back many years at stable URLs).
- Small/suppressed cells: ZIPs with <100 returns and nonresidential ZIPs are
  excluded by the IRS, and items with <20 returns are suppressed — a 0 can be a
  suppressed cell rather than a true zero. A summed total can therefore slightly
  understate reality and won't equal the state total.
- The first call downloads the dataset into a local store (no API key); every
  call after that is local and offline.
"""


@dataclass
class AppContext:
    """Resources shared across requests for the lifetime of the server."""

    store: Store
    client: SoiClient
    load_lock: asyncio.Lock


@asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncIterator[AppContext]:
    """Own the local store + SOI client: open on startup, close on shutdown."""
    store = Store()
    client = SoiClient()
    try:
        yield AppContext(store=store, client=client, load_lock=asyncio.Lock())
    finally:
        await client.aclose()
        store.close()


mcp = FastMCP("soi", instructions=_INSTRUCTIONS, lifespan=_lifespan)


def _app(ctx: Context) -> AppContext:
    """The shared app resources from the lifespan context."""
    return app_context(ctx, AppContext)


def _normalize_zip(zip_code: str) -> str:
    """Validate and normalize a ZIP to a 5-digit string.

    Accepts a bare 5-digit ZIP or a ZIP+4 (the +4 is dropped). Rejects the
    reserved SOI rollup codes 00000 (state total) and 99999 (the "other" bucket).
    """
    digits = "".join(c for c in zip_code if c.isdigit())
    if len(digits) not in (5, 9):
        raise ValueError(f"Not a 5-digit US ZIP code: {zip_code!r}")
    zipcode = digits[:5]
    if zipcode in (STATE_TOTAL_ZIP, OTHER_ZIP):
        raise ValueError(
            f"{zipcode} is a reserved SOI rollup, not a real ZIP "
            "(00000 = state total, use get_state_totals; 99999 = the 'other' "
            "bucket of small/nonresidential ZIPs)."
        )
    return zipcode


async def _ensure_loaded(app: AppContext) -> int:
    """Make sure the local store is populated; return the loaded tax year.

    Lazily downloads the latest SOI ZIP file on first use if the store is empty.
    Serialized so concurrent first calls don't each kick off a download.
    """
    return await ensure_loaded(
        app.load_lock,
        is_loaded=app.store.is_loaded,
        load=lambda: load_store(app.store, app.client),
        version=lambda: cast(int, app.store.tax_year()),
    )


async def _zip_rows(
    app: AppContext, zip_code: str
) -> tuple[str, list[dict[str, object]], int]:
    """Resolve a ZIP to its stored bracket rows + the tax year, or raise."""
    tax_year = await _ensure_loaded(app)
    zipcode = _normalize_zip(zip_code)
    rows = app.store.zip_stubs(zipcode)
    if not rows:
        raise ValueError(
            f"No SOI data for ZIP {zipcode} — it may have fewer than 100 returns "
            "(folded into the IRS '99999' bucket) or be nonresidential."
        )
    return zipcode, rows, tax_year


@mcp.tool(title="Look up a ZIP", annotations=READ_ONLY)
async def lookup_zip(zip_code: str, ctx: Context) -> ZipInfo:
    """Confirm a ZIP has SOI data and return its return and individual counts.

    `zip_code`: a 5-digit US ZIP. A good first call to validate a ZIP before
    asking for more detail. Returns the state, number of returns, number of
    individuals, and the SOI tax year. ZIPs with <100 returns are excluded.
    """
    zipcode, rows, tax_year = await _zip_rows(_app(ctx), zip_code)
    return to_zip_info(zipcode, rows, tax_year)


@mcp.tool(title="Get income by ZIP", annotations=READ_ONLY)
async def get_income(zip_code: str, ctx: Context) -> Income:
    """Income measures for a ZIP: AGI, average AGI per return, and components.

    `zip_code`: a 5-digit US ZIP. Returns total adjusted gross income (AGI),
    average AGI per return, and the main income components — salaries and wages,
    taxable interest, ordinary dividends, business net income, and net capital
    gain. All dollar amounts in USD.

    Note: figures cover filed tax returns only. Average AGI is a *mean per
    return*, not a median per household, and AGI omits most nontaxable income —
    so it is not directly comparable to Census median household income.
    """
    zipcode, rows, tax_year = await _zip_rows(_app(ctx), zip_code)
    return to_income(zipcode, rows, tax_year)


@mcp.tool(title="Get AGI distribution by ZIP", annotations=READ_ONLY)
async def get_agi_distribution(zip_code: str, ctx: Context) -> AgiDistribution:
    """The income distribution of a ZIP across the six IRS AGI brackets.

    `zip_code`: a 5-digit US ZIP. Returns, for each bracket (<$25k, $25-50k,
    $50-75k, $75-100k, $100-200k, $200k+), the number of returns and total AGI
    plus each bracket's share of the ZIP's returns and AGI. This is the income
    *shape* of a ZIP — what a single median can't show.

    Note: a bracket showing 0 may be IRS-suppressed (<20 returns in that cell)
    rather than truly empty, so the other brackets' shares can be slightly
    overstated.
    """
    zipcode, rows, tax_year = await _zip_rows(_app(ctx), zip_code)
    return to_agi_distribution(zipcode, rows, tax_year)


@mcp.tool(title="Get tax by ZIP", annotations=READ_ONLY)
async def get_tax(zip_code: str, ctx: Context) -> Tax:
    """Tax measures for a ZIP: income tax, total liability, and average per return.

    `zip_code`: a 5-digit US ZIP. Returns income tax, income tax before credits,
    total tax liability (broader — includes self-employment tax and other taxes),
    total tax payments, and the average total tax per return. Amounts in USD.
    """
    zipcode, rows, tax_year = await _zip_rows(_app(ctx), zip_code)
    return to_tax(zipcode, rows, tax_year)


@mcp.tool(title="Get credits by ZIP", annotations=READ_ONLY)
async def get_credits(zip_code: str, ctx: Context) -> Credits:
    """Refundable-credit take-up for a ZIP: the EITC and additional child tax credit.

    `zip_code`: a 5-digit US ZIP. Returns the number of returns and total amount
    for the Earned Income Tax Credit (overall and split by number of qualifying
    children: none / one / two / three or more), plus the additional (refundable)
    child tax credit. Amounts in USD.

    Note: a 0 may be IRS-suppressed (<20 returns in each AGI-bracket cell)
    rather than a true zero — it does not prove no one claims the credit.
    """
    zipcode, rows, tax_year = await _zip_rows(_app(ctx), zip_code)
    return to_credits(zipcode, rows, tax_year)


@mcp.tool(title="Get deductions by ZIP", annotations=READ_ONLY)
async def get_deductions(zip_code: str, ctx: Context) -> Deductions:
    """Deduction measures for a ZIP: standard vs. itemized, plus SALT.

    `zip_code`: a 5-digit US ZIP. Returns the count and amount of standard
    deductions and itemized deductions, the taxes-paid (SALT) deduction, and the
    percent of returns that itemized. Amounts in USD.

    Note: a 0 may be IRS-suppressed (<20 returns in each AGI-bracket cell)
    rather than a true zero — it does not prove no one in the ZIP itemizes.
    """
    zipcode, rows, tax_year = await _zip_rows(_app(ctx), zip_code)
    return to_deductions(zipcode, rows, tax_year)


@mcp.tool(title="Get filing status by ZIP", annotations=READ_ONLY)
async def get_filing_status(zip_code: str, ctx: Context) -> FilingStatus:
    """Filing-status mix for a ZIP: single / married-joint / head-of-household.

    `zip_code`: a 5-digit US ZIP. Returns the number of single, married-filing-
    jointly, and head-of-household returns, the number of elderly returns (age
    65+), and the count and share of electronically filed returns.

    Note: a 0 count may be IRS-suppressed (<20 returns in each AGI-bracket
    cell) rather than truly absent.
    """
    zipcode, rows, tax_year = await _zip_rows(_app(ctx), zip_code)
    return to_filing_status(zipcode, rows, tax_year)


@mcp.tool(title="Compare ZIPs", annotations=READ_ONLY)
async def compare_zips(zips: list[str], metric: str, ctx: Context) -> Comparison:
    """Rank several ZIPs by a single metric, highest value first.

    `zips`: a list of 5-digit US ZIPs to compare. `metric`: one of
    `total_returns`, `adjusted_gross_income`, `avg_agi_per_return`,
    `pct_returns_200k_plus`, `total_income`, `salaries_and_wages`, `income_tax`,
    `total_tax_liability`, `avg_total_tax_per_return`, `eitc_amount`. Returns each
    ZIP's value, sorted descending; ZIPs with no SOI data are listed last. A 0
    for a sparse metric (e.g. `eitc_amount`) may be IRS-suppressed, not a true
    zero.
    """
    if not zips:
        raise ValueError("Pass at least one ZIP to compare.")
    if metric not in available_metrics():
        raise ValueError(
            f"Unknown metric {metric!r}. Choose one of: "
            f"{', '.join(available_metrics())}."
        )
    app = _app(ctx)
    tax_year = await _ensure_loaded(app)
    # Normalize and de-duplicate while preserving order (a repeated ZIP shouldn't
    # appear twice in the ranking).
    unique_zips = list(dict.fromkeys(_normalize_zip(z) for z in zips))
    rows_by_zip = [(zc, app.store.zip_stubs(zc)) for zc in unique_zips]
    return to_comparison(rows_by_zip, metric, tax_year)


@mcp.tool(title="Get state totals", annotations=READ_ONLY)
async def get_state_totals(state: str, ctx: Context) -> StateTotals:
    """State-level SOI totals and AGI distribution from the IRS state rollup.

    `state`: a 2-letter USPS code (e.g. 'CA') or full state name (e.g.
    'California'). Returns the state's total returns, individuals, AGI, average
    AGI per return, income tax, total tax liability, and the income distribution
    across the six AGI brackets. Drawn from the IRS 00000 state-total row.
    """
    code = resolve_state(state)
    app = _app(ctx)
    tax_year = await _ensure_loaded(app)
    rows = app.store.state_total_stubs(code)
    if not rows:
        raise ValueError(f"No SOI state-total data for {code} in tax year {tax_year}.")
    return to_state_totals(code, rows, tax_year)


@mcp.tool(title="Get a raw SOI field", annotations=READ_ONLY)
async def get_soi_field(zip_code: str, field: str, ctx: Context) -> SoiFieldValue:
    """Raw value of a single SOI field for a ZIP — an escape hatch.

    `zip_code`: a 5-digit US ZIP. `field`: a SOI field code (e.g. `A00100` for
    AGI, `N1` for number of returns); case-insensitive. Returns that field summed
    across the ZIP's AGI brackets, with its label and unit (USD for amount fields,
    count for return counts). Limited to the fields held in the local store (the
    same ones the other tools draw on); an unknown field errors with the list.

    Note: a 0 may be IRS-suppressed (<20 returns in a cell) rather than a true
    zero, and a sum over suppressed cells slightly understates the real total.
    """
    code = resolve_field(field)
    zipcode, rows, tax_year = await _zip_rows(_app(ctx), zip_code)
    value = agg(rows, code)
    return SoiFieldValue(
        zipcode=zipcode,
        state=cast("str | None", rows[0].get("state")) if rows else None,
        field=code,
        label=field_label(code),
        unit=field_unit(code),
        value=value,
        tax_year=tax_year,
    )


async def _run_load(year: int | None) -> None:
    """`setup` / `refresh [year]`: download a SOI ZIP year into the local store."""
    store = Store()
    client = SoiClient()
    try:
        target = year if year is not None else await client.latest_year()
        print(
            f"Downloading IRS SOI ZIP data for tax year {target} into "
            f"{store.path} … (~200 MB, one-time)",
            file=sys.stderr,
        )
        loaded = await load_store(store, client, year=target)
        meta = store.metadata()
        print(
            f"Done: tax year {loaded}, {meta.get('zip_count', '?')} ZIPs, "
            f"{meta.get('row_count', '?')} bracket-rows.",
            file=sys.stderr,
        )
    finally:
        await client.aclose()
        store.close()


def main() -> None:
    """Console entry point.

    `mcpwright-soi` runs the MCP server over stdio (for Claude Desktop / Claude
    Code). `mcpwright-soi setup` downloads the latest SOI ZIP year; `mcpwright-soi
    refresh [year]` re-pulls (an optional 4-digit year loads that specific year).
    """
    run_cli(mcp, loader=_run_load, error=SoiError, accepts_year=True)
