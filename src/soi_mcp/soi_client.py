"""Async client for the IRS SOI individual-income ZIP-code data files.

The data is a set of static, public-domain CSVs on ``www.irs.gov/pub/irs-soi``
(no API key, no rate-limit terms). One file per tax year, named with a two-digit
year prefix, e.g. ``22zpallagi.csv`` for Tax Year 2022. The SOI ZIP release lags
real time by ~2–3 years, so the latest available year is probed, not assumed.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from pathlib import Path

PUB_BASE = "https://www.irs.gov/pub/irs-soi"
LANDING_URL = (
    "https://www.irs.gov/statistics/"
    "soi-tax-stats-individual-income-tax-statistics-zip-code-data-soi"
)


class SoiError(RuntimeError):
    """An IRS SOI request failed in a way we can't recover from."""


def csv_url(year: int) -> str:
    """The all-states, AGI-stub CSV URL for a tax year (e.g. 2022 → …/22zpallagi.csv)."""
    return f"{PUB_BASE}/{year % 100:02d}zpallagi.csv"


class SoiClient:
    """Thin async wrapper over the IRS SOI static file host."""

    def __init__(self, *, max_retries: int = 3) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, read=600.0),
            follow_redirects=True,
            headers={"User-Agent": "soi-mcp (https://github.com/mcpwright/soi-mcp)"},
        )
        self._max_retries = max_retries

    async def __aenter__(self) -> SoiClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def year_available(self, year: int) -> bool:
        """True if the SOI ZIP CSV for ``year`` exists on the IRS host."""
        try:
            resp = await self._client.head(csv_url(year))
        except httpx.HTTPError:
            return False
        return resp.status_code == 200

    async def latest_year(self) -> int:
        """Probe for the most recent published SOI ZIP tax year.

        SOI ZIP data lags ~2–3 years, so we start two years back and walk
        downward until a file responds 200.
        """
        now = datetime.now(UTC).year
        for year in range(now - 2, now - 9, -1):
            if await self.year_available(year):
                return year
        raise SoiError(
            "Could not find a published SOI ZIP-code file for any recent year."
        )

    async def download_csv(self, year: int, dest: Path) -> int:
        """Stream the SOI ZIP CSV for ``year`` to ``dest``; return bytes written.

        Streams to disk (the file is ~200 MB) and retries transient errors
        (429 / 5xx / network) with exponential backoff. Raises ``SoiError`` if
        the year's file is missing or the download keeps failing.
        """
        url = csv_url(year)
        dest.parent.mkdir(parents=True, exist_ok=True)
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                written = 0
                async with self._client.stream("GET", url) as resp:
                    if resp.status_code == 404:
                        raise SoiError(
                            f"No SOI ZIP-code file for tax year {year} at {url}."
                        )
                    if resp.status_code == 429 or resp.status_code >= 500:
                        last_exc = SoiError(
                            f"IRS returned {resp.status_code} for {url}"
                        )
                        await asyncio.sleep(2**attempt)
                        continue
                    resp.raise_for_status()
                    with dest.open("wb") as fh:
                        async for chunk in resp.aiter_bytes(chunk_size=1 << 20):
                            fh.write(chunk)
                            written += len(chunk)
                return written
            except SoiError:
                raise
            except httpx.HTTPError as exc:  # network/timeout — retry
                last_exc = exc
                await asyncio.sleep(2**attempt)
                continue
        raise SoiError(
            f"SOI download failed after {self._max_retries} attempts: {url}"
        ) from last_exc
