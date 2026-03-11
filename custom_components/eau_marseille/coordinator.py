"""Data update coordinator for Eau de Marseille Métropole."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ApiError, AuthenticationError, EauMarseilleApiClient, WaterConsumptionData
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class EauMarseilleCoordinator(DataUpdateCoordinator[WaterConsumptionData]):
    """Coordinator to fetch data from Eau de Marseille API."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        client: EauMarseilleApiClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client

    async def _async_update_data(self) -> WaterConsumptionData:
        """Fetch data from API."""
        try:
            return await self.client.get_data()
        except AuthenticationError as err:
            raise UpdateFailed(f"Authentication error: {err}") from err
        except ApiError as err:
            raise UpdateFailed(f"API error: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error: {err}") from err
