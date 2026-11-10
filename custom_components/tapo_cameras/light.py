"""Lights: the spotlight (white lamp) and the floodlight of the cameras that have one."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.light import ColorMode, LightEntity, LightEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pytapo import Tapo

from . import TapoConfigEntry
from .entity import TapoDescribedEntity, TapoDescriptionMixin
from .model import TapoData, is_on

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class TapoLightDescription(LightEntityDescription, TapoDescriptionMixin):
    # Called with the client and the wanted state, knowing the current one.
    switch: Callable[[Tapo, bool], Any]
    to_raw: Callable[[bool], Any]


LIGHTS = (
    TapoLightDescription(
        key="spotlight",
        translation_key="spotlight",
        method="getWhitelampStatus",
        path=("status",),
        # The camera only offers "toggle": called only when the state differs.
        switch=lambda tapo, _on: tapo.reverseWhitelampStatus(),
        to_raw=lambda on: "1" if on else "0",
    ),
    TapoLightDescription(
        key="floodlight",
        translation_key="floodlight",
        method="getFloodlightStatus",
        path=("status",),
        switch=lambda tapo, on: tapo.manualFloodlightOp(on),
        to_raw=lambda on: 1 if on else 0,
    ),
)


class TapoLight(TapoDescribedEntity, LightEntity):
    entity_description: TapoLightDescription
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = frozenset({ColorMode.ONOFF})

    @property
    def is_on(self) -> bool | None:
        return is_on(self.entity_description.raw_value(self.data))

    async def _async_set(self, on: bool) -> None:
        if self.is_on == on:
            return
        description = self.entity_description

        def apply(data: TapoData) -> None:
            data.set(description.method, description.path, description.to_raw(on))

        await self.coordinator.async_command(lambda tapo: description.switch(tapo, on), apply=apply, retry=False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)


async def async_setup_entry(
    hass: HomeAssistant, entry: TapoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(TapoLight(coordinator, d) for d in LIGHTS if d.supported(coordinator.data))
