"""Sensors: network and SD card."""

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
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TapoConfigEntry
from .entity import TapoEntity
from .model import TapoData, size_in_bytes

PARALLEL_UPDATES = 0


def _rssi(data: TapoData) -> int | None:
    value = data.connection.get("rssiValue", data.basic_info.get("rssi"))
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _disk(field: str) -> Callable[[TapoData], Any]:
    def value(data: TapoData) -> Any:
        return data.disks[0].get(field) if data.disks else None

    return value


def _disk_size(field: str) -> Callable[[TapoData], Any]:
    return lambda data: size_in_bytes(_disk(field)(data))


@dataclass(frozen=True, kw_only=True)
class TapoSensorDescription(SensorEntityDescription):
    value_fn: Callable[[TapoData], Any]


SENSORS: tuple[TapoSensorDescription, ...] = (
    TapoSensorDescription(
        key="signal_strength",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_rssi,
    ),
    TapoSensorDescription(
        key="ssid",
        translation_key="ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.connection.get("ssid") or data.basic_info.get("ssid"),
    ),
    TapoSensorDescription(
        key="link_type",
        translation_key="link_type",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.connection.get("link_type"),
    ),
    TapoSensorDescription(
        key="ip_address",
        translation_key="ip_address",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("getDeviceIpAddress", "network", "wan", "ipaddr"),
    ),
    TapoSensorDescription(
        key="sd_card_status",
        translation_key="sd_card_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_disk("status"),
    ),
    TapoSensorDescription(
        key="sd_card_free_space",
        translation_key="sd_card_free_space",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_disk_size("free_space"),
    ),
    TapoSensorDescription(
        key="sd_card_total_space",
        translation_key="sd_card_total_space",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_disk_size("total_space"),
    ),
)


class TapoSensor(TapoEntity, SensorEntity):
    entity_description: TapoSensorDescription

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.data)


async def async_setup_entry(
    hass: HomeAssistant, entry: TapoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(TapoSensor(coordinator, d) for d in SENSORS if d.value_fn(coordinator.data) is not None)
