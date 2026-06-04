"""USPS state code resolution for state-level SOI lookups.

The SOI file identifies states by their 2-letter USPS code (plus DC). This maps
full names to codes so ``get_state_totals`` accepts either ``"CA"`` or
``"California"``.
"""

from __future__ import annotations

# 2-letter USPS code → full state name (50 states + DC, matching SOI coverage).
STATE_NAMES: dict[str, str] = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}

_NAME_TO_CODE = {name.lower(): code for code, name in STATE_NAMES.items()}


def resolve_state(state: str) -> str:
    """Resolve a USPS code or full state name (case-insensitive) to a 2-letter code.

    Raises ``ValueError`` if it isn't a recognized state.
    """
    key = state.strip()
    if key.upper() in STATE_NAMES:
        return key.upper()
    if key.lower() in _NAME_TO_CODE:
        return _NAME_TO_CODE[key.lower()]
    raise ValueError(
        f"Unknown state {state!r}. Pass a 2-letter USPS code (e.g. 'CA') or a "
        "full state name (e.g. 'California')."
    )
