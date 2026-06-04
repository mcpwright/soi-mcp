"""Typed models returned by the SOI MCP tools.

These are the tool *return* types — the MCP SDK derives an output schema from
them, so agents receive structured data, not just text. All dollar amounts are
in **whole USD** (the source reports thousands; we scale at load). Counts are
numbers of returns, rounded by the IRS to the nearest 10. Every figure is for one
tax year, summed across a ZIP's six AGI brackets unless noted.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ZipInfo(BaseModel):
    """Basic SOI identity and size for a ZIP."""

    zipcode: str = Field(description="5-digit ZIP code")
    state: str | None = Field(default=None, description="2-letter USPS state code")
    returns: int | None = Field(
        default=None, description="Total number of tax returns filed from this ZIP"
    )
    individuals: int | None = Field(
        default=None,
        description="Total number of individuals (filers plus dependents)",
    )
    tax_year: int = Field(description="SOI tax year of the data")


class Income(BaseModel):
    """Income measures for a ZIP (all dollar amounts in USD)."""

    zipcode: str = Field(description="5-digit ZIP code")
    state: str | None = Field(default=None, description="2-letter USPS state code")
    returns: int | None = Field(default=None, description="Number of returns")
    adjusted_gross_income: int | None = Field(
        default=None, description="Total adjusted gross income (AGI)"
    )
    avg_agi_per_return: int | None = Field(
        default=None, description="AGI divided by the number of returns"
    )
    total_income: int | None = Field(default=None, description="Total income amount")
    salaries_and_wages: int | None = Field(
        default=None, description="Salaries and wages amount"
    )
    taxable_interest: int | None = Field(
        default=None, description="Taxable interest amount"
    )
    ordinary_dividends: int | None = Field(
        default=None, description="Ordinary dividends amount"
    )
    business_net_income: int | None = Field(
        default=None,
        description="Business or professional net income (less loss) amount",
    )
    net_capital_gain: int | None = Field(
        default=None, description="Net capital gain (less loss) amount"
    )
    tax_year: int = Field(description="SOI tax year of the data")


class AgiBracket(BaseModel):
    """One AGI bracket's share of a ZIP's returns and income."""

    agi_stub: int = Field(description="AGI bracket code, 1 (lowest) to 6 (highest)")
    label: str = Field(description="AGI range, e.g. '$100,000 under $200,000'")
    returns: int | None = Field(
        default=None, description="Number of returns in this AGI bracket"
    )
    returns_pct: float | None = Field(
        default=None,
        description="Percent of the ZIP's returns in this bracket (0-100)",
    )
    adjusted_gross_income: int | None = Field(
        default=None, description="Total AGI of returns in this bracket (USD)"
    )
    agi_pct: float | None = Field(
        default=None,
        description="Percent of the ZIP's total AGI in this bracket (0-100)",
    )


class AgiDistribution(BaseModel):
    """The income distribution of a ZIP across the six AGI brackets."""

    zipcode: str = Field(description="5-digit ZIP code")
    state: str | None = Field(default=None, description="2-letter USPS state code")
    total_returns: int | None = Field(
        default=None, description="Total returns across all brackets"
    )
    total_agi: int | None = Field(
        default=None, description="Total AGI across all brackets (USD)"
    )
    brackets: list[AgiBracket] = Field(
        description="One entry per AGI bracket, ordered 1 (lowest) to 6 (highest)"
    )
    tax_year: int = Field(description="SOI tax year of the data")


class Tax(BaseModel):
    """Tax measures for a ZIP (all dollar amounts in USD)."""

    zipcode: str = Field(description="5-digit ZIP code")
    state: str | None = Field(default=None, description="2-letter USPS state code")
    returns: int | None = Field(default=None, description="Number of returns")
    income_tax: int | None = Field(
        default=None,
        description="Income tax amount (after credits, before other taxes)",
    )
    income_tax_before_credits: int | None = Field(
        default=None, description="Income tax before credits amount"
    )
    total_tax_liability: int | None = Field(
        default=None,
        description="Total tax liability (broader than income tax: includes "
        "self-employment tax, recapture, etc.)",
    )
    total_tax_payments: int | None = Field(
        default=None, description="Total tax payments amount"
    )
    avg_total_tax_per_return: int | None = Field(
        default=None, description="Total tax liability divided by the number of returns"
    )
    tax_year: int = Field(description="SOI tax year of the data")


class EitcTier(BaseModel):
    """EITC take-up for returns with a given number of qualifying children."""

    qualifying_children: str = Field(
        description="Number of qualifying children: 'none', 'one', 'two', or "
        "'three or more'"
    )
    returns: int | None = Field(default=None, description="Number of EITC returns")
    amount: int | None = Field(default=None, description="EITC amount (USD)")


class Credits(BaseModel):
    """Refundable-credit take-up for a ZIP (EITC and the additional CTC)."""

    zipcode: str = Field(description="5-digit ZIP code")
    state: str | None = Field(default=None, description="2-letter USPS state code")
    eitc_returns: int | None = Field(
        default=None, description="Number of returns claiming the EITC"
    )
    eitc_amount: int | None = Field(default=None, description="Total EITC amount (USD)")
    eitc_by_children: list[EitcTier] = Field(
        description="EITC returns and amount split by number of qualifying children"
    )
    additional_ctc_returns: int | None = Field(
        default=None,
        description="Number of returns with the additional (refundable) child tax credit",
    )
    additional_ctc_amount: int | None = Field(
        default=None,
        description="Additional (refundable) child tax credit amount (USD)",
    )
    tax_year: int = Field(description="SOI tax year of the data")


class Deductions(BaseModel):
    """Deduction measures for a ZIP (all dollar amounts in USD)."""

    zipcode: str = Field(description="5-digit ZIP code")
    state: str | None = Field(default=None, description="2-letter USPS state code")
    returns: int | None = Field(default=None, description="Number of returns")
    standard_deduction_returns: int | None = Field(
        default=None, description="Number of returns claiming the standard deduction"
    )
    standard_deduction_amount: int | None = Field(
        default=None, description="Standard deduction amount"
    )
    itemized_returns: int | None = Field(
        default=None, description="Number of returns with itemized deductions"
    )
    itemized_amount: int | None = Field(
        default=None, description="Total itemized deductions amount"
    )
    salt_returns: int | None = Field(
        default=None,
        description="Number of returns with the taxes-paid (SALT) deduction",
    )
    salt_amount: int | None = Field(
        default=None, description="Taxes-paid (SALT) deduction amount"
    )
    itemizing_pct: float | None = Field(
        default=None,
        description="Percent of returns that itemized rather than took the "
        "standard deduction (0-100)",
    )
    tax_year: int = Field(description="SOI tax year of the data")


class FilingStatus(BaseModel):
    """Filing-status and filing-characteristic counts for a ZIP."""

    zipcode: str = Field(description="5-digit ZIP code")
    state: str | None = Field(default=None, description="2-letter USPS state code")
    total_returns: int | None = Field(
        default=None, description="Total number of returns"
    )
    single_returns: int | None = Field(default=None, description="Single returns")
    married_joint_returns: int | None = Field(
        default=None, description="Married-filing-jointly returns"
    )
    head_of_household_returns: int | None = Field(
        default=None, description="Head-of-household returns"
    )
    elderly_returns: int | None = Field(
        default=None, description="Returns with the taxpayer aged 65 or older"
    )
    electronically_filed_returns: int | None = Field(
        default=None, description="Electronically filed returns"
    )
    electronically_filed_pct: float | None = Field(
        default=None, description="Percent of returns filed electronically (0-100)"
    )
    tax_year: int = Field(description="SOI tax year of the data")


class ZipMetric(BaseModel):
    """One ZIP's value for a single metric, used in a ranked comparison."""

    zipcode: str = Field(description="5-digit ZIP code")
    value: float | None = Field(
        default=None,
        description="The metric's value for this ZIP, or null if the ZIP has no "
        "SOI data in the store",
    )


class Comparison(BaseModel):
    """Several ZIPs ranked by one metric, highest value first."""

    metric: str = Field(description="The compared metric's name")
    tax_year: int = Field(description="SOI tax year of the data")
    results: list[ZipMetric] = Field(
        description="One entry per requested ZIP, sorted by value descending; "
        "ZIPs with no data are listed last"
    )


class StateTotals(BaseModel):
    """State-level totals from the SOI 00000 rollup row (all dollar amounts USD)."""

    state: str = Field(description="2-letter USPS state code")
    returns: int | None = Field(default=None, description="Total returns in the state")
    individuals: int | None = Field(
        default=None, description="Total individuals (filers plus dependents)"
    )
    adjusted_gross_income: int | None = Field(
        default=None, description="Total adjusted gross income (AGI)"
    )
    avg_agi_per_return: int | None = Field(
        default=None, description="AGI divided by the number of returns"
    )
    income_tax: int | None = Field(default=None, description="Total income tax amount")
    total_tax_liability: int | None = Field(
        default=None, description="Total tax liability amount"
    )
    brackets: list[AgiBracket] = Field(
        description="The state's income distribution across the six AGI brackets"
    )
    tax_year: int = Field(description="SOI tax year of the data")


class SoiFieldValue(BaseModel):
    """The value of a single SOI field for a ZIP, summed across AGI brackets."""

    zipcode: str = Field(description="5-digit ZIP code")
    state: str | None = Field(default=None, description="2-letter USPS state code")
    field: str = Field(description="SOI field code, e.g. 'A00100' or 'N1'")
    label: str = Field(description="Human-readable description of the field")
    unit: str = Field(description="'USD' for amount fields, 'count' for return counts")
    value: int | None = Field(
        default=None,
        description="The field's value for this ZIP (summed over brackets)",
    )
    tax_year: int = Field(description="SOI tax year of the data")
