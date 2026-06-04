"""IRS SOI ZIP-code field definitions and CSV parsing.

The SOI individual-income ZIP file (``<yy>zpallagi.csv``) has ~150 columns named
in ``N####`` / ``A####`` pairs — ``N`` = number of returns reporting an item,
``A`` = the aggregate dollar amount **in thousands**. We curate the subset the
tools expose (income, tax, credits, deductions, filing status), store each under
its SOI code (lower-cased), and normalize amounts to whole dollars at load time
so everything downstream is in USD.

One row of the source file is a (state, ZIP, AGI bracket) cell; we keep all six
AGI brackets per ZIP so the distribution is preserved. ``zipcode`` "00000" is the
state-total rollup and "99999" is the catch-all "other" bucket (ZIPs with <100
returns and nonresidential ZIPs) — both are kept and surfaced deliberately.
"""

from __future__ import annotations

import csv
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# AGI bracket codes (the file's ``agi_stub``) → human label and [lo, hi) bounds.
# Fixed by the IRS: six brackets, codes 1–6.
AGI_STUBS: dict[int, tuple[str, int, int | None]] = {
    1: ("$1 under $25,000", 1, 25_000),
    2: ("$25,000 under $50,000", 25_000, 50_000),
    3: ("$50,000 under $75,000", 50_000, 75_000),
    4: ("$75,000 under $100,000", 75_000, 100_000),
    5: ("$100,000 under $200,000", 100_000, 200_000),
    6: ("$200,000 or more", 200_000, None),
}

# Reserved ``zipcode`` values that aren't real ZIPs.
STATE_TOTAL_ZIP = "00000"  # per-state rollup
OTHER_ZIP = "99999"  # ZIPs with <100 returns + nonresidential, folded together

# (SOI code, human label, kind) — kind in {"count", "amount"}.
# "amount" values are dollars-in-thousands in the source and are multiplied by
# 1000 at load, so stored amounts are whole USD. Counts are returns, rounded by
# the IRS to the nearest 10.
FIELDS: list[tuple[str, str, str]] = [
    # --- counts / filing characteristics ---
    ("N1", "Number of returns", "count"),
    ("N2", "Number of individuals (filers and dependents)", "count"),
    ("MARS1", "Number of single returns", "count"),
    ("MARS2", "Number of married-filing-jointly returns", "count"),
    ("MARS4", "Number of head-of-household returns", "count"),
    ("ELF", "Number of electronically filed returns", "count"),
    ("ELDERLY", "Number of elderly returns (taxpayer age 65 or older)", "count"),
    (
        "VRTCRIND",
        "Number of returns with a digital-asset (virtual currency) indicator",
        "count",
    ),
    # --- income (amount in USD + count of returns reporting it) ---
    ("A00100", "Adjusted gross income (AGI)", "amount"),
    ("N02650", "Number of returns with total income", "count"),
    ("A02650", "Total income amount", "amount"),
    ("N00200", "Number of returns with salaries and wages", "count"),
    ("A00200", "Salaries and wages amount", "amount"),
    ("N00300", "Number of returns with taxable interest", "count"),
    ("A00300", "Taxable interest amount", "amount"),
    ("N00600", "Number of returns with ordinary dividends", "count"),
    ("A00600", "Ordinary dividends amount", "amount"),
    (
        "N00900",
        "Number of returns with business or professional net income (less loss)",
        "count",
    ),
    ("A00900", "Business or professional net income (less loss) amount", "amount"),
    ("N01000", "Number of returns with net capital gain (less loss)", "count"),
    ("A01000", "Net capital gain (less loss) amount", "amount"),
    # --- deductions ---
    ("N04450", "Number of returns claiming the standard deduction", "count"),
    ("A04450", "Standard deduction amount", "amount"),
    ("N04470", "Number of returns with itemized deductions", "count"),
    ("A04470", "Total itemized deductions amount", "amount"),
    ("N18300", "Number of returns with the taxes-paid deduction (SALT)", "count"),
    ("A18300", "Taxes-paid deduction (SALT) amount", "amount"),
    # --- tax ---
    ("N04800", "Number of returns with taxable income", "count"),
    ("A04800", "Taxable income amount", "amount"),
    ("N05800", "Number of returns with income tax before credits", "count"),
    ("A05800", "Income tax before credits amount", "amount"),
    ("N06500", "Number of returns with income tax", "count"),
    ("A06500", "Income tax amount", "amount"),
    ("N10300", "Number of returns with total tax liability", "count"),
    ("A10300", "Total tax liability amount", "amount"),
    ("N10600", "Number of returns with total tax payments", "count"),
    ("A10600", "Total tax payments amount", "amount"),
    # --- credits ---
    ("N59660", "Number of returns with the Earned Income Tax Credit (EITC)", "count"),
    ("A59660", "Earned Income Tax Credit (EITC) amount", "amount"),
    ("N59661", "Number of EITC returns with no qualifying children", "count"),
    ("A59661", "EITC amount, returns with no qualifying children", "amount"),
    ("N59662", "Number of EITC returns with one qualifying child", "count"),
    ("A59662", "EITC amount, returns with one qualifying child", "amount"),
    ("N59663", "Number of EITC returns with two qualifying children", "count"),
    ("A59663", "EITC amount, returns with two qualifying children", "amount"),
    (
        "N59664",
        "Number of EITC returns with three or more qualifying children",
        "count",
    ),
    ("A59664", "EITC amount, returns with three or more qualifying children", "amount"),
    (
        "N11070",
        "Number of returns with the additional (refundable) child tax credit",
        "count",
    ),
    ("A11070", "Additional (refundable) child tax credit amount", "amount"),
]

# Stored column name per SOI code (SQLite-friendly, lower-cased).
COLUMN = {code: code.lower() for code, _label, _kind in FIELDS}
KIND = {code: kind for code, _label, kind in FIELDS}
LABEL = {code: label for code, label, _kind in FIELDS}
DATA_COLUMNS: list[str] = [COLUMN[code] for code, _label, _kind in FIELDS]

# The thousands→USD multiplier applied to "amount" fields at load.
_AMOUNT_SCALE = 1000

# Geography / dimension columns from the source file (case-insensitive match).
_GEO = {"STATEFIPS": "statefips", "STATE": "state", "zipcode": "zipcode"}


def available_fields() -> list[str]:
    """SOI field codes available for direct lookup (the loaded subset)."""
    return [code for code, _label, _kind in FIELDS]


def resolve_field(field: str) -> str:
    """Resolve a SOI field code (case-insensitive) to its canonical code.

    Raises ``ValueError`` listing the options if the field isn't in the loaded
    subset (the store holds the curated columns, not all ~150 source columns).
    """
    key = field.strip().upper()
    if key in COLUMN:
        return key
    raise ValueError(
        f"Unknown SOI field {field!r}. Available fields: "
        f"{', '.join(available_fields())}."
    )


def _sanitize(raw: str, kind: str) -> int | None:
    """Coerce a raw SOI cell to a stored int (USD for amounts), or None."""
    v = raw.strip()
    if not v:
        return None
    try:
        num = float(v)
    except ValueError:
        return None
    # Amounts are reported in thousands of dollars; counts are plain.
    # Negative aggregates are legitimate (net capital loss, business loss) — keep them.
    if kind == "amount":
        return int(round(num * _AMOUNT_SCALE))
    return int(round(num))


def parse_csv(path: Path) -> Iterator[dict[str, object]]:
    """Stream parsed records from a downloaded ``<yy>zpallagi.csv`` file.

    Yields one dict per source row: ``statefips``, ``state``, ``zipcode``,
    ``agi_stub`` plus the curated data columns (amounts already in USD). Rows
    whose ``agi_stub`` is not 1–6 are skipped. ``zipcode`` is kept as a string so
    leading zeros (and the reserved 00000 / 99999 rows) survive.
    """
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None:
            return
        idx = {name.strip().upper(): i for i, name in enumerate(header)}
        geo_i = {col: idx.get(src.upper()) for src, col in _GEO.items()}
        stub_i = idx.get("AGI_STUB")
        field_i = {code: idx.get(code) for code, _label, _kind in FIELDS}
        for row in reader:
            if stub_i is None or stub_i >= len(row):
                continue
            try:
                stub = int(float(row[stub_i]))
            except ValueError:
                continue
            if stub not in AGI_STUBS:
                continue
            rec: dict[str, object] = {"agi_stub": stub}
            for col, i in geo_i.items():
                rec[col] = row[i].strip() if i is not None and i < len(row) else None
            for code, i in field_i.items():
                rec[COLUMN[code]] = (
                    _sanitize(row[i], KIND[code])
                    if i is not None and i < len(row)
                    else None
                )
            yield rec
