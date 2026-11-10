"""Siren: the camera's alarm (sound and light), started and stopped by hand."""

from __future__ import annotations

from typing import Any

from homeassistant.components.siren import SirenEntity, SirenEntityDescription, SirenEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TapoConfigEntry
from .entity import TapoEntity
from .model import TapoData, is_on

PARALLEL_UPDATES = 1

SIREN = SirenEntityDescription(key="siren", translation_key="siren")

# Requests answered by cameras that have an alarm (older and newer firmwares).
ALARM_METHODS = ("getLastAlarmInfo", "getAlarmConfig", "getSirenConfig", "getSirenStatus")


def _status(data: TapoData) -> bool | None:
    for index in (0, 1):
        if (status := is_on(data.get("getSirenStatus", "status", index=index))) is not None:
            return status
    return None


class TapoSiren(TapoEntity, SirenEntity):
    _attr_supported_features = SirenEntityFeature.TURN_ON | SirenEntityFeature.TURN_OFF

    @property
    def is_on(self) -> bool | None:
        return _status(self.data)

    @property
    def assumed_state(self) -> bool:
        return _status(self.data) is None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(lambda tapo: tapo.startManualAlarm(), apply=_set(True), retry=False)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(lambda tapo: tapo.stopManualAlarm(), apply=_set(False), retry=False)


def _set(on: bool):
    def apply(data: TapoData) -> None:
        for index in (0, 1):
            data.set("getSirenStatus", ("status",), "on" if on else "off", index=index)

    return apply


async def async_setup_entry(
    hass: HomeAssistant, entry: TapoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    if any(coordinator.data.get(method) is not None for method in ALARM_METHODS):
        async_add_entities([TapoSiren(coordinator, SIREN)])
