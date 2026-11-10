"""Polling of one camera."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any, TypeVar

from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pytapo import Tapo

from .api import (
    TapoAuthError,
    TapoClient,
    TapoError,
    TapoPrivacyModeError,
    TapoSuspendedError,
)
from .const import DEFAULT_MOVE_ANGLE, DEFAULT_SCAN_INTERVAL, DEFAULT_STREAM_QUALITY, DOMAIN, REFRESH_AFTER_WRITE
from .model import TapoData

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .events import OnvifEvents

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")


class TapoCoordinator(DataUpdateCoordinator[TapoData]):
    """State of one camera, refreshed with one request per interval."""

    config_entry: ConfigEntry
    events: OnvifEvents | None = None
    # Step of the move buttons, in degrees (number entity "move angle").
    move_angle: float = DEFAULT_MOVE_ANGLE
    # Stream of the camera entity (select "stream quality").
    stream_quality: str = DEFAULT_STREAM_QUALITY

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: TapoClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {client.host}",
            update_interval=timedelta(seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
            # Several writes in a row (sliders, PTZ) end in one refresh.
            request_refresh_debouncer=Debouncer(hass, _LOGGER, cooldown=REFRESH_AFTER_WRITE, immediate=False),
            always_update=False,
        )
        self.client = client

    async def _async_update_data(self) -> TapoData:
        try:
            raw = await self.client.async_get_state()
        except TapoAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="invalid_auth",
                translation_placeholders={"host": self.client.host},
            ) from err
        except TapoSuspendedError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="suspended",
                translation_placeholders={"host": self.client.host, "seconds": str(err.retry_after)},
            ) from err
        except TapoError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"host": self.client.host, "error": str(err)},
            ) from err
        if not isinstance(raw, dict):
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"host": self.client.host, "error": "unexpected answer"},
            )
        return TapoData(raw=raw)

    async def async_command(
        self,
        func: Callable[[Tapo], T],
        *,
        apply: Callable[[TapoData], Any] | None = None,
        retry: bool = True,
    ) -> T:
        """Send a change; on success apply it to the state at once, then confirm with a refresh.

        `retry=False` for actions that must not run twice (moves, reboot) if the answer is lost.
        """
        try:
            result = await self.client.async_call(func, reconnect=retry)
        except TapoPrivacyModeError as err:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="privacy_mode") from err
        except TapoAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="invalid_auth",
                translation_placeholders={"host": self.client.host},
            ) from err
        except TapoError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"host": self.client.host, "error": str(err)},
            ) from err
        if apply is not None and self.data is not None:
            apply(self.data)
            self.async_update_listeners()
        await self.async_request_refresh()
        return result

    @property
    def device_info(self) -> DeviceInfo:
        info = self.data.basic_info if self.data else {}
        mac = self.data.mac if self.data else None
        return DeviceInfo(
            identifiers={(DOMAIN, self.config_entry.unique_id or self.config_entry.entry_id)},
            connections={(CONNECTION_NETWORK_MAC, mac)} if mac else set(),
            manufacturer="TP-Link",
            model=info.get("device_model") or info.get("dev_name"),
            name=info.get("device_alias") or info.get("device_name") or self.config_entry.title,
            sw_version=info.get("sw_version"),
            hw_version=info.get("hw_version"),
        )
