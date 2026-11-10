"""Buttons: reboot, pan/tilt moves and calibration, SD card format."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pytapo import Tapo

from . import TapoConfigEntry
from .coordinator import TapoCoordinator
from .entity import TapoEntity
from .model import TapoData

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class TapoButtonDescription(ButtonEntityDescription):
    # Called with the client and the move step in degrees.
    press: Callable[[Tapo, float], Any]
    supported_fn: Callable[[TapoData], bool]


def _move(pan: int, tilt: int) -> Callable[[Tapo, float], Any]:
    return lambda tapo, angle: tapo.moveMotor(round(pan * angle), round(tilt * angle))


BUTTONS: tuple[TapoButtonDescription, ...] = (
    TapoButtonDescription(
        key="reboot",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        press=lambda tapo, _angle: tapo.reboot(),
        supported_fn=lambda data: True,
    ),
    TapoButtonDescription(
        key="move_up",
        translation_key="move_up",
        press=_move(0, 1),
        supported_fn=lambda data: data.ptz,
    ),
    TapoButtonDescription(
        key="move_down",
        translation_key="move_down",
        press=_move(0, -1),
        supported_fn=lambda data: data.ptz,
    ),
    TapoButtonDescription(
        key="move_left",
        translation_key="move_left",
        press=_move(-1, 0),
        supported_fn=lambda data: data.ptz,
    ),
    TapoButtonDescription(
        key="move_right",
        translation_key="move_right",
        press=_move(1, 0),
        supported_fn=lambda data: data.ptz,
    ),
    TapoButtonDescription(
        key="calibrate",
        translation_key="calibrate",
        entity_category=EntityCategory.CONFIG,
        press=lambda tapo, _angle: tapo.calibrateMotor(),
        supported_fn=lambda data: data.ptz,
    ),
    TapoButtonDescription(
        key="format_sd_card",
        translation_key="format_sd_card",
        entity_category=EntityCategory.CONFIG,
        # Erases every recording: hidden until enabled on purpose.
        entity_registry_enabled_default=False,
        press=lambda tapo, _angle: tapo.format(),
        supported_fn=lambda data: bool(data.disks),
    ),
)


class TapoButton(TapoEntity, ButtonEntity):
    entity_description: TapoButtonDescription

    def __init__(self, coordinator: TapoCoordinator, description: TapoButtonDescription) -> None:
        super().__init__(coordinator, description)

    async def async_press(self) -> None:
        press, angle = self.entity_description.press, self.coordinator.move_angle
        # Not retried: a move or a reboot whose answer is lost has usually been done.
        await self.coordinator.async_command(lambda tapo: press(tapo, angle), retry=False)


async def async_setup_entry(
    hass: HomeAssistant, entry: TapoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(TapoButton(coordinator, d) for d in BUTTONS if d.supported_fn(coordinator.data))
