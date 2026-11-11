"""Detection events, pulled from the camera's ONVIF event service.

The subscription is held for the whole life of the entry: it is renewed before it expires, and
when the camera drops it (reboot, Wi-Fi loss, firmware update) it is created again with a backoff.
Binary sensors exist from the start and are only unavailable while no subscription is active.
Some firmwares never send the "end" of an event: a state still on after `motion_timeout` seconds
without news is switched off.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    EVENT_TAPO,
    ONVIF_MESSAGE_LIMIT,
    ONVIF_MIN_PULL_INTERVAL,
    ONVIF_PULL_GRACE,
    ONVIF_PULL_TIMEOUT,
    ONVIF_RETRY_BACKOFF,
    ONVIF_SUBSCRIPTION_TTL,
)

_LOGGER = logging.getLogger(__name__)

# Data item names of the camera's events → detection key.
EVENT_ITEMS: dict[str, str] = {
    "IsMotion": "motion",
    "IsPeople": "person",
    "IsPerson": "person",
    "IsVehicle": "vehicle",
    "IsPet": "pet",
    "IsLineCross": "line_crossing",
    "IsLineCrossing": "line_crossing",
    "IsIntrusion": "area_intrusion",
    "IsTamper": "tamper",
    "IsBabyCry": "baby_cry",
    "IsBark": "bark",
    "IsMeow": "meow",
    "IsGlassBreak": "glass_break",
    "IsPackage": "package",
}
# Topics whose data item is not named after the detection.
EVENT_TOPICS: dict[str, str] = {
    "CellMotionDetector": "motion",
    "MotionAlarm": "motion",
    "PeopleDetector": "person",
    "TamperDetector": "tamper",
    "LineDetector": "line_crossing",
    "FieldDetector": "area_intrusion",
}

_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false", "1", "0"):
        return value.lower() in ("true", "1")
    return None


def _items(group: Any) -> list[tuple[str, Any]]:
    """(Name, Value) of the SimpleItems of a Data or Source group."""
    items = getattr(group, "SimpleItem", None) or []
    return [(getattr(item, "Name", None), getattr(item, "Value", None)) for item in items]


def parse_message(message: Any) -> list[tuple[str, bool]]:
    """Detections (key, active) carried by one ONVIF notification message."""
    topic = getattr(getattr(message, "Topic", None), "_value_1", None) or ""
    payload = getattr(getattr(message, "Message", None), "_value_1", None)
    data = getattr(payload, "Data", None)
    found: list[tuple[str, bool]] = []
    topic_key = next((key for part, key in EVENT_TOPICS.items() if part in topic), None)
    for name, value in _items(data):
        active = _as_bool(value)
        if not isinstance(name, str) or active is None:
            continue
        if name in EVENT_ITEMS:
            found.append((EVENT_ITEMS[name], active))
        elif name.startswith("Is") and len(name) > 2:
            # A detection this integration does not know yet: still reported, as its own key.
            found.append((_CAMEL.sub("_", name[2:]).lower(), active))
        elif topic_key is not None:
            found.append((topic_key, active))
    return found


def _onvif_camera(host: str, port: int, username: str, password: str) -> Any:
    """The ONVIF client, in the executor: importing it reads package metadata and building it lists the
    WSDL files and loads the system certificates, all blocking calls."""
    from onvif import ONVIFCamera  # noqa: PLC0415 - heavy import, only when events are enabled

    return ONVIFCamera(host, port, username, password)


class OnvifEvents:
    """Pull point subscription of one camera, with its detection states."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        username: str,
        password: str,
        motion_timeout: int,
        device_id: Callable[[], str | None],
    ) -> None:
        self._hass = hass
        self.host = host
        self._port = port
        self._username = username
        self._password = password
        self._motion_timeout = motion_timeout
        self._device_id = device_id
        self._device: str | None = None
        self.states: dict[str, bool] = {}
        self.changed_at: dict[str, datetime] = {}
        self.connected = False
        self.last_error: str | None = None
        self.messages = 0
        self._listeners: list[Callable[[], None]] = []
        self._timeouts: dict[str, CALLBACK_TYPE] = {}
        self._task: asyncio.Task | None = None
        self._lost = asyncio.Event()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            self._listeners.remove(listener)

        return remove

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def async_start(self) -> None:
        if self._task is None:
            self._task = self._hass.async_create_background_task(self._run(), f"{DOMAIN} events {self.host}")

    @callback
    def async_stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        for cancel in self._timeouts.values():
            cancel()
        self._timeouts.clear()

    # Subscription

    async def _run(self) -> None:
        failures = 0
        while True:
            camera = manager = None
            started = time.monotonic()
            try:
                camera, manager = await self._subscribe()
                service = manager.get_service()
                self._set_connected(True, None)
                failures = 0
                await self._pull(service)
                _LOGGER.debug("%s: event subscription lost, subscribing again", self.host)
            except asyncio.CancelledError:
                await self._close(camera, manager)
                raise
            except Exception as err:  # noqa: BLE001 - any failure of the camera or the library means "retry"
                delay = ONVIF_RETRY_BACKOFF[min(failures, len(ONVIF_RETRY_BACKOFF) - 1)]
                failures += 1
                level = logging.WARNING if failures == 3 else logging.DEBUG
                _LOGGER.log(level, "%s: events unavailable (%s), retrying in %s s", self.host, err, delay)
                self._set_connected(False, str(err) or type(err).__name__)
                await self._close(camera, manager)
                await self._backoff(delay)
                continue
            await self._close(camera, manager)
            self._set_connected(False, "subscription lost")
            # A subscription the camera drops right away: don't subscribe again in a tight loop.
            if time.monotonic() - started < ONVIF_SUBSCRIPTION_TTL.total_seconds():
                await self._backoff(ONVIF_RETRY_BACKOFF[0])

    @staticmethod
    async def _backoff(delay: float) -> None:
        await asyncio.sleep(delay)

    async def _subscribe(self) -> tuple[Any, Any]:
        camera = await self._hass.async_add_executor_job(
            _onvif_camera, self.host, self._port, self._username, self._password
        )
        try:
            await camera.update_xaddrs()
            self._lost.clear()
            manager = await camera.create_pullpoint_manager(ONVIF_SUBSCRIPTION_TTL, self._lost.set)
        except BaseException:
            with contextlib.suppress(Exception):
                await camera.close()
            raise
        return camera, manager

    async def _pull(self, service: Any) -> None:
        params = {"MessageLimit": ONVIF_MESSAGE_LIMIT, "Timeout": ONVIF_PULL_TIMEOUT}
        # The camera answers within ONVIF_PULL_TIMEOUT; no answer at all means a dead connection.
        deadline = ONVIF_PULL_TIMEOUT.total_seconds() + ONVIF_PULL_GRACE
        while not self._lost.is_set():
            started = time.monotonic()
            response = await asyncio.wait_for(service.PullMessages(params), deadline)
            messages = getattr(response, "NotificationMessage", None) or []
            for message in messages:
                self.messages += 1
                for key, active in parse_message(message):
                    self._update(key, active)
            # Some firmwares ignore the timeout and answer at once with nothing: don't spin.
            if not messages and time.monotonic() - started < ONVIF_MIN_PULL_INTERVAL:
                await self._backoff(ONVIF_MIN_PULL_INTERVAL)

    @staticmethod
    async def _close(camera: Any, manager: Any) -> None:
        if manager is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(manager.shutdown(), 5)
        if camera is not None:
            with contextlib.suppress(Exception):
                await camera.close()

    @callback
    def _set_connected(self, connected: bool, error: str | None) -> None:
        changed = connected != self.connected
        self.connected, self.last_error = connected, error
        if not connected:
            # What was detected before the loss is not known to have ended: clear it.
            for key in [k for k, v in self.states.items() if v]:
                self._update(key, False, notify=False)
            changed = True
        if changed:
            self._notify()

    # States

    @callback
    def _update(self, key: str, active: bool, notify: bool = True) -> None:
        if (cancel := self._timeouts.pop(key, None)) is not None:
            cancel()
        if active and self._motion_timeout > 0:
            self._timeouts[key] = async_call_later(self._hass, self._motion_timeout, self._timeout_callback(key))
        if self.states.get(key) == active:
            return
        self.states[key] = active
        self.changed_at[key] = dt_util.utcnow()
        if active:
            if self._device is None:
                self._device = self._device_id()
            self._hass.bus.async_fire(EVENT_TAPO, {"device_id": self._device, "host": self.host, "type": key})
        if notify:
            self._notify()

    def _timeout_callback(self, key: str) -> Callable[[datetime], None]:
        @callback
        def expire(_now: datetime) -> None:
            self._timeouts.pop(key, None)
            self._update(key, False)

        return expire

    def as_dict(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "last_error": self.last_error,
            "messages": self.messages,
            "states": dict(self.states),
            "changed_at": {k: v.isoformat() for k, v in self.changed_at.items()},
        }
