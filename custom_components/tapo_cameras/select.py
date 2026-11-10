"""Selects: detection sensitivities, image modes and pan/tilt presets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from pytapo import Tapo

from . import TapoConfigEntry
from .const import STREAM_PATHS
from .entity import TapoDescribedEntity, TapoDescriptionMixin, TapoEntity
from .model import SENSITIVITY_OPTIONS, SENSITIVITY_PERCENT, TapoData, is_on, on_off, sensitivity_level

PARALLEL_UPDATES = 1

NIGHT_VISION_MODES = ["inf_night_vision", "wtl_night_vision", "md_night_vision", "dbl_night_vision"]


@dataclass(frozen=True, kw_only=True)
class TapoDetectionDescription(SelectEntityDescription, TapoDescriptionMixin):
    """A detection: off, or on with a sensitivity. `path` points at its settings (enabled, sensitivity)."""

    setter: Callable[[Tapo, bool, str | None], Any]
    sensitivity_key: str = "sensitivity"
    # How the camera stores the sensitivity: a percentage, or a label (low / medium / high).
    labels: bool = False

    def option(self, data: TapoData) -> str | None:
        settings = self.raw_value(data)
        if not isinstance(settings, dict) or is_on(settings.get("enabled")) is None:
            return None
        if not is_on(settings.get("enabled")):
            return "off"
        return sensitivity_level(settings.get(self.sensitivity_key, settings.get("sensitivity"))) or "normal"

    def apply(self, data: TapoData, option: str) -> None:
        data.set(self.method, (*self.path, "enabled"), on_off(option != "off"))
        if option != "off":
            raw = {"normal": "medium"}.get(option, option) if self.labels else str(SENSITIVITY_PERCENT[option])
            data.set(self.method, (*self.path, self.sensitivity_key), raw)


DETECTIONS: tuple[TapoDetectionDescription, ...] = (
    TapoDetectionDescription(
        key="motion_detection",
        translation_key="motion_detection",
        method="getDetectionConfig",
        path=("motion_detection", "motion_det"),
        sensitivity_key="digital_sensitivity",
        setter=lambda tapo, on, level: tapo.setMotionDetection(on, level or False),
    ),
    TapoDetectionDescription(
        key="person_detection",
        translation_key="person_detection",
        method="getPersonDetectionConfig",
        path=("people_detection", "detection"),
        setter=lambda tapo, on, level: tapo.setPersonDetection(on, level or False),
    ),
    TapoDetectionDescription(
        key="vehicle_detection",
        translation_key="vehicle_detection",
        method="getVehicleDetectionConfig",
        path=("vehicle_detection", "detection"),
        setter=lambda tapo, on, level: tapo.setVehicleDetection(on, level or False),
    ),
    TapoDetectionDescription(
        key="pet_detection",
        translation_key="pet_detection",
        method="getPetDetectionConfig",
        path=("pet_detection", "detection"),
        setter=lambda tapo, on, level: tapo.setPetDetection(on, level or False),
    ),
    TapoDetectionDescription(
        key="package_detection",
        translation_key="package_detection",
        method="getPackageDetectionConfig",
        path=("package_detection", "detection"),
        setter=lambda tapo, on, level: tapo.setPackageDetection(
            on, str(SENSITIVITY_PERCENT[level]) if level else False
        ),
    ),
    TapoDetectionDescription(
        key="baby_cry_detection",
        translation_key="baby_cry_detection",
        method="getBCDConfig",
        path=("sound_detection", "bcd"),
        labels=True,
        setter=lambda tapo, on, level: tapo.setBabyCryDetection(on, level or False),
    ),
    TapoDetectionDescription(
        key="bark_detection",
        translation_key="bark_detection",
        method="getBarkDetectionConfig",
        path=("bark_detection", "detection"),
        setter=lambda tapo, on, level: tapo.setBarkDetection(on, level or False),
    ),
    TapoDetectionDescription(
        key="meow_detection",
        translation_key="meow_detection",
        method="getMeowDetectionConfig",
        path=("meow_detection", "detection"),
        setter=lambda tapo, on, level: tapo.setMeowDetection(on, level or False),
    ),
    TapoDetectionDescription(
        key="glass_break_detection",
        translation_key="glass_break_detection",
        method="getGlassDetectionConfig",
        path=("glass_detection", "detection"),
        setter=lambda tapo, on, level: tapo.setGlassBreakDetection(on, level or False),
    ),
    TapoDetectionDescription(
        key="tamper_detection",
        translation_key="tamper_detection",
        method="getTamperDetectionConfig",
        path=("tamper_detection", "tamper_det"),
        labels=True,
        setter=lambda tapo, on, level: tapo.setTamperDetection(on, level or False),
    ),
)


@dataclass(frozen=True, kw_only=True)
class TapoModeDescription(SelectEntityDescription, TapoDescriptionMixin):
    """A setting with a fixed list of values, written as is."""

    setter: Callable[[Tapo, str], Any]
    options_fn: Callable[[TapoData], list[str]] | None = None


MODES: tuple[TapoModeDescription, ...] = (
    TapoModeDescription(
        key="night_vision",
        translation_key="night_vision",
        entity_category=EntityCategory.CONFIG,
        method="getNightVisionModeConfig",
        path=("image", "switch", "night_vision_mode"),
        options_fn=lambda data: list(
            data.get("getNightVisionCapability", "image_capability", "supplement_lamp", "night_vision_mode_range")
            or NIGHT_VISION_MODES[:3]
        ),
        setter=lambda tapo, mode: tapo.setNightVisionModeConfig(mode),
    ),
    TapoModeDescription(
        key="day_night_mode",
        translation_key="day_night_mode",
        entity_category=EntityCategory.CONFIG,
        method="getLightFrequencyInfo",
        path=("image", "common", "inf_type"),
        options=["auto", "on", "off"],
        setter=lambda tapo, mode: tapo.setDayNightModeConfig(mode),
    ),
    TapoModeDescription(
        key="light_frequency",
        translation_key="light_frequency",
        entity_category=EntityCategory.CONFIG,
        method="getLightFrequencyInfo",
        path=("image", "common", "light_freq_mode"),
        options=["auto", "50", "60"],
        setter=lambda tapo, mode: tapo.setLightFrequencyMode(mode),
    ),
)

PRESET = SelectEntityDescription(key="preset", translation_key="preset")
STREAM_QUALITY = SelectEntityDescription(
    key="stream_quality",
    translation_key="stream_quality",
    entity_category=EntityCategory.CONFIG,
    options=list(STREAM_PATHS),
)


class TapoDetectionSelect(TapoDescribedEntity, SelectEntity):
    entity_description: TapoDetectionDescription
    _attr_options = SENSITIVITY_OPTIONS
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.current_option is not None

    @property
    def current_option(self) -> str | None:
        return self.entity_description.option(self.data)

    async def async_select_option(self, option: str) -> None:
        description = self.entity_description
        on = option != "off"
        await self.coordinator.async_command(
            lambda tapo: description.setter(tapo, on, option if on else None),
            apply=lambda data: description.apply(data, option),
        )


class TapoModeSelect(TapoDescribedEntity, SelectEntity):
    entity_description: TapoModeDescription

    @property
    def options(self) -> list[str]:
        description = self.entity_description
        options = description.options_fn(self.data) if description.options_fn else list(description.options or [])
        current = self.current_option
        return options if current is None or current in options else [*options, current]

    @property
    def current_option(self) -> str | None:
        value = self.entity_description.raw_value(self.data)
        return None if value is None else str(value)

    async def async_select_option(self, option: str) -> None:
        description = self.entity_description
        await self.coordinator.async_command(
            lambda tapo: description.setter(tapo, option),
            apply=lambda data: data.set(description.method, description.path, option),
        )


class TapoPresetSelect(TapoEntity, SelectEntity):
    """Moves to a saved position. The camera has no 'current preset': the state stays unknown."""

    _attr_current_option = None

    @property
    def available(self) -> bool:
        return super().available and bool(self.data.presets)

    @property
    def options(self) -> list[str]:
        return list(self.data.presets.values())

    async def async_select_option(self, option: str) -> None:
        preset_id = next((pid for pid, name in self.data.presets.items() if name == option), option)
        await self.coordinator.async_command(lambda tapo: tapo.setPreset(preset_id), retry=False)


class TapoStreamQualitySelect(TapoEntity, SelectEntity, RestoreEntity):
    """HD or SD stream for the camera entity. Kept by Home Assistant, the camera has no such setting."""

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None and last.state in STREAM_PATHS:
            self._set(last.state)

    @property
    def available(self) -> bool:
        return True

    @property
    def current_option(self) -> str:
        return self.coordinator.stream_quality

    async def async_select_option(self, option: str) -> None:
        self._set(option)

    def _set(self, option: str) -> None:
        if option != self.coordinator.stream_quality:
            self.coordinator.stream_quality = option
            # The camera entity switches its stream; this entity writes its state too.
            self.coordinator.async_update_listeners()


async def async_setup_entry(
    hass: HomeAssistant, entry: TapoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    data = coordinator.data
    entities: list[SelectEntity] = [
        TapoDetectionSelect(coordinator, d) for d in DETECTIONS if isinstance(d.raw_value(data), dict)
    ]
    entities += [TapoModeSelect(coordinator, d) for d in MODES if d.supported(data)]
    entities.append(TapoStreamQualitySelect(coordinator, STREAM_QUALITY))
    if data.has("getPresetConfig", "preset", "preset"):
        entities.append(TapoPresetSelect(coordinator, PRESET))
    async_add_entities(entities)
