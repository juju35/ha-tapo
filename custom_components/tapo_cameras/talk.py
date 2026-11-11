"""Talk: audio played on the camera's speaker, over its media port (8800).

The camera takes G.711 A-law, 8 kHz mono, in an MPEG transport stream with its own stream type
for A-law (0x90), sent in a "talk" session of the same multipart connection its live view uses.
The audio comes from FFmpeg (any file, URL, or text-to-speech result Home Assistant can read),
paced in real time so that the camera's buffer neither runs dry nor overflows.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from time import monotonic
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pytapo.media_stream.session import HttpMediaSession

_LOGGER = logging.getLogger(__name__)

SAMPLE_RATE = 8000
# A-law: one byte per sample. 40 ms per packet, as the camera's own audio.
FRAME_BYTES = 320
FRAME_SECONDS = FRAME_BYTES / SAMPLE_RATE
# Sent ahead of real time, so that a late wake-up of the event loop doesn't make the audio stutter.
LEAD = 0.25
# Talk modes, in the order tried: echo cancellation (cameras with it), then half duplex.
TALK_MODES = ("aec", "half_duplex")
TALK_MIMETYPE = "audio/mp2t"
# Seconds to wait for the camera to open the talk session.
OPEN_TIMEOUT = 10.0

# MPEG-TS.
TS_SIZE = 188
PID_PAT = 0x0000
PID_PMT = 0x1000
PID_AUDIO = 0x0100
STREAM_TYPE_PCMA_TAPO = 0x90
STREAM_ID_AUDIO = 0xC0


def _crc32_mpeg(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) if crc & 0x80000000 else crc << 1
            crc &= 0xFFFFFFFF
    return crc


def _section(table: bytes) -> bytes:
    """A PSI section (pointer field, table, CRC) padded to one TS payload."""
    body = table + _crc32_mpeg(table).to_bytes(4, "big")
    return (b"\x00" + body).ljust(TS_SIZE - 4, b"\xff")


def _pat() -> bytes:
    # table_id 0, section_syntax 1, length 13; transport_stream_id 1; version 0, current; program 1 → PMT PID.
    return _section(
        bytes([0x00, 0xB0, 0x0D, 0x00, 0x01, 0xC1, 0x00, 0x00, 0x00, 0x01]) + (0xE000 | PID_PMT).to_bytes(2, "big")
    )


def _pmt() -> bytes:
    # table_id 2, length 18; program 1; PCR on the audio PID; no program info; one A-law stream.
    return _section(
        bytes([0x02, 0xB0, 0x12, 0x00, 0x01, 0xC1, 0x00, 0x00])
        + (0xE000 | PID_AUDIO).to_bytes(2, "big")
        + b"\xf0\x00"
        + bytes([STREAM_TYPE_PCMA_TAPO])
        + (0xE000 | PID_AUDIO).to_bytes(2, "big")
        + b"\xf0\x00"
    )


def _pts(pts: int) -> bytes:
    """A 33-bit, 90 kHz timestamp in the 5-byte PES format (PTS only)."""
    pts &= (1 << 33) - 1
    return bytes(
        [
            0x21 | ((pts >> 29) & 0x0E),
            (pts >> 22) & 0xFF,
            0x01 | ((pts >> 14) & 0xFE),
            (pts >> 7) & 0xFF,
            0x01 | ((pts << 1) & 0xFE),
        ]
    )


class TsMuxer:
    """A-law frames → MPEG-TS packets, with the continuity counters of each PID."""

    def __init__(self) -> None:
        self._counters: dict[int, int] = {}

    def _packet(self, pid: int, payload: bytes, start: bool) -> bytes:
        counter = self._counters.get(pid, 0)
        self._counters[pid] = (counter + 1) & 0x0F
        header = bytes([0x47, (0x40 if start else 0x00) | (pid >> 8), pid & 0xFF])
        room = TS_SIZE - 4
        if len(payload) >= room:
            return header + bytes([0x10 | counter]) + payload[:room]
        # Short last packet: stuffing in an adaptation field.
        stuffing = room - len(payload) - 1
        adaptation = bytes([stuffing]) + (bytes([0x00]) + b"\xff" * (stuffing - 1) if stuffing else b"")
        return header + bytes([0x30 | counter]) + adaptation + payload

    def tables(self) -> bytes:
        return self._packet(PID_PAT, _pat(), True) + self._packet(PID_PMT, _pmt(), True)

    def frame(self, alaw: bytes, pts: int) -> bytes:
        """One PES packet of A-law samples, split into TS packets."""
        header = b"\x80\x80\x05" + _pts(pts)  # marker bits, PTS only, 5 bytes of header data
        pes_length = len(header) + len(alaw)
        pes = b"\x00\x00\x01" + bytes([STREAM_ID_AUDIO]) + pes_length.to_bytes(2, "big") + header + alaw
        room = TS_SIZE - 4
        return b"".join(
            self._packet(PID_AUDIO, pes[offset : offset + room], offset == 0) for offset in range(0, len(pes), room)
        )


async def _alaw_frames(ffmpeg: str, source: str) -> AsyncIterator[bytes]:
    """The source decoded by FFmpeg to A-law, 8 kHz mono, in FRAME_BYTES frames."""
    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        source,
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "alaw",
        "-",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None
    try:
        while frame := await process.stdout.readexactly(FRAME_BYTES):
            yield frame
    except asyncio.IncompleteReadError as end:
        if end.partial:
            # Pad the last frame with A-law silence (0xD5).
            yield end.partial.ljust(FRAME_BYTES, b"\xd5")
    finally:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
        stderr = await process.stderr.read() if process.stderr else b""
        await process.wait()
        if process.returncode not in (0, None, -9) and stderr:
            _LOGGER.warning("FFmpeg could not read %s: %s", source, stderr.decode(errors="replace").strip())


class TalkError(Exception):
    """The camera refused or dropped the talk session."""


async def _send(session: HttpMediaSession, talk_session: int, data: bytes) -> None:
    """One multipart part of audio in the talk session (the library only sends requests)."""
    encrypt = session._aes is not None  # noqa: SLF001 - the library has no API to send audio
    if encrypt:
        data = session._aes.encrypt(data)  # noqa: SLF001
    headers = {
        b"Content-Type": TALK_MIMETYPE.encode(),
        b"X-If-Encrypt": b"1" if encrypt else b"0",
        b"X-Session-Id": str(talk_session).encode(),
        b"Content-Length": str(len(data)).encode(),
    }
    await session._send_http_request(b"--" + session.client_boundary, headers)  # noqa: SLF001
    writer = session._writer  # noqa: SLF001
    writer.write(data + b"\r\n")
    await writer.drain()


async def _open(session: HttpMediaSession) -> tuple[AsyncIterator[Any], int]:
    """A talk session: the camera's answers, and the session ID audio goes to."""
    code: Any = None
    for mode in TALK_MODES:
        request = {"type": "request", "seq": 1, "params": {"talk": {"mode": mode}, "method": "get"}}
        responses = session.transceive(json.dumps(request), no_data_timeout=None)
        try:
            first = await asyncio.wait_for(anext(responses), OPEN_TIMEOUT)
        except (TimeoutError, StopAsyncIteration) as err:
            await responses.aclose()
            raise TalkError("the camera did not open a talk session") from err
        answer: Any = first.json_data or {}
        code = (answer.get("params") or {}).get("error_code", answer.get("error_code", 0))
        if first.session is not None and code in (0, None):
            _LOGGER.debug("Talk session %s open in mode %s", first.session, mode)
            return responses, first.session
        await responses.aclose()
    raise TalkError(f"the camera refused to talk (error {code})")


async def async_talk(session: HttpMediaSession, ffmpeg: str, source: str) -> float:
    """Play `source` on the camera's speaker; returns the seconds played."""
    async with session:
        responses, talk_session = await _open(session)

        # The camera keeps answering in the talk session: read its answers, or its queue fills up.
        async def drain() -> None:
            async for _ in responses:
                pass

        drainer = asyncio.create_task(drain())
        muxer = TsMuxer()
        started, sent = monotonic(), 0
        try:
            async for frame in _alaw_frames(ffmpeg, source):
                pts = round(sent * FRAME_SECONDS * 90000)
                packet = (muxer.tables() if sent % 25 == 0 else b"") + muxer.frame(frame, pts)
                await _send(session, talk_session, packet)
                sent += 1
                if (ahead := started + sent * FRAME_SECONDS - monotonic() - LEAD) > 0:
                    await asyncio.sleep(ahead)
            # Let the camera play what is buffered before the session closes.
            if (rest := started + sent * FRAME_SECONDS - monotonic()) > 0:
                await asyncio.sleep(rest)
        finally:
            drainer.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await drainer
            await responses.aclose()
        return sent * FRAME_SECONDS
