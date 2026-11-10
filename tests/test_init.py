"""Setup, entities created from what the camera supports, and changes."""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.camera import async_get_stream_source
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed, mock_restore_cache

from custom_components.tapo_cameras.const import DOMAIN

from .conftest import FakeCamera


def _entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"aa:bb:cc:dd:ee:ff_{key}")
    assert entity_id, f"{platform}.{key} not created"
    return entity_id


async def test_setup_and_unload(hass: HomeAssistant, loaded: MockConfigEntry, camera: FakeCamera) -> None:
    assert loaded.state is ConfigEntryState.LOADED
    # Control login: "admin" with the Tapo account password.
    args = camera.constructor.call_args
    assert args.args[:4] == ("192.168.1.15", "admin", "cloud-secret", "cloud-secret")
    assert await hass.config_entries.async_unload(loaded.entry_id)
    assert loaded.state is ConfigEntryState.NOT_LOADED
    camera.tapo.close.assert_called()


async def test_entities_follow_capabilities(hass: HomeAssistant, loaded: MockConfigEntry) -> None:
    registry = er.async_get(hass)
    keys = {
        e.unique_id.removeprefix("aa:bb:cc:dd:ee:ff_")
        for e in er.async_entries_for_config_entry(registry, loaded.entry_id)
    }
    # Supported by the fixture.
    for key in (
        "camera",
        "stream_quality",
        "privacy_mode",
        "smart_track_people_enabled",
        "alarm_trigger_motion_detection",
        "person_detection",
        "tamper_detection",
        "night_vision",
        "preset",
        "move_up",
        "move_angle",
        "spotlight_intensity",
        "spotlight",
        "siren",
        "sd_card_free_space",
        "signal_strength",
        "firmware",
    ):
        assert key in keys, key
    # Not answered by this camera.
    for key in ("bark_detection", "package_detection", "floodlight"):
        assert key not in keys, key
    # Events disabled in the options: no detection sensors.
    assert not any(k in keys for k in ("motion", "event_subscription"))


async def test_states(hass: HomeAssistant, loaded: MockConfigEntry) -> None:
    assert hass.states.get(_entity_id(hass, "switch", "privacy_mode")).state == "off"
    assert hass.states.get(_entity_id(hass, "switch", "indicator_led")).state == "on"
    assert hass.states.get(_entity_id(hass, "select", "motion_detection")).state == "normal"
    assert hass.states.get(_entity_id(hass, "select", "person_detection")).state == "high"
    assert hass.states.get(_entity_id(hass, "select", "vehicle_detection")).state == "off"
    assert hass.states.get(_entity_id(hass, "select", "tamper_detection")).state == "normal"
    assert hass.states.get(_entity_id(hass, "select", "night_vision")).state == "inf_night_vision"
    preset = hass.states.get(_entity_id(hass, "select", "preset"))
    assert preset.attributes["options"] == ["Door", "Window"]
    assert hass.states.get(_entity_id(hass, "number", "speaker_volume")).state == "60"
    assert float(hass.states.get(_entity_id(hass, "sensor", "sd_card_free_space")).state) == 12.5
    assert hass.states.get(_entity_id(hass, "sensor", "signal_strength")).state == "-39"
    assert hass.states.get(_entity_id(hass, "camera", "camera")).state != "off"


async def test_switch_applies_at_once(hass: HomeAssistant, loaded: MockConfigEntry, camera: FakeCamera) -> None:
    entity_id = _entity_id(hass, "switch", "privacy_mode")
    await hass.services.async_call("switch", "turn_on", {"entity_id": entity_id}, blocking=True)
    camera.tapo.setPrivacyMode.assert_called_once_with(True)
    # Shown before the confirming refresh, which would still report the old value here.
    assert hass.states.get(entity_id).state == "on"
    # The camera is off while privacy mode is on: no stream.
    with pytest.raises(HomeAssistantError, match="off"):
        await async_get_stream_source(hass, _entity_id(hass, "camera", "camera"))


async def test_detection_select(hass: HomeAssistant, loaded: MockConfigEntry, camera: FakeCamera) -> None:
    entity_id = _entity_id(hass, "select", "vehicle_detection")
    await hass.services.async_call("select", "select_option", {"entity_id": entity_id, "option": "high"}, blocking=True)
    camera.tapo.setVehicleDetection.assert_called_once_with(True, "high")
    assert hass.states.get(entity_id).state == "high"
    await hass.services.async_call("select", "select_option", {"entity_id": entity_id, "option": "off"}, blocking=True)
    camera.tapo.setVehicleDetection.assert_called_with(False, False)
    assert hass.states.get(entity_id).state == "off"


async def test_alarm_trigger_switch(hass: HomeAssistant, loaded: MockConfigEntry, camera: FakeCamera) -> None:
    registry = er.async_get(hass)
    entity_id = _entity_id(hass, "switch", "alarm_trigger_people_detection")
    registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(loaded.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "off"
    await hass.services.async_call("switch", "turn_on", {"entity_id": entity_id}, blocking=True)
    camera.tapo.setAlertEventType.assert_called_once_with("people_detection", True)
    assert hass.states.get(entity_id).state == "on"


async def test_move_and_presets(hass: HomeAssistant, loaded: MockConfigEntry, camera: FakeCamera) -> None:
    await hass.services.async_call(
        "number", "set_value", {"entity_id": _entity_id(hass, "number", "move_angle"), "value": 30}, blocking=True
    )
    await hass.services.async_call(
        "button", "press", {"entity_id": _entity_id(hass, "button", "move_left")}, blocking=True
    )
    camera.tapo.moveMotor.assert_called_once_with(-30, 0)

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": _entity_id(hass, "select", "preset"), "option": "Window"},
        blocking=True,
    )
    camera.tapo.setPreset.assert_called_once_with("2")

    cam = _entity_id(hass, "camera", "camera")
    await hass.services.async_call(DOMAIN, "go_to_preset", {"entity_id": cam, "preset": "Door"}, blocking=True)
    camera.tapo.setPreset.assert_called_with("1")
    await hass.services.async_call(DOMAIN, "ptz", {"entity_id": cam, "pan": 10, "tilt": -5}, blocking=True)
    camera.tapo.moveMotor.assert_called_with(10, -5)


async def test_stream_quality(hass: HomeAssistant, loaded: MockConfigEntry) -> None:
    camera_id = _entity_id(hass, "camera", "camera")
    assert await async_get_stream_source(hass, camera_id) == "rtsp://camuser:cam-secret@192.168.1.15:554/stream1"
    assert hass.states.get(camera_id).attributes["stream_quality"] == "hd"

    quality = _entity_id(hass, "select", "stream_quality")
    await hass.services.async_call("select", "select_option", {"entity_id": quality, "option": "sd"}, blocking=True)
    assert hass.states.get(quality).state == "sd"
    assert await async_get_stream_source(hass, camera_id) == "rtsp://camuser:cam-secret@192.168.1.15:554/stream2"
    assert hass.states.get(camera_id).attributes["stream_quality"] == "sd"


async def test_running_stream_switches(hass: HomeAssistant, loaded: MockConfigEntry) -> None:
    camera = next(e for e in hass.data["camera"].entities if e.entity_id == _entity_id(hass, "camera", "camera"))
    camera.stream = MagicMock()
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": _entity_id(hass, "select", "stream_quality"), "option": "sd"},
        blocking=True,
    )
    camera.stream.update_source.assert_called_once_with("rtsp://camuser:cam-secret@192.168.1.15:554/stream2")


async def test_stream_quality_restored(hass: HomeAssistant, camera: FakeCamera, entry: MockConfigEntry) -> None:
    mock_restore_cache(hass, [State("select.living_room_stream_quality", "sd")])
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    source = await async_get_stream_source(hass, _entity_id(hass, "camera", "camera"))
    assert source.endswith("/stream2")


async def test_firmware_check(hass: HomeAssistant, loaded: MockConfigEntry, camera: FakeCamera) -> None:
    camera.tapo.isUpdateAvailable.return_value = {
        "result": {"responses": [{}, {"result": {"cloud_config": {"upgrade_info": {"version": "1.2.0 Build 251001"}}}}]}
    }
    entity_id = _entity_id(hass, "update", "firmware")
    assert hass.states.get(entity_id).state == "off"
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=121))
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == "on"
    assert state.attributes["latest_version"] == "1.2.0 Build 251001"
    await hass.services.async_call("update", "install", {"entity_id": entity_id}, blocking=True)
    camera.tapo.startFirmwareUpgrade.assert_called_once()


async def test_snapshots_shared(hass: HomeAssistant, loaded: MockConfigEntry) -> None:
    """Several dashboards asking at once: one ffmpeg, the still served again for a few seconds."""
    from homeassistant.components.camera import async_get_image

    calls = 0

    async def slow_image(*args, **kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return b"jpeg"

    entity_id = _entity_id(hass, "camera", "camera")
    with patch("custom_components.tapo_cameras.camera.async_get_image", slow_image):
        images = await asyncio.gather(*(async_get_image(hass, entity_id) for _ in range(5)))
        assert all(image.content == b"jpeg" for image in images)
        assert calls == 1
        with patch("custom_components.tapo_cameras.camera.monotonic", return_value=time.monotonic() + 6):
            await async_get_image(hass, entity_id)
        assert calls == 2
