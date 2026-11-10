"""Detection events: parsing, subscription loss and recovery, sensors created before any event."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.tapo_cameras.const import CONF_MOTION_TIMEOUT, CONF_ONVIF_EVENTS, DOMAIN, EVENT_TAPO
from custom_components.tapo_cameras.events import OnvifEvents, parse_message

from .conftest import FakeCamera


def message(topic: str, name: str, value: str) -> SimpleNamespace:
    item = SimpleNamespace(Name=name, Value=value)
    payload = SimpleNamespace(Data=SimpleNamespace(SimpleItem=[item]), Source=SimpleNamespace(SimpleItem=[]))
    return SimpleNamespace(Topic=SimpleNamespace(_value_1=topic), Message=SimpleNamespace(_value_1=payload))


@pytest.mark.parametrize(
    ("topic", "name", "value", "expected"),
    [
        ("tns1:RuleEngine/CellMotionDetector/Motion", "IsMotion", "true", [("motion", True)]),
        ("tns1:RuleEngine/CellMotionDetector/People", "IsPeople", "false", [("person", False)]),
        ("tns1:RuleEngine/TPSmartEventDetector/TPSmartEvent", "IsVehicle", "true", [("vehicle", True)]),
        ("tns1:RuleEngine/TPSmartEventDetector/TPSmartEvent", "IsPet", "true", [("pet", True)]),
        ("tns1:RuleEngine/CellMotionDetector/LineCross", "IsLineCross", "true", [("line_crossing", True)]),
        ("tns1:RuleEngine/TamperDetector/Tamper", "IsTamper", "true", [("tamper", True)]),
        # A detection not known yet keeps its own key.
        ("tns1:RuleEngine/TPSmartEventDetector/TPSmartEvent", "IsFireAlarm", "true", [("fire_alarm", True)]),
        # A topic-named detection whose item is not "Is…".
        ("tns1:RuleEngine/CellMotionDetector/Motion", "State", "1", [("motion", True)]),
        # Not a detection.
        ("tns1:Device/HardwareFailure/StorageFailure", "Failed", "nope", []),
    ],
)
def test_parse_message(topic: str, name: str, value: str, expected: list) -> None:
    assert parse_message(message(topic, name, value)) == expected


class FakeSubscription:
    """A pull point: queued batches of messages, then waits like a camera with nothing to say."""

    def __init__(self) -> None:
        self.batches: asyncio.Queue = asyncio.Queue()
        self.lost = None
        service = MagicMock()
        service.PullMessages = AsyncMock(side_effect=self._pull)
        self.manager = MagicMock()
        self.manager.get_service.return_value = service
        self.manager.shutdown = AsyncMock()
        self.camera = MagicMock()
        self.camera.close = AsyncMock()

    async def _pull(self, params):
        batch = await self.batches.get()
        if isinstance(batch, Exception):
            raise batch
        return SimpleNamespace(NotificationMessage=batch)


@pytest.fixture
def subscription():
    fake = FakeSubscription()

    async def subscribe(self):
        self._lost.clear()
        return fake.camera, fake.manager

    with patch.object(OnvifEvents, "_subscribe", subscribe):
        yield fake


@pytest.fixture
async def with_events(hass: HomeAssistant, camera: FakeCamera, entry: MockConfigEntry, subscription) -> MockConfigEntry:
    hass.config_entries.async_update_entry(entry, options={CONF_ONVIF_EVENTS: True, CONF_MOTION_TIMEOUT: 60})
    # Time jumps in these tests must not look like a dead connection (tested on its own below).
    with patch("custom_components.tapo_cameras.events.ONVIF_PULL_GRACE", 3600):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry
        await hass.config_entries.async_unload(entry.entry_id)


def _state(hass: HomeAssistant, key: str):
    entity_id = er.async_get(hass).async_get_entity_id("binary_sensor", DOMAIN, f"aa:bb:cc:dd:ee:ff_{key}")
    assert entity_id, key
    return hass.states.get(entity_id)


async def test_sensors_exist_before_any_event(hass: HomeAssistant, with_events: MockConfigEntry) -> None:
    for key in ("motion", "person", "vehicle", "pet", "tamper", "baby_cry", "line_crossing"):
        assert _state(hass, key).state == "off", key
    # Not supported by the fixture camera.
    assert er.async_get(hass).async_get_entity_id("binary_sensor", DOMAIN, "aa:bb:cc:dd:ee:ff_bark") is None
    assert _state(hass, "event_subscription").state == "on"


async def test_events_drive_the_sensors(hass: HomeAssistant, with_events: MockConfigEntry, subscription) -> None:
    fired = []
    hass.bus.async_listen(EVENT_TAPO, fired.append)
    await subscription.batches.put([message("tns1:RuleEngine/CellMotionDetector/Motion", "IsMotion", "true")])
    await hass.async_block_till_done()
    assert _state(hass, "motion").state == "on"
    assert fired[0].data["type"] == "motion"
    device = dr.async_entries_for_config_entry(dr.async_get(hass), with_events.entry_id)[0]
    assert fired[0].data["device_id"] == device.id

    await subscription.batches.put([message("tns1:RuleEngine/CellMotionDetector/Motion", "IsMotion", "false")])
    await hass.async_block_till_done()
    assert _state(hass, "motion").state == "off"


async def test_unknown_detection_gets_a_sensor(hass: HomeAssistant, with_events: MockConfigEntry, subscription) -> None:
    await subscription.batches.put(
        [message("tns1:RuleEngine/TPSmartEventDetector/TPSmartEvent", "IsFireAlarm", "true")]
    )
    await hass.async_block_till_done()
    assert _state(hass, "fire_alarm").state == "on"


async def test_safety_timeout(hass: HomeAssistant, with_events: MockConfigEntry, subscription) -> None:
    await subscription.batches.put([message("tns1:RuleEngine/PeopleDetector/People", "IsPeople", "true")])
    await hass.async_block_till_done()
    assert _state(hass, "person").state == "on"
    # The camera never sends the end of the event.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert _state(hass, "person").state == "off"


async def test_subscription_loss_and_recovery(hass: HomeAssistant, with_events: MockConfigEntry, subscription) -> None:
    await subscription.batches.put([message("tns1:RuleEngine/CellMotionDetector/Motion", "IsMotion", "true")])
    await hass.async_block_till_done()
    with patch.object(OnvifEvents, "_backoff", AsyncMock()) as backoff:
        await subscription.batches.put(TimeoutError("camera rebooting"))
        await hass.async_block_till_done()
        backoff.assert_awaited_once_with(5)
    # Back at once (the backoff is mocked): the sensors are available again, the old detection cleared.
    assert _state(hass, "event_subscription").state == "on"
    assert _state(hass, "motion").state == "off"
    subscription.manager.shutdown.assert_awaited()


async def test_dead_connection_detected(hass: HomeAssistant, with_events: MockConfigEntry, subscription) -> None:
    """A pull that never answers (connection dead without a reset) ends in a new subscription."""
    events = with_events.runtime_data.events
    events.async_stop()
    with (
        patch("custom_components.tapo_cameras.events.ONVIF_PULL_TIMEOUT", timedelta(seconds=0.01)),
        patch("custom_components.tapo_cameras.events.ONVIF_PULL_GRACE", 0.01),
        patch.object(OnvifEvents, "_backoff", AsyncMock(side_effect=asyncio.CancelledError)) as backoff,
    ):
        events.async_start()
        with pytest.raises(asyncio.CancelledError):
            await events._task
    backoff.assert_awaited_once_with(5)
    assert not events.connected


async def test_empty_answers_do_not_spin(hass: HomeAssistant, with_events: MockConfigEntry, subscription) -> None:
    """A firmware answering at once with nothing is pulled at most once a second."""
    waits = []

    async def wait(delay):
        waits.append(delay)
        if len(waits) == 3:
            raise asyncio.CancelledError

    events = with_events.runtime_data.events
    events.async_stop()
    for _ in range(5):
        await subscription.batches.put([])
    with patch.object(OnvifEvents, "_backoff", side_effect=wait):
        events.async_start()
        with pytest.raises(asyncio.CancelledError):
            await events._task
    assert waits == [1.0, 1.0, 1.0]
