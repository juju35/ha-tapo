"""Refreshes: what is asked each time, and answers kept while a request fails for a short while."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.tapo_cameras.const import DOMAIN, SLOW_METHODS, UNUSED_METHODS

from .conftest import FakeCamera


async def _refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"aa:bb:cc:dd:ee:ff_{key}")
    return hass.states.get(entity_id).state


async def test_unused_requests_never_asked(loaded: MockConfigEntry, camera: FakeCamera) -> None:
    for asked in camera.asked:
        assert not asked & UNUSED_METHODS


async def test_slow_requests_asked_now_and_then(
    hass: HomeAssistant, loaded: MockConfigEntry, camera: FakeCamera
) -> None:
    # Setup asked everything.
    assert SLOW_METHODS & set(camera.state) <= camera.asked[0]
    await _refresh(hass, loaded)
    assert not camera.asked[-1] & SLOW_METHODS
    # Their last answer is kept: entities stay available.
    assert _state(hass, "sensor", "sd_card_free_space") != "unavailable"
    assert _state(hass, "select", "preset") != "unavailable"

    with patch("custom_components.tapo_cameras.coordinator.monotonic", return_value=1e9):
        await _refresh(hass, loaded)
    assert SLOW_METHODS & set(camera.state) <= camera.asked[-1]


async def test_change_asks_everything_again(hass: HomeAssistant, loaded: MockConfigEntry, camera: FakeCamera) -> None:
    await _refresh(hass, loaded)
    switch = er.async_get(hass).async_get_entity_id("switch", DOMAIN, "aa:bb:cc:dd:ee:ff_automatic_reboot")
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=3))
    await hass.async_block_till_done()
    assert "getReboot" in camera.asked[-1]


async def test_failing_request_keeps_its_answer_for_a_while(
    hass: HomeAssistant, loaded: MockConfigEntry, camera: FakeCamera
) -> None:
    assert _state(hass, "select", "person_detection") == "high"
    # Refused this time (privacy mode, busy camera): last good answer kept.
    camera.state["getPersonDetectionConfig"] = [False]
    with patch("custom_components.tapo_cameras.coordinator.monotonic", return_value=1000.0):
        await _refresh(hass, loaded)
    assert _state(hass, "select", "person_detection") == "high"
    # Still failing after the limit: unavailable.
    with patch("custom_components.tapo_cameras.coordinator.monotonic", return_value=1000.0 + 601):
        await _refresh(hass, loaded)
    assert _state(hass, "select", "person_detection") == "unavailable"
    # Back.
    camera.state["getPersonDetectionConfig"] = [{"people_detection": {"detection": {"enabled": "off"}}}]
    await _refresh(hass, loaded)
    assert _state(hass, "select", "person_detection") == "off"


async def test_request_asked_twice_failing_once(
    hass: HomeAssistant, loaded: MockConfigEntry, camera: FakeCamera
) -> None:
    ldc = camera.state["getLdc"]
    camera.state["getLdc"] = [ldc[0], False]
    await _refresh(hass, loaded)
    assert loaded.runtime_data.data.raw["getLdc"] == ldc


async def test_new_login_asks_everything(hass: HomeAssistant, loaded: MockConfigEntry, camera: FakeCamera) -> None:
    loaded.runtime_data.client.logins += 1
    await _refresh(hass, loaded)
    assert "getDeviceInfo" in camera.asked[-1]
