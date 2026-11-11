"""Media player: the camera's speaker. Plays sounds, files and text-to-speech (`tts.speak`)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from homeassistant.components import media_source
from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityDescription,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    async_process_play_media_url,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TapoConfigEntry
from .api import TapoError
from .const import DOMAIN
from .entity import TapoEntity
from .model import is_on
from .talk import TalkError, async_talk

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

SPEAKER = MediaPlayerEntityDescription(key="speaker", translation_key="speaker")
VOLUME = ("getAudioConfig", "audio_config", "speaker", "volume")


class TapoSpeaker(TapoEntity, MediaPlayerEntity):
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.BROWSE_MEDIA
        | MediaPlayerEntityFeature.MEDIA_ANNOUNCE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.VOLUME_SET
    )
    _attr_media_content_type = MediaType.MUSIC
    _task: asyncio.Task | None = None

    @property
    def state(self) -> MediaPlayerState:
        return MediaPlayerState.PLAYING if self._task is not None else MediaPlayerState.IDLE

    @property
    def volume_level(self) -> float | None:
        try:
            return int(self.data.get(*VOLUME)) / 100
        except (TypeError, ValueError):
            return None

    async def async_set_volume_level(self, volume: float) -> None:
        level = round(volume * 100)
        await self.coordinator.async_command(
            lambda tapo: tapo.setSpeakerVolume(level),
            apply=lambda data: data.set(VOLUME[0], VOLUME[1:], str(level)),
        )

    async def async_browse_media(
        self, media_content_type: MediaType | str | None = None, media_content_id: str | None = None
    ) -> BrowseMedia:
        return await media_source.async_browse_media(
            self.hass,
            media_content_id,
            content_filter=lambda item: item.media_content_type.startswith("audio/"),
        )

    async def async_play_media(self, media_type: MediaType | str, media_id: str, **kwargs: Any) -> None:
        if is_on(self.data.get("getLensMaskConfig", "lens_mask", "lens_mask_info", "enabled")):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="privacy_mode")
        if media_source.is_media_source_id(media_id):
            media_id = (await media_source.async_resolve_media(self.hass, media_id, self.entity_id)).url
        url = async_process_play_media_url(self.hass, media_id)
        try:
            session = await self.coordinator.client.async_call(lambda tapo: tapo.getMediaSession(), reconnect=False)
        except TapoError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"host": self.coordinator.client.host, "error": str(err)},
            ) from err
        # One sound at a time: a new one replaces the one playing.
        await self._async_cancel()
        self._task = self.hass.async_create_background_task(
            self._async_play(session, url), f"{DOMAIN} talk {self.coordinator.client.host}"
        )
        self.async_write_ha_state()

    async def _async_play(self, session: Any, url: str) -> None:
        try:
            seconds = await async_talk(session, get_ffmpeg_manager(self.hass).binary, url)
            _LOGGER.debug("%s: played %.1f s", self.coordinator.client.host, seconds)
        except (TalkError, OSError, asyncio.IncompleteReadError) as err:
            _LOGGER.warning("%s: could not play on the speaker: %s", self.coordinator.client.host, err)
        finally:
            if self._task is asyncio.current_task():
                self._task = None
                self.async_write_ha_state()

    async def _async_cancel(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def async_media_stop(self) -> None:
        await self._async_cancel()
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        await self._async_cancel()
        await super().async_will_remove_from_hass()


async def async_setup_entry(
    hass: HomeAssistant, entry: TapoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    if coordinator.data.get(*VOLUME) is not None:
        async_add_entities([TapoSpeaker(coordinator, SPEAKER)])
