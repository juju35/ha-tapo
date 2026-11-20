"""Lights (spotlight, floodlight) and siren: commands, state shown at once, no command when already there."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tapo_cameras.const import DOMAIN

from .conftest import FakeCamera


def _entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"aa:bb:cc:dd:ee:ff_{key}")
    assert entity_id, f"{platform}.{key} not created"
    return entity_id


async def test_spotlight_toggles_only_when_the_state_differs(
    hass: HomeAssistant, loaded: MockConfigEntry, camera: FakeCamera
) -> None:
    light = _entity_id(hass, "light", "spotlight")
    assert hass.states.get(light).state == "off"
    # Already off: the camera only offers a toggle, so nothing is sent.
    await hass.services.async_call("light", "turn_off", {"entity_id": light}, blocking=True)
    camera.tapo.reverseWhitelampStatus.assert_not_called()
    await hass.services.async_call("light", "turn_on", {"entity_id": light}, blocking=True)
    camera.tapo.reverseWhitelampStatus.assert_called_once_with()
    assert hass.states.get(light).state == "on"
    await hass.services.async_call("light", "turn_off", {"entity_id": light}, blocking=True)
    assert camera.tapo.reverseWhitelampStatus.call_count == 2
    assert hass.states.get(light).state == "off"


async def test_floodlight_on_and_off(hass: HomeAssistant, camera: FakeCamera, entry: MockConfigEntry) -> None:
    camera.state["getFloodlightStatus"] = [{"status": 0}]
    with patch("custom_components.tapo_cameras.camera.async_get_image", return_value=b"jpeg"):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    light = _entity_id(hass, "light", "floodlight")
    assert hass.states.get(light).state == "off"
    await hass.services.async_call("light", "turn_on", {"entity_id": light}, blocking=True)
    camera.tapo.manualFloodlightOp.assert_called_once_with(True)
    assert hass.states.get(light).state == "on"
    await hass.services.async_call("light", "turn_off", {"entity_id": light}, blocking=True)
    camera.tapo.manualFloodlightOp.assert_called_with(False)
    assert hass.states.get(light).state == "off"


async def test_siren_start_and_stop(hass: HomeAssistant, loaded: MockConfigEntry, camera: FakeCamera) -> None:
    siren = _entity_id(hass, "siren", "siren")
    state = hass.states.get(siren)
    assert state.state == "off"
    assert not state.attributes.get("assumed_state")
    await hass.services.async_call("siren", "turn_on", {"entity_id": siren}, blocking=True)
    camera.tapo.startManualAlarm.assert_called_once_with()
    assert hass.states.get(siren).state == "on"
    await hass.services.async_call("siren", "turn_off", {"entity_id": siren}, blocking=True)
    camera.tapo.stopManualAlarm.assert_called_once_with()
    assert hass.states.get(siren).state == "off"


async def test_siren_without_status_is_assumed(hass: HomeAssistant, camera: FakeCamera, entry: MockConfigEntry) -> None:
    """An alarm camera that does not report the siren's status: the state is assumed."""
    camera.state["getSirenStatus"] = [False]
    with patch("custom_components.tapo_cameras.camera.async_get_image", return_value=b"jpeg"):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    state = hass.states.get(_entity_id(hass, "siren", "siren"))
    assert state.state == "unknown"
    assert state.attributes.get("assumed_state") is True
