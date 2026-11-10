"""The connection: one request at a time, new session after a lost one, errors mapped."""

from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tapo_cameras.api import (
    TapoAuthError,
    TapoClient,
    TapoConnectionError,
    TapoError,
    TapoPrivacyModeError,
    TapoSuspendedError,
    classify,
)

from .conftest import FakeCamera


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Invalid authentication data", TapoAuthError),
        ("Temporary Suspension: Try again in 1800 seconds", TapoSuspendedError),
        ("Error: Privacy mode is ON, not able to execute, Response: {}", TapoPrivacyModeError),
        ("HTTPSConnectionPool(host='1.2.3.4', port=443): Read timed out.", TapoConnectionError),
        ("Error: Method does not exist", TapoError),
    ],
)
def test_classify(message: str, expected: type) -> None:
    assert type(classify(Exception(message))) is expected


def test_suspension_delay() -> None:
    assert classify(Exception("Temporary Suspension: Try again in 1800 seconds")).retry_after == 1800


async def test_requests_never_overlap(hass: HomeAssistant, camera: FakeCamera) -> None:
    client = TapoClient(hass, "1.2.3.4", "secret", 443)
    running, overlaps, lock = 0, [], threading.Lock()

    def call(_tapo):
        nonlocal running
        with lock:
            running += 1
            overlaps.append(running)
        time.sleep(0.02)
        with lock:
            running -= 1

    await asyncio.gather(*(client.async_call(call) for _ in range(5)))
    assert max(overlaps) == 1
    # One login for all of them.
    assert camera.constructor.call_count == 1


async def test_new_session_after_a_lost_one(hass: HomeAssistant, camera: FakeCamera) -> None:
    client = TapoClient(hass, "1.2.3.4", "secret", 443)
    answers = iter([Exception("Connection aborted"), "ok"])

    def call(_tapo):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    assert await client.async_call(call) == "ok"
    assert camera.constructor.call_count == 2
    camera.tapo.close.assert_called_once()


async def test_refused_change_keeps_the_session(hass: HomeAssistant, camera: FakeCamera) -> None:
    client = TapoClient(hass, "1.2.3.4", "secret", 443)

    def call(_tapo):
        raise Exception("Error: Privacy mode is ON, not able to execute")

    with pytest.raises(TapoPrivacyModeError):
        await client.async_call(call)
    assert client.connected
    camera.tapo.close.assert_not_called()


async def test_no_login_storm(hass: HomeAssistant, camera: FakeCamera) -> None:
    """After a failed login, the next attempts wait instead of hitting the camera (it locks itself)."""
    camera.constructor.side_effect = Exception("Connection refused")
    client = TapoClient(hass, "1.2.3.4", "secret", 443)
    for _ in range(3):
        with pytest.raises(TapoConnectionError):
            await client.async_call(lambda tapo: None)
    assert camera.constructor.call_count == 1


async def test_bad_password_starts_reauth(hass: HomeAssistant, camera: FakeCamera, entry: MockConfigEntry) -> None:
    camera.constructor.side_effect = Exception("Invalid authentication data")
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_unreachable_camera_retries_setup(
    hass: HomeAssistant, camera: FakeCamera, entry: MockConfigEntry
) -> None:
    camera.constructor.side_effect = Exception("Connection refused")
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_batch_retried_without_fragile_method(hass: HomeAssistant, camera: FakeCamera) -> None:
    state = camera.tapo.getMost.side_effect
    camera.tapo.getMost.side_effect = lambda omit_methods=(), **kw: (
        state() if omit_methods else (_ for _ in ()).throw(Exception("Expecting value: line 1"))
    )
    client = TapoClient(hass, "1.2.3.4", "secret", 443)
    assert "getDeviceInfo" in await client.async_get_state()
    camera.tapo.getMost.assert_called_with(omit_methods=["getAudioConfig"])


async def test_timeout_drops_the_session(hass: HomeAssistant, camera: FakeCamera) -> None:
    client = TapoClient(hass, "1.2.3.4", "secret", 443)
    with patch("custom_components.tapo_cameras.api.REQUEST_TIMEOUT", 0.05), pytest.raises(TapoConnectionError):
        await client.async_call(lambda tapo: time.sleep(0.2), reconnect=False)
    assert not client.connected
