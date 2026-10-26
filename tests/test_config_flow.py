"""Config, reconfigure and options flows."""

from __future__ import annotations

import aiohttp
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.lg_resu_rmd.const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import HOST, HOST_2, NAME, SERIAL, mock_pack


async def _start(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result


async def test_user_flow_creates_entry(
    hass: HomeAssistant, mock_rmd: AiohttpClientMocker
) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: f" {HOST} ", CONF_NAME: NAME}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    assert result["data"] == {CONF_HOST: HOST}
    assert result["result"].unique_id == SERIAL


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"http://{HOST}/getbmsinfo", exc=aiohttp.ClientError("down"))
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_NAME: NAME}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_timeout(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"http://{HOST}/getbmsinfo", exc=TimeoutError())
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_NAME: NAME}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_not_an_rmd(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"http://{HOST}/getbmsinfo", text="Moved to /login.html")
    aioclient_mock.get(f"http://{HOST}/getversion", text="4.2.1")
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_NAME: NAME}
    )
    assert result["errors"] == {"base": "invalid_response"}


async def test_user_flow_recovers_after_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"http://{HOST}/getbmsinfo", exc=TimeoutError())
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_NAME: NAME}
    )
    assert result["errors"] == {"base": "cannot_connect"}
    aioclient_mock.clear_requests()
    mock_pack(aioclient_mock, HOST, "pack91")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_NAME: NAME}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_same_pack_new_ip_aborts_and_updates(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, title=NAME, unique_id=SERIAL, data={CONF_HOST: "10.0.0.9"}
    )
    entry.add_to_hass(hass)
    mock_pack(aioclient_mock, HOST, "pack91")
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_NAME: NAME}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == HOST


async def test_reconfigure_changes_host(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_rmd: AiohttpClientMocker
) -> None:
    mock_pack(mock_rmd, "192.168.1.191", "pack91")
    result = await setup_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.191"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert setup_entry.data[CONF_HOST] == "192.168.1.191"


async def test_reconfigure_rejects_other_pack(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_rmd: AiohttpClientMocker
) -> None:
    mock_pack(mock_rmd, HOST_2, "pack92")
    result = await setup_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST_2}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_pack"
    assert setup_entry.data[CONF_HOST] == HOST


async def test_options_flow_sets_interval(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    coordinator = setup_entry.runtime_data
    assert coordinator.update_interval.total_seconds() == DEFAULT_SCAN_INTERVAL

    result = await hass.config_entries.options.async_init(setup_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 120.0}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_entry.options == {CONF_SCAN_INTERVAL: 120}
    # The entry reloads, so the new coordinator polls at the new interval.
    assert setup_entry.runtime_data is not coordinator
    assert setup_entry.runtime_data.update_interval.total_seconds() == 120
