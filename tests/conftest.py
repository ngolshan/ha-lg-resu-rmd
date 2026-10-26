"""Fixtures for the Home Assistant tests: a mocked RMD serving saved pages."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.lg_resu_rmd.const import DOMAIN
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

FIXTURES = Path(__file__).parent / "fixtures"

HOST = "192.168.1.91"
HOST_2 = "192.168.1.92"
SERIAL = "2201010001"
NAME = "LG RESU16H 1"
PAGES = ("getbmsinfo", "getversion", "getbmsdata", "showapinfo")


def page(pack: str, name: str) -> bytes:
    """A page saved from a live RMD (pack91 or pack92); /showapinfo is JSON."""
    suffix = "json" if name == "showapinfo" else "html"
    return (FIXTURES / f"{pack}-{name}.{suffix}").read_bytes()


def mock_pack(aioclient_mock: AiohttpClientMocker, host: str, pack: str) -> None:
    for name in PAGES:
        aioclient_mock.get(f"http://{host}/{name}", content=page(pack, name))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def mock_rmd(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Pack 1's RMD at HOST, serving the saved pages."""
    mock_pack(aioclient_mock, HOST, "pack91")
    return aioclient_mock


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title=NAME, unique_id=SERIAL, data={CONF_HOST: HOST}
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, mock_rmd: AiohttpClientMocker, config_entry: MockConfigEntry
) -> MockConfigEntry:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
