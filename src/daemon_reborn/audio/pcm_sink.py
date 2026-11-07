"""Fail-safe generated PCM playback through a UI-owned Qt audio sink.

The playback session is deliberately Qt-independent so queue, generation, mute,
and progress behavior can be tested with deterministic mock devices. The
adapter is the only layer that knows about Qt Multimedia.
"""

from __future__ import annotations

import math
import struct
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from PySide6.QtCore import QObject, QTimer
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices


@dataclass(frozen=True)
class PcmFormat:
    """Interleaved signed little-endian PCM16 stream format."""

    sample_rate: int
    channels: int
    sample_width_bytes: int = 2

    @property
    def bytes_per_frame(self) -> int:
        return self.channels * self.sample_width_bytes

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.bytes_per_frame


FIXTURE_FORMAT = PcmFormat(sample_rate=24_000, channels=1)


@dataclass(frozen=True)
class AudioDeviceInfo:
    """Small capability snapshot used by both real and deterministic devices."""

    device_id: str
    description: str
    supported_formats: tuple[PcmFormat, ...]
    available: bool = True
    qt_device: Any | None = None


@dataclass(frozen=True)
class FormatSelection:
    format: PcmFormat
    conversion_required: bool


def choose_supported_format(
    device: AudioDeviceInfo, requested: PcmFormat = FIXTURE_FORMAT
) -> FormatSelection:
    """Choose the requested format when possible, otherwise a device format."""

    if requested in device.supported_formats:
        return FormatSelection(requested, False)
    if not device.supported_formats:
        raise ValueError("audio device has no supported PCM formats")
    same_channels = [fmt for fmt in device.supported_formats if fmt.channels == requested.channels]
    selected = min(same_channels or list(device.supported_formats), key=lambda fmt: abs(fmt.sample_rate - requested.sample_rate))
    return FormatSelection(selected, True)


def generate_fixture_pcm(duration_ms: int = 250, sample_rate: int = FIXTURE_FORMAT.sample_rate) -> bytes:
    """Generate a deterministic, non-voice 440 Hz mono PCM16 tone."""

    if duration_ms <= 0 or sample_rate <= 0:
        raise ValueError("duration and sample rate must be positive")
    sample_count = sample_rate * duration_ms // 1000
    return b"".join(
        struct.pack("<h", int(12_000 * math.sin(2 * math.pi * 440 * i / sample_rate)))
        for i in range(sample_count)
    )


def convert_pcm16(data: bytes, source: PcmFormat, target: PcmFormat) -> bytes:
    """Convert PCM16 rate/channels with bounded, deterministic nearest samples."""

    if source.sample_width_bytes != 2 or target.sample_width_bytes != 2:
        raise ValueError("only PCM16 conversion is supported")
    if len(data) % source.bytes_per_frame:
        raise ValueError("PCM data is not frame aligned")
    if source == target:
        return data
    source_frames = [
        struct.unpack_from("<" + "h" * source.channels, data, offset)
        for offset in range(0, len(data), source.bytes_per_frame)
    ]
    target_count = round(len(source_frames) * target.sample_rate / source.sample_rate)
    output = bytearray()
    for target_index in range(target_count):
        source_index = min(len(source_frames) - 1, round(target_index * source.sample_rate / target.sample_rate))
        frame = source_frames[source_index]
        if target.channels == source.channels:
            channels = frame
        elif target.channels == 1:
            channels = (sum(frame) // len(frame),)
        elif source.channels == 1:
            channels = (frame[0],) * target.channels
        else:
            channels = tuple(frame[index % len(frame)] for index in range(target.channels))
        output.extend(struct.pack("<" + "h" * target.channels, *channels))
    return bytes(output)


def enumerate_qt_audio_devices() -> tuple[AudioDeviceInfo, ...]:
    """Snapshot current Qt output devices; callers re-enumerate after changes."""

    devices: list[AudioDeviceInfo] = []
    for device in QMediaDevices.audioOutputs():
        raw_id: Any = device.id()
        formats = tuple(
            PcmFormat(rate, channels)
            for rate in sorted({24_000, 48_000, device.maximumSampleRate()})
            if device.minimumSampleRate() <= rate <= device.maximumSampleRate()
            for channels in sorted({1, 2, device.maximumChannelCount()})
            if device.minimumChannelCount() <= channels <= device.maximumChannelCount()
            and QAudioFormat.SampleFormat.Int16 in device.supportedSampleFormats()
            and device.isFormatSupported(_qt_format(PcmFormat(rate, channels)))
        )
        devices.append(
            AudioDeviceInfo(
                raw_id.data().decode(errors="replace") if raw_id else device.description(),
                device.description(),
                formats,
                qt_device=device,
            )
        )
    return tuple(devices)


def _qt_format(format: PcmFormat) -> QAudioFormat:
    qt_format = QAudioFormat()
    qt_format.setSampleRate(format.sample_rate)
    qt_format.setChannelCount(format.channels)
    qt_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    return qt_format


class SinkState(Enum):
    IDLE = "idle"
    PLAYING = "playing"
    CANCELLED = "cancelled"
    NO_DEVICE = "no-device"
    UNDERRUN = "underrun"
    STOPPED = "stopped"


@dataclass(frozen=True)
class PlaybackProgress:
    generation: int
    processed_bytes: int
    queued_bytes: int
    queued_latency_us: int
    processed_fraction: float


class PcmPlaybackSession:
    """A bounded byte ring with generation and processed-audio accounting."""

    def __init__(self, format: PcmFormat, max_queue_bytes: int = 48_000) -> None:
        if max_queue_bytes < format.bytes_per_frame:
            raise ValueError("queue must hold at least one frame")
        self.format = format
        self.max_queue_bytes = max_queue_bytes - max_queue_bytes % format.bytes_per_frame
        self._queue = bytearray()
        self._total_bytes = 0
        self._processed_bytes = 0
        self._generation = 0
        self._muted = False
        self.state = SinkState.IDLE
        self.dropped_bytes = 0

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def queued_bytes(self) -> int:
        return len(self._queue)

    @property
    def queued_latency_us(self) -> int:
        return self.queued_bytes * 1_000_000 // self.format.bytes_per_second

    def begin(self, data: bytes) -> int:
        self._generation += 1
        self._queue.clear()
        self._processed_bytes = 0
        self._total_bytes = len(data)
        self.dropped_bytes = 0
        self.state = SinkState.PLAYING
        self.enqueue(data)
        return self._generation

    def enqueue(self, data: bytes) -> int:
        capacity = self.max_queue_bytes - len(self._queue)
        accepted = min(len(data), capacity)
        accepted -= accepted % self.format.bytes_per_frame
        self._queue.extend(data[:accepted])
        self.dropped_bytes += len(data) - accepted
        return accepted

    def peek(self, size: int) -> bytes:
        if self._muted:
            return b"\x00" * min(size - size % self.format.bytes_per_frame, len(self._queue))
        return bytes(self._queue[:size])

    def discard(self, size: int) -> int:
        size -= size % self.format.bytes_per_frame
        removed = min(size, len(self._queue))
        del self._queue[:removed]
        return removed

    def prepend(self, data: bytes) -> None:
        self._queue[:0] = data

    def read(self, size: int, generation: int) -> bytes:
        if generation != self._generation or self.state is not SinkState.PLAYING:
            return b""
        data = self.peek(size)
        self.discard(len(data))
        return data

    def mark_processed(self, count: int) -> None:
        self.discard(count)
        self._processed_bytes = min(self._total_bytes, self._processed_bytes + count)
        if self._processed_bytes >= self._total_bytes and not self._queue:
            self.state = SinkState.IDLE

    def set_muted(self, muted: bool) -> None:
        self._muted = muted

    def cancel(self) -> bool:
        was_active = self.state is SinkState.PLAYING
        self._queue.clear()
        self.state = SinkState.CANCELLED
        return was_active

    def progress(self, generation: int | None = None) -> PlaybackProgress:
        return PlaybackProgress(
            generation=self._generation if generation is None else generation,
            processed_bytes=self._processed_bytes,
            queued_bytes=len(self._queue),
            queued_latency_us=self.queued_latency_us,
            processed_fraction=(self._processed_bytes / self._total_bytes if self._total_bytes else 1.0),
        )


class PcmAudioSinkAdapter(QObject):
    """UI-thread-owned adapter; Qt sink creation is deferred until a device exists."""

    def __init__(
        self, device_provider: Callable[[], Iterable[AudioDeviceInfo]] | None = None
    ) -> None:
        super().__init__()
        self._device_provider = device_provider or enumerate_qt_audio_devices
        self._owner_thread_id = threading.get_ident()
        self._session: PcmPlaybackSession | None = None
        self._device: AudioDeviceInfo | None = None
        self._sink_writer: Callable[[bytes], int] | None = None
        self._qt_sink: QAudioSink | None = None
        self._qt_io: Any | None = None
        self._pump_timer = QTimer(self)
        self._pump_timer.setInterval(10)
        self._pump_timer.timeout.connect(self.pump)
        self._generation_counter = 0
        self._muted = False
        self.state = SinkState.IDLE
        self._media_devices = QMediaDevices(self)
        self._media_devices.audioOutputsChanged.connect(self.on_audio_outputs_changed)

    @property
    def queued_bytes(self) -> int:
        return self._session.queued_bytes if self._session else 0

    def _assert_ui_thread(self) -> None:
        if threading.get_ident() != self._owner_thread_id:
            raise RuntimeError("audio sink must be used from the UI thread")

    def play(self, data: bytes) -> PlaybackResult:
        self._assert_ui_thread()
        if not data or len(data) % FIXTURE_FORMAT.bytes_per_frame:
            return PlaybackResult(False, self._session.generation + 1 if self._session else 1, "invalid-pcm")
        devices = [device for device in self._device_provider() if device.available]
        if not devices:
            self.state = SinkState.NO_DEVICE
            return PlaybackResult(False, 0, "no-output-device")
        selection = choose_supported_format(devices[0])
        converted = convert_pcm16(data, FIXTURE_FORMAT, selection.format)
        self._device = devices[0]
        self._session = PcmPlaybackSession(selection.format)
        self._generation_counter += 1
        self._session.begin(converted)
        self._session._generation = self._generation_counter
        self._session.set_muted(self._muted)
        generation = self._generation_counter
        if self._sink_writer is None and devices[0].qt_device is not None:
            try:
                self._qt_sink = QAudioSink(devices[0].qt_device, _qt_format(selection.format), self)
                self._qt_sink.stateChanged.connect(self._on_qt_state_changed)
                qt_io = self._qt_sink.start()
                self._qt_io = qt_io
                if qt_io is None:
                    self._session.cancel()
                    self.state = SinkState.STOPPED
                    return PlaybackResult(False, generation, "sink-open-failed")
                self._sink_writer = lambda payload: int(qt_io.write(payload))
                self._pump_timer.start()
            except (RuntimeError, TypeError, ValueError):
                self._session.cancel()
                self.state = SinkState.STOPPED
                return PlaybackResult(False, generation, "sink-open-failed")
        self.state = SinkState.PLAYING
        return PlaybackResult(True, generation, None)

    def _on_qt_state_changed(self, state: Any) -> None:
        if self._session is None:
            return
        if state == QAudio.State.IdleState and self._session.queued_bytes:
            self.state = SinkState.UNDERRUN
        elif state == QAudio.State.StoppedState:
            self.state = SinkState.STOPPED

    def feed(self, generation: int, data: bytes) -> int:
        self._assert_ui_thread()
        if self._session is None or generation != self._session.generation:
            return 0
        return self._session.enqueue(data)

    def set_sink_writer(self, writer: Callable[[bytes], int]) -> None:
        self._assert_ui_thread()
        self._sink_writer = writer

    def pump(self) -> int:
        self._assert_ui_thread()
        if self._session is None or self._sink_writer is None:
            return 0
        payload = self._session.peek(min(self._session.queued_bytes, 4_096))
        if not payload:
            self.state = SinkState.UNDERRUN if self.state is SinkState.PLAYING else self.state
            return 0
        written = max(0, min(len(payload), self._sink_writer(payload)))
        self._session.mark_processed(written)
        if written < len(payload):
            self.state = SinkState.PLAYING
        return written

    def set_muted(self, muted: bool) -> None:
        self._assert_ui_thread()
        self._muted = muted
        if self._session:
            self._session.set_muted(muted)

    def progress(self, generation: int | None = None) -> PlaybackProgress:
        self._assert_ui_thread()
        if self._session is None:
            return PlaybackProgress(generation or 0, 0, 0, 0, 1.0)
        return self._session.progress(generation)

    def on_audio_outputs_changed(self) -> None:
        self._assert_ui_thread()
        current_ids = {device.device_id for device in self._device_provider() if device.available}
        if self._device is None or self._device.device_id not in current_ids:
            if self._session:
                self._session.cancel()
            self.state = SinkState.NO_DEVICE

    def stop(self) -> None:
        self._assert_ui_thread()
        self._pump_timer.stop()
        if self._qt_sink is not None:
            self._qt_sink.reset()
            self._qt_sink = None
            self._qt_io = None
        if self._session:
            self._session.cancel()
        self.state = SinkState.STOPPED


@dataclass(frozen=True)
class PlaybackResult:
    started: bool
    generation: int
    reason: str | None
