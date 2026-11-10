"""Polling of one camera."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from time import monotonic
from typing import TYPE_CHECKING, Any, TypeVar

from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
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
from .const import (
    DEFAULT_MOVE_ANGLE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STREAM_QUALITY,
    DOMAIN,
    FULL_REFRESH_INTERVAL,
    REFRESH_AFTER_WRITE,
    SLOW_METHODS,
    STALE_ANSWER_LIMIT,
    UNUSED_METHODS,
)
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
        # Monotonic time of the last refresh that asked every request; None: the next one must.
        self._full_at: float | None = None
        self._logins_seen = 0
        # Request → monotonic time it first failed, while the last good answer is kept.
        self._failing_since: dict[str, float] = {}

    @property
    def failing(self) -> list[str]:
        return list(self._failing_since)

    @callback
    def async_request_full_refresh(self) -> None:
        """Make the next refresh ask the slow requests too."""
        self._full_at = None

    async def _async_update_data(self) -> TapoData:
        now = monotonic()
        full = (
            self.data is None
            or self._full_at is None
            or self.client.logins != self._logins_seen
            or now - self._full_at >= FULL_REFRESH_INTERVAL.total_seconds()
        )
        omit = UNUSED_METHODS if full else UNUSED_METHODS | SLOW_METHODS
        try:
            raw = await self.client.async_get_state(omit)
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
        if full:
            self._full_at, self._logins_seen = now, self.client.logins
        return TapoData(raw=self._merge(raw, omit, now))

    def _merge(self, raw: dict[str, list[Any]], omit: frozenset[str], now: float) -> dict[str, list[Any]]:
        """Fill the requests not asked, or failing for a short while, with their last good answer."""
        if self.data is None:
            return raw
        for method, answers in self.data.raw.items():
            if method in UNUSED_METHODS:
                continue
            if method in omit:
                raw[method] = answers
                continue
            new = raw.get(method) or []
            # Answer by answer: a request asked twice may fail only once.
            lost = [i for i, answer in enumerate(answers) if answer is not False and (i >= len(new) or new[i] is False)]
            if not lost:
                self._failing_since.pop(method, None)
                continue
            since = self._failing_since.setdefault(method, now)
            if now - since >= STALE_ANSWER_LIMIT.total_seconds():
                if now - since < STALE_ANSWER_LIMIT.total_seconds() + self.update_interval.total_seconds():
                    _LOGGER.debug("%s: %s keeps failing, its entities become unavailable", self.client.host, method)
                continue
            merged = [*new, *[False] * (len(answers) - len(new))]
            for i in lost:
                merged[i] = answers[i]
            raw[method] = merged
        return raw

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
        # The change may touch a slow request (preset saved, scheduled reboot…): confirm it too.
        self.async_request_full_refresh()
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
