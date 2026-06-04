"""Tests for the async IRS SOI client (HTTP mocked with respx)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from soi_mcp.soi_client import PUB_BASE, SoiClient, SoiError, csv_url


def test_csv_url_uses_two_digit_year() -> None:
    assert csv_url(2022) == f"{PUB_BASE}/22zpallagi.csv"
    assert csv_url(2008) == f"{PUB_BASE}/08zpallagi.csv"


@respx.mock
async def test_year_available_true_false() -> None:
    respx.head(csv_url(2022)).mock(return_value=httpx.Response(200))
    respx.head(csv_url(2099)).mock(return_value=httpx.Response(404))
    async with SoiClient() as client:
        assert await client.year_available(2022) is True
        assert await client.year_available(2099) is False


@respx.mock
async def test_latest_year_probes_downward() -> None:
    target = datetime.now(UTC).year - 2
    respx.head(csv_url(target)).mock(return_value=httpx.Response(200))
    async with SoiClient() as client:
        assert await client.latest_year() == target


@respx.mock
async def test_download_csv_streams_to_file(tmp_path: Path) -> None:
    body = b"STATEFIPS,STATE,zipcode,agi_stub,N1\n06,CA,90210,1,300.0000\n"
    respx.get(csv_url(2022)).mock(return_value=httpx.Response(200, content=body))
    dest = tmp_path / "out.csv"
    async with SoiClient() as client:
        written = await client.download_csv(2022, dest)
    assert written == len(body)
    assert dest.read_bytes() == body


@respx.mock
async def test_download_csv_404_raises(tmp_path: Path) -> None:
    respx.get(csv_url(1999)).mock(return_value=httpx.Response(404))
    async with SoiClient() as client:
        with pytest.raises(SoiError, match="No SOI ZIP-code file for tax year 1999"):
            await client.download_csv(1999, tmp_path / "x.csv")


@respx.mock
async def test_download_csv_retries_then_succeeds(tmp_path: Path) -> None:
    body = b"STATEFIPS,STATE,zipcode,agi_stub,N1\n"
    route = respx.get(csv_url(2022))
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(200, content=body),
    ]
    dest = tmp_path / "retry.csv"
    async with SoiClient(max_retries=3) as client:
        written = await client.download_csv(2022, dest)
    assert written == len(body)
    assert route.call_count == 2
