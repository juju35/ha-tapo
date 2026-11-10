"""Switches: camera settings that are on or off."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pytapo import Tapo

from . import TapoConfigEntry
from .coordinator import TapoCoordinator
from .entity import TapoDescribedEntity, TapoDescriptionMixin
from .model import TapoData, is_on, on_off

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class TapoSwitchDescription(SwitchEntityDescription, TapoDescriptionMixin):
    setter: Callable[[Tapo, bool], Any]
    # Raw value → on/off, and on/off → raw value written into the state after a change.
    to_bool: Callable[[Any], bool | None] = field(default=is_on)
    to_raw: Callable[[bool], Any] = field(default=on_off)
    # Actions that must not be retried on a lost answer.
    retry: bool = True


SWITCHES: tuple[TapoSwitchDescription, ...] = (
    TapoSwitchDescription(
        key="privacy_mode",
        translation_key="privacy_mode",
        method="getLensMaskConfig",
        path=("lens_mask", "lens_mask_info", "enabled"),
        setter=lambda tapo, on: tapo.setPrivacyMode(on),
    ),
    TapoSwitchDescription(
        key="indicator_led",
        translation_key="indicator_led",
        entity_category=EntityCategory.CONFIG,
        method="getLedStatus",
        path=("led", "config", "enabled"),
        setter=lambda tapo, on: tapo.setLEDEnabled(on),
    ),
    TapoSwitchDescription(
        key="notifications",
        translation_key="notifications",
        entity_category=EntityCategory.CONFIG,
        method="getMsgPushConfig",
        path=("msg_push", "chn1_msg_push_info", "notification_enabled"),
        setter=lambda tapo, on: tapo.setNotificationsEnabled(notificationsEnabled=on),
    ),
    TapoSwitchDescription(
        key="rich_notifications",
        translation_key="rich_notifications",
        entity_category=EntityCategory.CONFIG,
        method="getMsgPushConfig",
        path=("msg_push", "chn1_msg_push_info", "rich_notification_enabled"),
        setter=lambda tapo, on: tapo.setNotificationsEnabled(richNotificationsEnabled=on),
    ),
    TapoSwitchDescription(
        key="record_audio",
        translation_key="record_audio",
        entity_category=EntityCategory.CONFIG,
        method="getAudioConfig",
        path=("audio_config", "record_audio", "enabled"),
        setter=lambda tapo, on: tapo.setRecordAudio(on),
    ),
    TapoSwitchDescription(
        key="microphone_mute",
        translation_key="microphone_mute",
        entity_category=EntityCategory.CONFIG,
        method="getAudioConfig",
        path=("audio_config", "microphone", "mute"),
        setter=lambda tapo, on: tapo.setMicrophone(mute=on),
    ),
    TapoSwitchDescription(
        key="noise_cancelling",
        translation_key="noise_cancelling",
        entity_category=EntityCategory.CONFIG,
        method="getAudioConfig",
        path=("audio_config", "microphone", "noise_cancelling"),
        setter=lambda tapo, on: tapo.setMicrophone(noise_cancelling=on),
    ),
    TapoSwitchDescription(
        key="lens_distortion_correction",
        translation_key="lens_distortion_correction",
        entity_category=EntityCategory.CONFIG,
        method="getLdc",
        path=("image", "switch", "ldc"),
        setter=lambda tapo, on: tapo.setLensDistortionCorrection(on),
    ),
    TapoSwitchDescription(
        key="flip",
        translation_key="flip",
        entity_category=EntityCategory.CONFIG,
        method="getRotationStatus",
        path=("image", "switch", "flip_type"),
        setter=lambda tapo, on: tapo.setImageFlipVertical(on),
        to_bool=lambda value: None if value is None else value != "off",
        to_raw=lambda on: "center" if on else "off",
    ),
    TapoSwitchDescription(
        key="auto_track",
        translation_key="auto_track",
        method="getTargetTrackConfig",
        path=("target_track", "target_track_info", "enabled"),
        setter=lambda tapo, on: tapo.setAutoTrackTarget(on),
    ),
    TapoSwitchDescription(
        key="privacy_zones",
        translation_key="privacy_zones",
        entity_category=EntityCategory.CONFIG,
        method="getCoverConfig",
        path=("cover", "cover", "enabled"),
        setter=lambda tapo, on: tapo.setCoverConfig(on),
    ),
    TapoSwitchDescription(
        key="record_to_sd_card",
        translation_key="record_to_sd_card",
        method="getRecordPlan",
        path=("record_plan", "chn1_channel", "enabled"),
        setter=lambda tapo, on: tapo.setRecordPlan(on),
    ),
    TapoSwitchDescription(
        key="circular_recording",
        translation_key="circular_recording",
        entity_category=EntityCategory.CONFIG,
        method="getCircularRecordingConfig",
        path=("harddisk_manage", "harddisk", "loop"),
        setter=lambda tapo, on: tapo.setCircularRecordingConfig(on),
    ),
    TapoSwitchDescription(
        key="line_crossing_detection",
        translation_key="line_crossing_detection",
        entity_category=EntityCategory.CONFIG,
        method="getLinecrossingDetectionConfig",
        path=("linecrossing_detection", "detection", "enabled"),
        setter=lambda tapo, on: tapo.setLinecrossingDetection(on),
    ),
    TapoSwitchDescription(
        key="automatic_reboot",
        translation_key="automatic_reboot",
        entity_category=EntityCategory.CONFIG,
        method="getReboot",
        path=("timing_reboot", "reboot", "enabled"),
        setter=lambda tapo, on: tapo.setReboot(enabled=on),
    ),
    TapoSwitchDescription(
        key="automatic_firmware_upgrade",
        translation_key="automatic_firmware_upgrade",
        entity_category=EntityCategory.CONFIG,
        method="getFirmwareAutoUpgradeConfig",
        path=("auto_upgrade", "common", "enabled"),
        setter=lambda tapo, on: tapo.setFirmwareAutoUpgradeConfig(enabled=on),
    ),
    TapoSwitchDescription(
        key="diagnose_mode",
        translation_key="diagnose_mode",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        method="getDiagnoseMode",
        path=("system", "sys", "diagnose_mode"),
        setter=lambda tapo, on: tapo.setDiagnoseMode(on),
    ),
)


def smart_track_description(kind: str) -> TapoSwitchDescription:
    """Tracking of one kind of target (people, pet, vehicle…), as the camera names it."""
    return TapoSwitchDescription(
        key=f"smart_track_{kind}",
        translation_key="smart_track",
        translation_placeholders={"type": kind.replace("_enabled", "").replace("_", " ")},
        entity_category=EntityCategory.CONFIG,
        method="getSmartTrackConfig",
        path=("smart_track", "smart_track_info", kind),
        setter=lambda tapo, on: tapo.setSmartTrackConfig(kind, on),
    )


def alarm_trigger_description(name: str) -> TapoSwitchDescription:
    """Whether one kind of detection triggers the camera's alarm."""
    return TapoSwitchDescription(
        key=f"alarm_trigger_{name}",
        translation_key="alarm_trigger",
        translation_placeholders={"type": name.replace("_detection", "").replace("_", " ")},
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        method="getAlertEventType",
        supported_fn=lambda data: name in data.alarm_event_types,
        setter=lambda tapo, on: tapo.setAlertEventType(name, on),
    )


class TapoSwitch(TapoDescribedEntity, SwitchEntity):
    entity_description: TapoSwitchDescription

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.is_on is not None

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.to_bool(self.entity_description.raw_value(self.data))

    async def _async_set(self, on: bool) -> None:
        description = self.entity_description

        def apply(data: TapoData) -> None:
            data.set(description.method, description.path, description.to_raw(on))

        await self.coordinator.async_command(lambda tapo: description.setter(tapo, on), apply=apply)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)


class TapoAlarmTriggerSwitch(TapoSwitch):
    """One entry of the list of detections that trigger the alarm."""

    def __init__(self, coordinator: TapoCoordinator, name: str) -> None:
        super().__init__(coordinator, alarm_trigger_description(name))
        self._name = name

    @property
    def is_on(self) -> bool | None:
        return self.data.alarm_event_types.get(self._name)

    async def _async_set(self, on: bool) -> None:
        name = self._name
        await self.coordinator.async_command(
            lambda tapo: tapo.setAlertEventType(name, on),
            apply=lambda data: data.set_alarm_event_type(name, on),
        )


async def async_setup_entry(
    hass: HomeAssistant, entry: TapoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    data = coordinator.data
    entities: list[SwitchEntity] = [TapoSwitch(coordinator, d) for d in SWITCHES if d.supported(data)]
    entities += [TapoSwitch(coordinator, smart_track_description(kind)) for kind in data.smart_track]
    entities += [TapoAlarmTriggerSwitch(coordinator, name) for name in data.alarm_event_types]
    async_add_entities(entities)
