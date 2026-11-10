"""Firmware update: checked through the camera every few hours, installed on request."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later

from . import TapoConfigEntry
from .api import TapoError
from .entity import TapoEntity
from .model import dig

PARALLEL_UPDATES = 1
# The check asks the camera to query TP-Link's servers: not at every refresh.
SCAN_INTERVAL = timedelta(hours=6)

FIRMWARE = UpdateEntityDescription(key="firmware", device_class=UpdateDeviceClass.FIRMWARE)
# First check after setup, once Home Assistant has started and the camera is not busy.
FIRST_CHECK = 120
# Upgrade states the camera reports while downloading or flashing.
BUSY_STATES = {"downloading", "upgrading", "flashing", "rebooting"}


def parse_upgrade_info(answer: Any) -> dict[str, Any] | None:
    """The available firmware from the answer to the check, None when there is none."""
    for response in dig(answer, "result", "responses") or []:
        info = dig(response, "result", "cloud_config", "upgrade_info")
        if isinstance(info, dict) and info.get("version"):
            return info
    return None


class TapoFirmwareUpdate(TapoEntity, UpdateEntity):
    _attr_supported_features = UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES
    _latest: dict[str, Any] | None = None

    @property
    def should_poll(self) -> bool:
        # Polled every SCAN_INTERVAL for the latest version, on top of the coordinator's updates.
        return True

    @property
    def installed_version(self) -> str | None:
        return self.data.basic_info.get("sw_version")

    @property
    def latest_version(self) -> str | None:
        return (self._latest or {}).get("version") or self.installed_version

    @property
    def release_summary(self) -> str | None:
        notes = (self._latest or {}).get("release_log")
        return notes[:252] + "..." if isinstance(notes, str) and len(notes) > 255 else notes

    @property
    def in_progress(self) -> bool:
        state = self.data.get("getFirmwareUpdateStatus", "cloud_config", "upgrade_status", "state")
        return isinstance(state, str) and state.lower() in BUSY_STATES

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def first_check(_now: datetime) -> None:
            self.async_schedule_update_ha_state(force_refresh=True)

        self.async_on_remove(async_call_later(self.hass, FIRST_CHECK, first_check))

    async def async_release_notes(self) -> str | None:
        notes = (self._latest or {}).get("release_log")
        return notes.replace("\\n", "\n") if isinstance(notes, str) else None

    async def async_update(self) -> None:
        try:
            answer = await self.coordinator.client.async_call(lambda tapo: tapo.isUpdateAvailable())
        except TapoError:
            # The camera or the cloud is unreachable: keep what was known.
            return
        self._latest = parse_upgrade_info(answer)

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        await self.coordinator.async_command(lambda tapo: tapo.startFirmwareUpgrade(), retry=False)


async def async_setup_entry(
    hass: HomeAssistant, entry: TapoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    if coordinator.data.get("getFirmwareUpdateStatus") is not None:
        async_add_entities([TapoFirmwareUpdate(coordinator, FIRMWARE)], update_before_add=False)
