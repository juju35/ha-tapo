"""Reading the camera's answers."""

from __future__ import annotations

import copy

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tapo_cameras.diagnostics import async_get_config_entry_diagnostics
from custom_components.tapo_cameras.model import TapoData, dig, is_on, sensitivity_level, size_in_bytes
from custom_components.tapo_cameras.update import parse_upgrade_info

from .conftest import FIXTURE


def test_dig() -> None:
    assert dig({"a": [{"b": 1}]}, "a", 0, "b") == 1
    assert dig({"a": [{"b": 1}]}, "a", 3, "b") is None
    assert dig({"a": "text"}, "a", "b") is None


@pytest.mark.parametrize(("value", "expected"), [("on", True), ("OFF", False), (1, True), ("0", False), (None, None)])
def test_is_on(value, expected) -> None:
    assert is_on(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("20", "low"),
        (50, "normal"),
        ("80", "high"),
        ("medium", "normal"),
        ("high", "high"),
        ("bogus", None),
        (None, None),
    ],
)
def test_sensitivity_level(value, expected) -> None:
    assert sensitivity_level(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"), [("29.7GB", 29.7e9), ("512 MB", 512e6), ("1TB", 1e12), ("0B", 0), ("?", None)]
)
def test_size_in_bytes(value, expected) -> None:
    assert size_in_bytes(value) == expected


def test_unsupported_methods_are_none() -> None:
    data = TapoData(raw=copy.deepcopy(FIXTURE))
    assert data.get("getBarkDetectionConfig") is None
    assert data.get("getNotAsked") is None
    assert data.mac == "aa:bb:cc:dd:ee:ff"
    assert data.presets == {"1": "Door", "2": "Window"}
    assert data.ptz
    assert data.disks[0]["free_space"] == "12.5GB"
    assert data.smart_track == {"people_enabled": True, "pet_enabled": False}


def test_set_writes_only_existing_answers() -> None:
    data = TapoData(raw=copy.deepcopy(FIXTURE))
    data.set("getLedStatus", ("led", "config", "enabled"), "off")
    assert data.get("getLedStatus", "led", "config", "enabled") == "off"
    data.set("getBarkDetectionConfig", ("bark_detection", "detection", "enabled"), "on")
    assert data.get("getBarkDetectionConfig") is None


def test_parse_upgrade_info() -> None:
    answer = {
        "result": {
            "responses": [
                {"method": "checkFirmwareVersionByCloud", "result": {}},
                {"result": {"cloud_config": {"upgrade_info": {"version": "1.2.0", "release_log": "Fixes"}}}},
            ]
        }
    }
    assert parse_upgrade_info(answer)["version"] == "1.2.0"
    assert parse_upgrade_info({"result": {"responses": [{"result": {"cloud_config": {"upgrade_info": {}}}}]}}) is None


async def test_diagnostics_hide_secrets(hass: HomeAssistant, loaded: MockConfigEntry) -> None:
    diagnostics = await async_get_config_entry_diagnostics(hass, loaded)
    text = str(diagnostics)
    for secret in ("cloud-secret", "cam-secret", "camuser", "192.168.1.15", "AA-BB-CC-DD-EE-FF", "Home"):
        assert secret not in text, secret
    assert diagnostics["state"]["getLedStatus"] == [{"led": {"config": {"enabled": "on"}}}]
