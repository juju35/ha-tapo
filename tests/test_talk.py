"""Talk: the transport stream the camera reads, the talk session, and the speaker entity."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytapo.media_stream.tsReader import TSReader
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tapo_cameras import talk
from custom_components.tapo_cameras.const import DOMAIN
from custom_components.tapo_cameras.talk import FRAME_BYTES, TalkError, TsMuxer, _crc32_mpeg, async_talk

from .conftest import FakeCamera


def _packets(data: bytes) -> list[bytes]:
    assert len(data) % 188 == 0
    return [data[i : i + 188] for i in range(0, len(data), 188)]


def test_ts_packets_are_well_formed() -> None:
    muxer = TsMuxer()
    data = muxer.tables() + muxer.frame(bytes(range(256)) + bytes(64), 0)
    packets = _packets(data)
    assert all(packet[0] == 0x47 for packet in packets)
    # PAT and PMT: valid CRC (the CRC of a section with its CRC is 0), A-law stream type 0x90.
    for packet in packets[:2]:
        length = ((packet[6] & 0x0F) << 8) | packet[7]
        assert _crc32_mpeg(packet[5 : 8 + length]) == 0
    assert bytes([0x90, 0xE1, 0x00]) in packets[1]
    # Continuity counters go on per PID: the first frame took two audio packets.
    again = _packets(muxer.frame(bytes(FRAME_BYTES), 3600))
    assert again[0][3] & 0x0F == 2


def test_camera_reader_gets_the_audio_back() -> None:
    """The library's reader of the camera's own streams decodes what we send."""
    frame = bytes((i * 7) % 256 for i in range(FRAME_BYTES))
    muxer = TsMuxer()
    reader = TSReader()
    reader.setBuffer(muxer.tables() + muxer.frame(frame, 0) + muxer.frame(frame, 3600))
    packets = []
    while (packet := reader.getPacket()) is not None:
        packets.append(packet)
    assert packets
    assert bytes(packets[0].payload) == frame
    assert packets[0].payloadType.name == "PCMA"


class FakeMediaSession:
    """The camera's media port: answers the talk request, records the audio parts sent."""

    def __init__(self, refuse: tuple[str, ...] = ()) -> None:
        self.refuse = refuse
        self.requests: list[dict] = []
        self.sent: list[tuple[int, bytes]] = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True

    async def transceive(self, data, no_data_timeout=None):
        request = json.loads(data)
        self.requests.append(request)
        refused = request["params"]["talk"]["mode"] in self.refuse
        yield SimpleNamespace(
            session=None if refused else 7,
            json_data={"type": "response", "params": {"error_code": -40106 if refused else 0}},
        )
        await asyncio.Event().wait()


@pytest.fixture
def frames():
    async def fake(ffmpeg, source):
        for i in range(3):
            yield bytes([i]) * FRAME_BYTES

    async def record(session, talk_session, data):
        session.sent.append((talk_session, data))

    with (
        patch.object(talk, "_alaw_frames", fake),
        patch.object(talk, "_send", record),
        patch.object(talk, "FRAME_SECONDS", 0.001),
    ):
        yield


async def test_talk_session(frames) -> None:
    session = FakeMediaSession()
    assert await async_talk(session, "ffmpeg", "http://ha/tts.mp3") == pytest.approx(0.003)
    assert session.requests[0]["params"] == {"talk": {"mode": "aec"}, "method": "get"}
    assert [sid for sid, _ in session.sent] == [7, 7, 7]
    # Tables first, then one PES per frame.
    first = _packets(session.sent[0][1])
    assert first[0][1:3] == b"\x40\x00" and first[1][1:3] == b"\x50\x00"
    assert session.closed


async def test_half_duplex_when_echo_cancellation_refused(frames) -> None:
    session = FakeMediaSession(refuse=("aec",))
    await async_talk(session, "ffmpeg", "x")
    assert [r["params"]["talk"]["mode"] for r in session.requests] == ["aec", "half_duplex"]
    assert session.sent


async def test_refused(frames) -> None:
    with pytest.raises(TalkError, match="refused"):
        await async_talk(FakeMediaSession(refuse=("aec", "half_duplex")), "ffmpeg", "x")


async def test_ffmpeg_frames(hass: HomeAssistant, tmp_path) -> None:
    """FFmpeg output cut in frames, the last one padded with silence (real FFmpeg when installed)."""
    import shutil

    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg")
    source = tmp_path / "beep.wav"
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=0.1", str(source)
    )
    await process.wait()
    frames = [frame async for frame in talk._alaw_frames("ffmpeg", str(source))]
    assert len(frames) == 3  # 800 samples: 320 + 320 + 160 padded
    assert all(len(frame) == FRAME_BYTES for frame in frames)
    assert frames[-1].endswith(b"\xd5" * 160)


def _speaker(hass: HomeAssistant) -> str:
    return er.async_get(hass).async_get_entity_id("media_player", DOMAIN, "aa:bb:cc:dd:ee:ff_speaker")


async def test_speaker_plays(hass: HomeAssistant, loaded: MockConfigEntry, camera: FakeCamera) -> None:
    entity_id = _speaker(hass)
    assert hass.states.get(entity_id).state == "idle"
    assert hass.states.get(entity_id).attributes["volume_level"] == 0.6
    camera.tapo.getMediaSession.return_value = media = MagicMock()
    playing = asyncio.Event()

    async def fake_talk(session, ffmpeg, source):
        assert session is media
        assert source == "http://example.com/doorbell.mp3"
        playing.set()
        await asyncio.sleep(0.05)
        return 1.0

    with patch("custom_components.tapo_cameras.media_player.async_talk", side_effect=fake_talk) as talking:
        await hass.services.async_call(
            "media_player",
            "play_media",
            {
                "entity_id": entity_id,
                "media_content_type": "music",
                "media_content_id": "http://example.com/doorbell.mp3",
            },
            blocking=True,
        )
        await playing.wait()
        assert hass.states.get(entity_id).state == "playing"
        await hass.async_block_till_done(wait_background_tasks=True)
    talking.assert_called_once()
    assert hass.states.get(entity_id).state == "idle"


async def test_speaker_stop(hass: HomeAssistant, loaded: MockConfigEntry, camera: FakeCamera) -> None:
    entity_id = _speaker(hass)

    async def forever(*args):
        await asyncio.Event().wait()

    with patch("custom_components.tapo_cameras.media_player.async_talk", side_effect=forever):
        await hass.services.async_call(
            "media_player",
            "play_media",
            {"entity_id": entity_id, "media_content_type": "music", "media_content_id": "http://example.com/a.mp3"},
            blocking=True,
        )
        assert hass.states.get(entity_id).state == "playing"
        await hass.services.async_call("media_player", "media_stop", {"entity_id": entity_id}, blocking=True)
    assert hass.states.get(entity_id).state == "idle"


async def test_speaker_volume(hass: HomeAssistant, loaded: MockConfigEntry, camera: FakeCamera) -> None:
    entity_id = _speaker(hass)
    await hass.services.async_call(
        "media_player", "volume_set", {"entity_id": entity_id, "volume_level": 0.35}, blocking=True
    )
    camera.tapo.setSpeakerVolume.assert_called_once_with(35)
    assert hass.states.get(entity_id).attributes["volume_level"] == 0.35


async def test_speaker_privacy_mode(hass: HomeAssistant, loaded: MockConfigEntry, camera: FakeCamera) -> None:
    loaded.runtime_data.data.set("getLensMaskConfig", ("lens_mask", "lens_mask_info", "enabled"), "on")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "media_player",
            "play_media",
            {
                "entity_id": _speaker(hass),
                "media_content_type": "music",
                "media_content_id": "http://example.com/a.mp3",
            },
            blocking=True,
        )
