"""Fixtures: a fake camera behind the library, and a config entry for it."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import frame
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tapo_cameras.const import CONF_CLOUD_PASSWORD, CONF_ONVIF_EVENTS, DOMAIN

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "c225.json").read_text(encoding="utf-8"))

ENTRY_DATA = {
    CONF_HOST: "192.168.1.15",
    CONF_CLOUD_PASSWORD: "cloud-secret",
    CONF_USERNAME: "camuser",
    CONF_PASSWORD: "cam-secret",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/ in every test."""
    yield


class _DeprecationRecorder(logging.Handler):
    """Collects Home Assistant deprecation reports that name this integration."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        lowered = message.lower()
        reported = record.name == frame.__name__ or "deprecated" in lowered or "will stop working" in lowered
        if reported and (f"'{DOMAIN}'" in message or f"custom_components/{DOMAIN}/" in message):
            self.messages.append(message)


@pytest.fixture(autouse=True)
def no_deprecated_calls():
    """Fail a test whose code path makes Home Assistant report a deprecated call of this integration."""
    getattr(frame, "_REPORTED_INTEGRATIONS", set()).clear()
    recorder = _DeprecationRecorder()
    root = logging.getLogger()
    root.addHandler(recorder)
    try:
        yield
    finally:
        root.removeHandler(recorder)
    if recorder.messages and (path := os.environ.get("DEPRECATIONS_LOG")):
        with open(path, "a", encoding="utf-8") as log:
            log.writelines(f"{m}\n" for m in recorder.messages)
    assert not recorder.messages, "\n".join(recorder.messages)


@pytest.fixture(autouse=True)
def no_onvif():
    """No real ONVIF connection: a subscription that never comes up (tests/test_events.py fakes one)."""

    async def never(self):
        await asyncio.Event().wait()

    with patch("custom_components.tapo_cameras.events.OnvifEvents._subscribe", never):
        yield


class FakeCamera:
    """What the library returns; `state` is what the camera currently holds."""

    def __init__(self) -> None:
        self.state: dict[str, list[Any]] = copy.deepcopy(FIXTURE)
        self.tapo = MagicMock(name="Tapo")
        self.tapo.isKLAP = False
        self.tapo.deviceType = "SMART.IPCAMERA"
        self.tapo.basicInfo = self.state["getDeviceInfo"][0]
        self.tapo.getMost.side_effect = self.get_most
        self.asked: list[set[str]] = []
        self.constructor = MagicMock(name="Tapo()", return_value=self.tapo)

    def get_most(self, omit_methods=(), **kwargs) -> dict[str, list[Any]]:
        """Like the library: omitted requests are answered False."""
        answer = copy.deepcopy(self.state)
        for method in omit_methods:
            answer[method] = [False]
        self.asked.append(set(self.state) - set(omit_methods))
        return answer


@pytest.fixture
def camera() -> FakeCamera:
    fake = FakeCamera()
    with (
        patch("custom_components.tapo_cameras.api.Tapo", fake.constructor),
        patch("custom_components.tapo_cameras.config_flow.Tapo", fake.constructor),
    ):
        yield fake


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Living room",
        unique_id="aa:bb:cc:dd:ee:ff",
        data=dict(ENTRY_DATA),
        options={CONF_ONVIF_EVENTS: False},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def loaded(hass: HomeAssistant, camera: FakeCamera, entry: MockConfigEntry) -> MockConfigEntry:
    with patch("custom_components.tapo_cameras.camera.async_get_image", return_value=b"jpeg"):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry
