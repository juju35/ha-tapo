"""Binary sensors: detections (motion, person, vehicle…) and the state of the event subscription.

Every detection the camera supports gets its sensor at setup, before any event: automations can
use it at once. A detection the camera reports that this integration does not know yet gets a
sensor too, created when it is first seen.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TapoConfigEntry
from .coordinator import TapoCoordinator
from .entity import TapoEntity
from .events import OnvifEvents

PARALLEL_UPDATES = 0

# Detection key → (device class, request whose answer tells the camera supports it; None: always).
DETECTIONS: dict[str, tuple[BinarySensorDeviceClass | None, str | None]] = {
    "motion": (BinarySensorDeviceClass.MOTION, None),
    "person": (BinarySensorDeviceClass.OCCUPANCY, "getPersonDetectionConfig"),
    "vehicle": (BinarySensorDeviceClass.MOTION, "getVehicleDetectionConfig"),
    "pet": (BinarySensorDeviceClass.MOTION, "getPetDetectionConfig"),
    "line_crossing": (BinarySensorDeviceClass.MOTION, "getLinecrossingDetectionConfig"),
    "tamper": (BinarySensorDeviceClass.TAMPER, "getTamperDetectionConfig"),
    "baby_cry": (BinarySensorDeviceClass.SOUND, "getBCDConfig"),
    "bark": (BinarySensorDeviceClass.SOUND, "getBarkDetectionConfig"),
    "meow": (BinarySensorDeviceClass.SOUND, "getMeowDetectionConfig"),
    "glass_break": (BinarySensorDeviceClass.SOUND, "getGlassDetectionConfig"),
    "package": (None, "getPackageDetectionConfig"),
    "area_intrusion": (BinarySensorDeviceClass.MOTION, None),
}
# Created only once reported (no request tells whether the camera supports them).
ON_FIRST_EVENT = {"area_intrusion"}

SUBSCRIPTION = BinarySensorEntityDescription(
    key="event_subscription",
    translation_key="event_subscription",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
)


def detection_description(key: str) -> BinarySensorEntityDescription:
    device_class = DETECTIONS.get(key, (None, None))[0]
    if key in DETECTIONS:
        return BinarySensorEntityDescription(key=key, translation_key=key, device_class=device_class)
    return BinarySensorEntityDescription(
        key=key,
        translation_key="detection",
        translation_placeholders={"type": key.replace("_", " ")},
        device_class=BinarySensorDeviceClass.MOTION,
    )


class TapoEventEntity(TapoEntity):
    """Entity whose state comes from the event subscription."""

    def __init__(self, coordinator: TapoCoordinator, events: OnvifEvents, description: BinarySensorEntityDescription):
        super().__init__(coordinator, description)
        self._events = events

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._events.async_add_listener(self.async_write_ha_state))


class TapoDetectionSensor(TapoEventEntity, BinarySensorEntity):
    @property
    def available(self) -> bool:
        # Independent of polling: events keep working while the control API is busy.
        return self._events.connected

    @property
    def is_on(self) -> bool:
        return self._events.states.get(self.entity_description.key, False)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        changed = self._events.changed_at.get(self.entity_description.key)
        return {"last_change": changed.isoformat()} if changed else None


class TapoSubscriptionSensor(TapoEventEntity, BinarySensorEntity):
    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self._events.connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"last_error": self._events.last_error, "messages": self._events.messages}


async def async_setup_entry(
    hass: HomeAssistant, entry: TapoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    events = coordinator.events
    if events is None:
        return
    data = coordinator.data
    created: set[str] = set()

    def supported(key: str, method: str | None) -> bool:
        return key not in ON_FIRST_EVENT and (method is None or data.get(method) is not None)

    keys = [key for key, (_, method) in DETECTIONS.items() if supported(key, method)]
    created.update(keys)
    entities: list[BinarySensorEntity] = [TapoSubscriptionSensor(coordinator, events, SUBSCRIPTION)]
    entities += [TapoDetectionSensor(coordinator, events, detection_description(key)) for key in keys]
    async_add_entities(entities)

    @callback
    def add_new_detections() -> None:
        if new := [key for key in events.states if key not in created]:
            created.update(new)
            async_add_entities(TapoDetectionSensor(coordinator, events, detection_description(key)) for key in new)

    entry.async_on_unload(events.async_add_listener(add_new_detections))
