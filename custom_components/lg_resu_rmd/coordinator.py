"""Coordinator: one /getbmsdata request per pack per poll."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, RETRY_DELAY
from .rmd import RmdClient, RmdError, RmdInfo

_LOGGER = logging.getLogger(__name__)

type RmdConfigEntry = ConfigEntry[RmdCoordinator]


class RmdCoordinator(DataUpdateCoordinator[dict[str, str]]):
    """Polls one RMD; data is the /getbmsdata page as {name: value}."""

    config_entry: RmdConfigEntry
    info: RmdInfo

    def __init__(
        self, hass: HomeAssistant, entry: RmdConfigEntry, client: RmdClient
    ) -> None:
        interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {client.host}",
            update_interval=timedelta(seconds=interval),
        )
        self.client = client

    async def _async_setup(self) -> None:
        try:
            self.info = await self.client.async_get_info()
        except RmdError as err:
            raise UpdateFailed(f"Could not read pack info: {err}") from err

    async def _async_update_data(self) -> dict[str, str]:
        # Timeouts, garbled replies and pages cut short all happen over the
        # RMD's Wi-Fi; one retry, then the entities go unavailable.
        try:
            return await self.client.async_get_bms_data()
        except RmdError as err:
            _LOGGER.debug(
                "%s failed, retrying in %s s: %s", self.name, RETRY_DELAY, err
            )
        await asyncio.sleep(RETRY_DELAY)
        try:
            return await self.client.async_get_bms_data()
        except RmdError as err:
            raise UpdateFailed(str(err)) from err
