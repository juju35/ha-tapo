"""Connection to a camera's control API.

Tapo firmwares process one request at a time: two requests sent together make the second one
fail with an authentication error, which drops the session. Every call, polling or control, goes
through one queue per camera (`asyncio.Lock`), and the state is read with a single batched request.
The library is synchronous; calls run in the executor.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from typing import Any, TypeVar

from homeassistant.core import HomeAssistant
from pytapo import Tapo

from .const import CONTROL_USER, RECONNECT_BACKOFF, REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")

_SUSPENDED = re.compile(r"Temporary Suspension: Try again in (\d+) seconds", re.IGNORECASE)
_AUTH_MARKERS = ("invalid authentication data", "invalid login credentials", "-40209", "-40418")
_PRIVACY_MARKERS = ("-64324", "privacy mode is on")

# Methods the batched request asks for that a camera may answer with an invalid response,
# dropped on a retry once the whole batch has failed.
_FRAGILE_METHODS = ["getAudioConfig"]


class TapoError(Exception):
    """A request to the camera failed."""


class TapoConnectionError(TapoError):
    """The camera could not be reached or the session was lost."""


class TapoAuthError(TapoError):
    """The camera refused the credentials."""


class TapoSuspendedError(TapoError):
    """The camera blocks logins for a while after too many failures."""

    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TapoPrivacyModeError(TapoError):
    """The request is refused while privacy mode is on."""


def classify(err: BaseException) -> TapoError:
    """Map a library exception (always a bare Exception) to a typed error."""
    if isinstance(err, TapoError):
        return err
    message = str(err)
    lowered = message.lower()
    if match := _SUSPENDED.search(message):
        return TapoSuspendedError(message, int(match.group(1)))
    if any(marker in lowered for marker in _AUTH_MARKERS):
        return TapoAuthError(message)
    if any(marker in lowered for marker in _PRIVACY_MARKERS):
        return TapoPrivacyModeError(message)
    if isinstance(err, (OSError, TimeoutError)) or "connection" in lowered or "timed out" in lowered:
        return TapoConnectionError(message)
    return TapoError(message)


class TapoClient:
    """One camera, one session, one request at a time."""

    def __init__(self, hass: HomeAssistant, host: str, password: str, control_port: int) -> None:
        self._hass = hass
        self.host = host
        self._password = password
        self._control_port = control_port
        self._tapo: Tapo | None = None
        self._lock = asyncio.Lock()
        self._failures = 0
        self._next_attempt = 0.0

    @property
    def connected(self) -> bool:
        return self._tapo is not None

    @property
    def is_klap(self) -> bool:
        return bool(self._tapo and self._tapo.isKLAP)

    def _create(self) -> Tapo:
        return Tapo(
            self.host,
            CONTROL_USER,
            self._password,
            self._password,
            controlPort=self._control_port,
            # The session is kept; an expired one is renewed by the library on the next request.
            reuseSession=True,
            retryStok=True,
            printWarnInformation=False,
            hass=self._hass,
        )

    async def _async_connect(self) -> Tapo:
        loop = asyncio.get_running_loop()
        if (wait := self._next_attempt - loop.time()) > 0:
            raise TapoConnectionError(f"Waiting {wait:.0f} s before connecting to {self.host} again")
        try:
            tapo = await asyncio.wait_for(self._hass.async_add_executor_job(self._create), REQUEST_TIMEOUT * 2)
        except Exception as err:
            error = classify(err)
            if isinstance(error, TapoSuspendedError):
                delay = error.retry_after
            else:
                delay = RECONNECT_BACKOFF[min(self._failures, len(RECONNECT_BACKOFF) - 1)]
            self._failures += 1
            self._next_attempt = loop.time() + delay
            if isinstance(error, TapoError) and type(error) is TapoError:
                raise TapoConnectionError(str(error)) from err
            raise error from err
        self._failures = 0
        self._next_attempt = 0.0
        _LOGGER.debug("Connected to %s (KLAP: %s)", self.host, tapo.isKLAP)
        return tapo

    async def _async_drop(self) -> None:
        """Forget the session so that the next call logs in again."""
        tapo, self._tapo = self._tapo, None
        if tapo is not None:
            try:
                await self._hass.async_add_executor_job(tapo.close)
            except Exception:  # noqa: BLE001 - closing a broken session may fail too
                _LOGGER.debug("Closing the session of %s failed", self.host, exc_info=True)

    async def async_call(self, func: Callable[[Tapo], T], *, reconnect: bool = True) -> T:
        """Run `func(tapo)` in the executor, after the previous call has finished."""
        async with self._lock:
            if self._tapo is None:
                self._tapo = await self._async_connect()
            tapo = self._tapo
            try:
                return await asyncio.wait_for(self._hass.async_add_executor_job(func, tapo), REQUEST_TIMEOUT)
            except Exception as err:
                error = classify(err)
                if isinstance(error, TapoPrivacyModeError) or type(error) is TapoError:
                    # The camera answered: the session is fine.
                    raise error from err
                await self._async_drop()
                if not reconnect or isinstance(error, (TapoAuthError, TapoSuspendedError)):
                    raise error from err
                _LOGGER.debug("Request to %s failed (%s), logging in again", self.host, err)
            # Once more with a new session: a session dropped by the camera is the usual cause.
            self._tapo = await self._async_connect()
            try:
                return await asyncio.wait_for(self._hass.async_add_executor_job(func, self._tapo), REQUEST_TIMEOUT)
            except Exception as err:
                error = classify(err)
                if not isinstance(error, TapoPrivacyModeError) and type(error) is not TapoError:
                    await self._async_drop()
                raise error from err

    async def async_get_state(self) -> dict[str, list[Any]]:
        """Every setting of the camera in one request."""

        def get_most(tapo: Tapo) -> dict[str, list[Any]]:
            try:
                return tapo.getMost()
            except Exception:
                # Some firmwares answer the batch with invalid JSON because of one method.
                _LOGGER.debug("Batched request to %s failed, retrying without %s", self.host, _FRAGILE_METHODS)
                return tapo.getMost(omit_methods=_FRAGILE_METHODS)

        return await self.async_call(get_most)

    async def async_close(self) -> None:
        async with self._lock:
            await self._async_drop()
