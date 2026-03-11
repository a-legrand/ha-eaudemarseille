"""Data update coordinator for Eau de Marseille Métropole."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    get_last_statistics,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ApiError, AuthenticationError, EauMarseilleApiClient, WaterConsumptionData
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, GRANULARITY_DAILY, GRANULARITY_MONTHLY

_LOGGER = logging.getLogger(__name__)

STAT_ID_CONSUMPTION = "eau_marseille:consommation"
STAT_ID_INDEX = "eau_marseille:index_compteur"


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
        self._history_imported = False

    async def _async_update_data(self) -> WaterConsumptionData:
        """Fetch data and import statistics."""
        try:
            data = await self.client.get_data()
        except AuthenticationError as err:
            raise UpdateFailed(f"Authentication error: {err}") from err
        except ApiError as err:
            raise UpdateFailed(f"API error: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error: {err}") from err

        # Import historical statistics into HA recorder
        await self._import_statistics()

        return data

    async def _import_statistics(self) -> None:
        """Import consumption history into HA long-term statistics.

        On first run: imports up to 3 years of monthly data + last year daily.
        On subsequent runs: only imports data since last known statistic.
        """
        try:
            await self._do_import_statistics()
        except Exception:
            _LOGGER.exception("Error importing statistics")

    async def _do_import_statistics(self) -> None:
        """Actual statistics import logic."""
        contract_id = self.client._contract_id
        if not contract_id:
            return

        now = datetime.now()

        # Check what we already have in HA statistics
        last_stats = await self.hass.async_add_executor_job(
            get_last_statistics, self.hass, 1, STAT_ID_CONSUMPTION, True, {"sum"}
        )

        last_sum = 0.0
        fetch_from = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(days=365 * 3)

        if last_stats and STAT_ID_CONSUMPTION in last_stats:
            stats = last_stats[STAT_ID_CONSUMPTION]
            if stats:
                last_stat = stats[0]
                last_sum = last_stat.get("sum", 0.0) or 0.0
                # Fetch from the day after the last statistic
                last_ts = last_stat.get("start")
                if last_ts:
                    if isinstance(last_ts, (int, float)):
                        fetch_from = datetime.fromtimestamp(last_ts) + timedelta(days=1)
                    elif isinstance(last_ts, datetime):
                        fetch_from = last_ts + timedelta(days=1)
                _LOGGER.debug("Last statistic sum=%.1f, fetching from %s", last_sum, fetch_from)

                # If we already have recent data, just do incremental
                if (now - fetch_from).days < 2:
                    self._history_imported = True
                    return

        fetch_from = fetch_from.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59, microsecond=0)

        # Fetch daily data from the API
        _LOGGER.info(
            "Importing water statistics from %s to %s",
            fetch_from.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
        )

        days_to_fetch = (end - fetch_from).days
        all_entries = []

        if days_to_fetch > 365:
            # For older data, use monthly granularity
            monthly_end = now.replace(month=1, day=1) - timedelta(days=1)
            monthly_data = await self.client.get_consumption(
                fetch_from, monthly_end, GRANULARITY_MONTHLY
            )
            if monthly_data:
                all_entries.extend(monthly_data)
                _LOGGER.debug("Fetched %d monthly entries", len(monthly_data))

            # Then daily for the last year
            daily_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            daily_data = await self.client.get_consumption(
                daily_start, end, GRANULARITY_DAILY
            )
            if daily_data:
                all_entries.extend(daily_data)
                _LOGGER.debug("Fetched %d daily entries", len(daily_data))
        else:
            # All daily
            daily_data = await self.client.get_consumption(
                fetch_from, end, GRANULARITY_DAILY
            )
            if daily_data:
                all_entries = daily_data
                _LOGGER.debug("Fetched %d daily entries", len(daily_data))

        if not all_entries:
            _LOGGER.debug("No new consumption data to import")
            self._history_imported = True
            return

        # Sort by date ascending (API returns most recent first)
        all_entries.sort(key=lambda e: e.get("dateReleve", ""))

        # Build statistics: consumption (sum of liters) and index
        consumption_stats: list[StatisticData] = []
        running_sum = last_sum

        for entry in all_entries:
            date_str = entry.get("dateReleve", "")
            if not date_str:
                continue
            try:
                dt = datetime.fromisoformat(date_str)
            except ValueError:
                continue

            volume_liters = entry.get("volumeConsoEnLitres", 0) or 0
            running_sum += volume_liters

            consumption_stats.append(
                StatisticData(
                    start=dt,
                    state=volume_liters,
                    sum=running_sum,
                )
            )

        if not consumption_stats:
            self._history_imported = True
            return

        # Import consumption statistics
        consumption_metadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name="Eau de Marseille - Consommation",
            source=DOMAIN,
            statistic_id=STAT_ID_CONSUMPTION,
            unit_of_measurement=UnitOfVolume.LITERS,
        )

        async_import_statistics(self.hass, consumption_metadata, consumption_stats)

        _LOGGER.info(
            "Imported %d water consumption statistics (sum=%.0f L)",
            len(consumption_stats),
            running_sum,
        )
        self._history_imported = True
