"""Sensor platform for Eau de Marseille Métropole."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EauMarseilleConfigEntry
from .api import WaterConsumptionData
from .const import DOMAIN
from .coordinator import EauMarseilleCoordinator


@dataclass(frozen=True, kw_only=True)
class EauMarseilleSensorEntityDescription(SensorEntityDescription):
    """Describe an Eau de Marseille sensor."""

    value_fn: Callable[[WaterConsumptionData], Any]


SENSORS: tuple[EauMarseilleSensorEntityDescription, ...] = (
    EauMarseilleSensorEntityDescription(
        key="daily_consumption",
        name="Consommation journalière",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:water",
        value_fn=lambda d: d.daily_consumption_liters,
    ),
    EauMarseilleSensorEntityDescription(
        key="monthly_consumption",
        name="Consommation mensuelle",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:water",
        value_fn=lambda d: d.monthly_consumption_liters,
    ),
    EauMarseilleSensorEntityDescription(
        key="yearly_consumption",
        name="Consommation annuelle",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:water",
        value_fn=lambda d: d.yearly_consumption_liters,
    ),
    EauMarseilleSensorEntityDescription(
        key="meter_index",
        name="Index compteur",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:gauge",
        value_fn=lambda d: d.meter_index_liters,
    ),
    EauMarseilleSensorEntityDescription(
        key="meter_index_m3",
        name="Index compteur m³",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:gauge",
        suggested_display_precision=3,
        value_fn=lambda d: d.meter_index_m3,
    ),
    EauMarseilleSensorEntityDescription(
        key="last_reading_index",
        name="Dernier relevé officiel",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:gauge",
        value_fn=lambda d: d.last_reading_index_m3,
    ),
    EauMarseilleSensorEntityDescription(
        key="last_reading_date",
        name="Date dernier relevé",
        icon="mdi:calendar",
        value_fn=lambda d: d.last_reading_date,
    ),
    EauMarseilleSensorEntityDescription(
        key="last_reading_anomaly",
        name="État compteur",
        icon="mdi:check-circle",
        value_fn=lambda d: d.last_reading_anomaly,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EauMarseilleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        EauMarseilleSensor(coordinator, description, entry)
        for description in SENSORS
    )


class EauMarseilleSensor(
    CoordinatorEntity[EauMarseilleCoordinator], SensorEntity
):
    """Eau de Marseille sensor entity."""

    entity_description: EauMarseilleSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EauMarseilleCoordinator,
        description: EauMarseilleSensorEntityDescription,
        entry: EauMarseilleConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Eau de Marseille Métropole",
            "manufacturer": "SEMM",
            "model": "Compteur d'eau",
        }

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if (
            self.entity_description.key == "daily_consumption"
            and self.coordinator.data
            and self.coordinator.data.daily_history
        ):
            return {"history": self.coordinator.data.daily_history[-7:]}
        return None
