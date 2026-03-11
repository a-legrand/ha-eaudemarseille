"""Data update coordinator for Eau de Marseille Métropole."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    clear_statistics,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ApiError, AuthenticationError, EauMarseilleApiClient, WaterConsumptionData
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, GRANULARITY_DAILY, GRANULARITY_MONTHLY

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
        self._stats_imported = False

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

        if not self._stats_imported:
            await self._import_statistics()

        return data

    async def _import_statistics(self) -> None:
        """Import historical consumption into HA long-term statistics."""
        contract_id = self.client._contract_id
        if not contract_id:
            return

        statistic_id = f"{DOMAIN}:consommation_{contract_id}"

        # One-time purge of old corrupted metadata (mean_type was stored as string "none")
        # This flag file prevents re-purging on every restart
        import os
        purge_flag = self.hass.config.path(f".eau_marseille_purged_{contract_id}")
        if not os.path.exists(purge_flag):
            try:
                instance = get_instance(self.hass)
                await instance.async_add_executor_job(
                    clear_statistics, instance, [statistic_id]
                )
                _LOGGER.info("Cleared old statistics for %s (one-time fix)", statistic_id)
                with open(purge_flag, "w") as f:
                    f.write("done")
            except Exception:
                _LOGGER.debug("No old statistics to clear for %s", statistic_id)

        now = datetime.now()
        end = now.replace(hour=23, minute=59, second=59, microsecond=0)

        # Fetch monthly data for the past 3 years
        three_years_ago = (now - timedelta(days=365 * 3)).replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )

        all_entries = []

        try:
            monthly = await self.client.get_consumption(
                three_years_ago, end, GRANULARITY_MONTHLY
            )
            if monthly:
                all_entries.extend(monthly)
                _LOGGER.debug("Fetched %d monthly entries", len(monthly))

            # Also fetch daily for last 30 days (more granular)
            d30 = (now - timedelta(days=30)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            daily = await self.client.get_consumption(d30, end, GRANULARITY_DAILY)
            if daily:
                # Remove monthly entries that overlap with daily
                daily_months = {e["dateReleve"][:7] for e in daily}
                all_entries = [
                    e for e in all_entries
                    if e["dateReleve"][:7] not in daily_months
                ]
                all_entries.extend(daily)
                _LOGGER.debug("Fetched %d daily entries", len(daily))

        except Exception:
            _LOGGER.exception("Error fetching historical data")
            return

        if not all_entries:
            _LOGGER.warning("No historical data to import")
            self._stats_imported = True
            return

        # Sort ascending by date
        all_entries.sort(key=lambda e: e.get("dateReleve", ""))

        # Build statistics with running sum
        statistics = []
        running_sum = 0.0

        for entry in all_entries:
            date_str = entry.get("dateReleve", "")
            if not date_str:
                continue
            try:
                dt = datetime.fromisoformat(date_str)
            except ValueError:
                continue

            volume = entry.get("volumeConsoEnLitres", 0) or 0
            running_sum += volume

            # HA requires: timezone-aware, at the top of the hour, in UTC
            dt_utc = dt.astimezone(timezone.utc).replace(
                minute=0, second=0, microsecond=0
            )

            statistics.append({
                "start": dt_utc,
                "state": volume,
                "sum": running_sum,
            })

        if not statistics:
            self._stats_imported = True
            return

        metadata = {
            "has_mean": False,
            "has_sum": True,
            "mean_type": 0,
            "unit_class": "volume",
            "name": "Eau de Marseille - Consommation",
            "source": DOMAIN,
            "statistic_id": statistic_id,
            "unit_of_measurement": "L",
        }

        try:
            async_add_external_statistics(self.hass, metadata, statistics)
            _LOGGER.info(
                "Imported %d water statistics (total %.0f L)",
                len(statistics), running_sum,
            )
            self._stats_imported = True
        except Exception:
            _LOGGER.exception("Failed to import statistics")
