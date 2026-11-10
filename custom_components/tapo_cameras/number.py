"""Numbers: volumes, sensitivity, spotlight intensity, and the step of the move buttons."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode, RestoreNumber
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pytapo import Tapo

from . import TapoConfigEntry
from .const import DEFAULT_MOVE_ANGLE
from .entity import TapoDescribedEntity, TapoDescriptionMixin, TapoEntity
from .model import TapoData

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class TapoNumberDescription(NumberEntityDescription, TapoDescriptionMixin):
    setter: Callable[[Tapo, int], Any]
    max_fn: Callable[[TapoData], float | None] | None = None


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


NUMBERS: tuple[TapoNumberDescription, ...] = (
    TapoNumberDescription(
        key="speaker_volume",
        translation_key="speaker_volume",
        entity_category=EntityCategory.CONFIG,
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        method="getAudioConfig",
        path=("audio_config", "speaker", "volume"),
        setter=lambda tapo, value: tapo.setSpeakerVolume(value),
    ),
    TapoNumberDescription(
        key="microphone_volume",
        translation_key="microphone_volume",
        entity_category=EntityCategory.CONFIG,
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        method="getAudioConfig",
        path=("audio_config", "microphone", "volume"),
        setter=lambda tapo, value: tapo.setMicrophone(volume=value),
    ),
    TapoNumberDescription(
        key="motion_sensitivity",
        translation_key="motion_sensitivity",
        entity_category=EntityCategory.CONFIG,
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=1,
        native_max_value=100,
        native_step=1,
        method="getDetectionConfig",
        path=("motion_detection", "motion_det", "digital_sensitivity"),
        setter=lambda tapo, value: tapo.setMotionDetection(None, value),
    ),
    TapoNumberDescription(
        key="spotlight_intensity",
        translation_key="spotlight_intensity",
        entity_category=EntityCategory.CONFIG,
        native_min_value=1,
        native_max_value=5,
        native_step=1,
        method="getWhitelampConfig",
        path=("image", "switch", "wtl_intensity_level"),
        max_fn=lambda data: _int(
            data.get("getWhitelampCapability", "image_capability", "white_lamp", "wtl_intensity_range")
        ),
        setter=lambda tapo, value: tapo.setWhitelampConfig(intensityLevel=value),
    ),
)

MOVE_ANGLE = NumberEntityDescription(
    key="move_angle",
    translation_key="move_angle",
    entity_category=EntityCategory.CONFIG,
    native_unit_of_measurement="°",
    native_min_value=1,
    native_max_value=180,
    native_step=1,
    mode=NumberMode.BOX,
)


class TapoNumber(TapoDescribedEntity, NumberEntity):
    entity_description: TapoNumberDescription

    @property
    def native_max_value(self) -> float:
        description = self.entity_description
        if description.max_fn is not None and (maximum := description.max_fn(self.data)) and maximum > 0:
            return maximum
        return description.native_max_value or 100

    @property
    def native_value(self) -> float | None:
        return _int(self.entity_description.raw_value(self.data))

    async def async_set_native_value(self, value: float) -> None:
        description = self.entity_description
        level = round(value)
        # Stored as the camera stores it: a string.
        await self.coordinator.async_command(
            lambda tapo: description.setter(tapo, level),
            apply=lambda data: data.set(description.method, description.path, str(level)),
        )


class TapoMoveAngle(TapoEntity, RestoreNumber):
    """Step of the move buttons, in degrees. Kept by Home Assistant, the camera has no such setting."""

    _attr_native_value = DEFAULT_MOVE_ANGLE

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) is not None and last.native_value is not None:
            self._attr_native_value = last.native_value
        self.coordinator.move_angle = self._attr_native_value

    @property
    def available(self) -> bool:
        return True

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.coordinator.move_angle = value
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant, entry: TapoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    data = coordinator.data
    entities: list[NumberEntity] = [TapoNumber(coordinator, d) for d in NUMBERS if d.supported(data)]
    if data.ptz:
        entities.append(TapoMoveAngle(coordinator, MOVE_ANGLE))
    async_add_entities(entities)
