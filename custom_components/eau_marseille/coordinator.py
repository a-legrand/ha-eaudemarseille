"""Data update coordinator for Eau de Marseille Métropole."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
)
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
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
            data = await self.client.get_data()
        except AuthenticationError as err:
            raise UpdateFailed(f"Authentication error: {err}") from err
        except ApiError as err:
            raise UpdateFailed(f"API error: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error: {err}") from err

        # Push historical data as external statistics (m³)
        await self._import_statistics(data)
        return data

    async def _import_statistics(self, data: WaterConsumptionData) -> None:
        """Import daily history as external statistics in m³."""
        if not data.daily_history:
            return

        statistic_id = f"{DOMAIN}:eau_m3"

        metadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name="Consommation eau m³",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_of_measurement="m³",
        )

        # Build statistics from daily history
        # daily_history entries have: date, liters, m3, index
        statistics: list[StatisticData] = []
        cumulative_sum = 0.0

        # Sort by date ascending
        sorted_history = sorted(data.daily_history, key=lambda e: e["date"])

        for entry in sorted_history:
            # Parse date and set to top of hour, UTC
            try:
                dt = datetime.fromisoformat(entry["date"][:10])
                dt_utc = dt.replace(hour=0, minute=0, second=0, tzinfo=UTC)
            except (ValueError, KeyError):
                continue

            m3_value = entry.get("m3", 0) or 0
            cumulative_sum += m3_value

            statistics.append(
                StatisticData(
                    start=dt_utc,
                    sum=cumulative_sum,
                    state=m3_value,
                )
            )

        if statistics:
            async_add_external_statistics(self.hass, metadata, statistics)
            _LOGGER.debug(
                "Imported %d external statistics entries for %s",
                len(statistics),
                statistic_id,
            )
