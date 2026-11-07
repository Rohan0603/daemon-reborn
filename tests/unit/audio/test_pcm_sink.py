"""RED tests for ORC-197's generated PCM playback boundary."""

from __future__ import annotations

import struct

import pytest
from PySide6.QtMultimedia import QAudio

from daemon_reborn.audio.pcm_sink import (
    FIXTURE_FORMAT,
    AudioDeviceInfo,
    PcmAudioSinkAdapter,
    PcmFormat,
    PcmPlaybackSession,
    SinkState,
    choose_supported_format,
    generate_fixture_pcm,
)


def test_fixture_is_deterministic_24khz_mono_pcm16() -> None:
    first = generate_fixture_pcm(duration_ms=10)
    second = generate_fixture_pcm(duration_ms=10)

    assert first == second
    assert len(first) == 24_000 * 10 // 1000 * 2
    assert struct.unpack_from("<h", first)[0] == 0


def test_supported_format_prefers_native_fixture_format() -> None:
    device = AudioDeviceInfo("mock", "Mock output", (FIXTURE_FORMAT,))

    selection = choose_supported_format(device)

    assert selection.format == FIXTURE_FORMAT
    assert not selection.conversion_required


def test_supported_format_reports_mismatch_and_selects_device_format() -> None:
    device_format = PcmFormat(sample_rate=48_000, channels=2)
    device = AudioDeviceInfo("mock", "Mock output", (device_format,))

    selection = choose_supported_format(device)

    assert selection.format == device_format
    assert selection.conversion_required


def test_session_bounds_queue_and_reports_queued_latency() -> None:
    session = PcmPlaybackSession(FIXTURE_FORMAT, max_queue_bytes=8)

    accepted = session.enqueue(b"1234567890")

    assert accepted == 8
    assert session.queued_bytes == 8
    assert session.queued_latency_us == 8 * 1_000_000 // FIXTURE_FORMAT.bytes_per_second
    assert session.dropped_bytes == 0


def test_session_generation_cancels_stale_audio_and_mute_is_silent() -> None:
    session = PcmPlaybackSession(FIXTURE_FORMAT, max_queue_bytes=64)
    generation = session.begin(generate_fixture_pcm(duration_ms=10))
    session.set_muted(True)

    assert session.read(8, generation) == b"\x00" * 8
    assert session.cancel() is True
    assert session.read(8, generation) == b""
    assert session.state is SinkState.CANCELLED
    assert session.generation != generation


def test_cancelled_adapter_rejects_feed_from_invalidated_generation() -> None:
    device = AudioDeviceInfo("mock", "Mock output", (FIXTURE_FORMAT,))
    adapter = PcmAudioSinkAdapter(lambda: (device,))
    result = adapter.play(b"abcdefgh")

    adapter.stop()

    assert adapter.feed(result.generation, b"stale") == 0


@pytest.mark.parametrize(
    ("replacement", "reason"),
    [(b"bad", "invalid-pcm"), (None, "no-output-device")],
)
def test_failed_replacement_invalidates_previous_generation(
    replacement: bytes | None, reason: str
) -> None:
    devices = [AudioDeviceInfo("mock", "Mock output", (FIXTURE_FORMAT,))]
    adapter = PcmAudioSinkAdapter(lambda: tuple(devices))
    adapter.set_sink_writer(lambda data: len(data))
    first = adapter.play(b"abcdefgh")
    if replacement is None:
        devices.clear()
        replacement_data = generate_fixture_pcm(duration_ms=10)
    else:
        replacement_data = replacement

    failed = adapter.play(replacement_data)

    assert not failed.started
    assert failed.reason == reason
    assert failed.generation > first.generation
    assert adapter.feed(first.generation, b"stale") == 0


def test_qt_stopped_state_cleans_session_and_rebinds_active_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeIo:
        def write(self, payload: bytes) -> int:
            return len(payload)

    class FakeSignal:
        def connect(self, callback: object) -> None:
            return None

    class FakeSink:
        def __init__(self, _device: object, _format: object, _parent: object) -> None:
            self.stateChanged = FakeSignal()

        def start(self) -> FakeIo:
            return FakeIo()

        def processedUSecs(self) -> int:
            return 0

        def reset(self) -> None:
            return None

    monkeypatch.setattr("daemon_reborn.audio.pcm_sink.QAudioSink", FakeSink)
    device = AudioDeviceInfo("mock", "Mock output", (FIXTURE_FORMAT,), qt_device="mock")
    adapter = PcmAudioSinkAdapter(lambda: (device,))
    first = adapter.play(b"abcdefgh")

    adapter._on_qt_state_changed(QAudio.State.StoppedState)

    stopped_state = adapter.state
    assert stopped_state is SinkState.STOPPED
    assert adapter._session is None
    assert adapter.feed(first.generation, b"stale") == 0

    adapter.on_audio_outputs_changed()

    assert adapter.state is SinkState.PLAYING
    assert adapter._session is not None
    assert adapter._session.generation > first.generation


def test_session_progress_uses_processed_bytes_not_elapsed_time() -> None:
    session = PcmPlaybackSession(FIXTURE_FORMAT, max_queue_bytes=64)
    generation = session.begin(b"abcdefgh")
    session.mark_processed(2)

    progress = session.progress(generation)

    assert progress.processed_bytes == 2
    assert progress.queued_bytes == 6
    assert progress.processed_fraction == pytest.approx(0.25)


def test_session_separates_submitted_from_qt_processed_clock() -> None:
    session = PcmPlaybackSession(FIXTURE_FORMAT, max_queue_bytes=8)
    generation = session.begin(b"abcdefghijklmnop")
    assert session.mark_submitted(8) == 8

    session.update_processed_usecs(8 * 1_000_000 // FIXTURE_FORMAT.bytes_per_second)
    progress = session.progress(generation)

    assert progress.submitted_bytes == 8
    assert progress.processed_bytes == 8
    assert progress.queued_bytes == 8


def test_large_playback_is_chunked_without_dropping_and_reaches_completion() -> None:
    device = AudioDeviceInfo("mock", "Mock output", (FIXTURE_FORMAT,))
    adapter = PcmAudioSinkAdapter(lambda: (device,))
    adapter.set_sink_writer(lambda data: len(data))
    result = adapter.play(b"a" * 100_000)

    for _ in range(100):
        adapter.pump()
        if adapter.state is SinkState.IDLE:
            break

    assert result.started
    assert adapter.progress(result.generation).processed_bytes == 100_000
    assert adapter.state is SinkState.IDLE


def test_adapter_fails_safe_without_output_device() -> None:
    adapter = PcmAudioSinkAdapter(lambda: ())

    result = adapter.play(generate_fixture_pcm(duration_ms=10))

    assert not result.started
    assert result.reason == "no-output-device"


def test_adapter_ignores_stale_generation_after_restart() -> None:
    device = AudioDeviceInfo("mock", "Mock output", (FIXTURE_FORMAT,))
    adapter = PcmAudioSinkAdapter(lambda: (device,))

    first = adapter.play(b"first!")
    second = adapter.play(b"second")

    assert second.generation > first.generation
    assert adapter.feed(first.generation, b"stale") == 0
    assert adapter.feed(second.generation, b"fresh!") == len(b"fresh!")


def test_adapter_handles_partial_sink_writes_without_losing_unwritten_bytes() -> None:
    device = AudioDeviceInfo("mock", "Mock output", (FIXTURE_FORMAT,))
    adapter = PcmAudioSinkAdapter(lambda: (device,))
    result = adapter.play(b"abcdefgh")
    adapter.set_sink_writer(lambda data: min(2, len(data)))

    written = adapter.pump()

    assert result.started
    assert written == 2
    assert adapter.queued_bytes == 6


def test_adapter_mute_applies_before_playback_starts() -> None:
    device = AudioDeviceInfo("mock", "Mock output", (FIXTURE_FORMAT,))
    adapter = PcmAudioSinkAdapter(lambda: (device,))
    adapter.set_muted(True)
    adapter.play(b"abcdefgh")
    captured: list[bytes] = []

    def capture(data: bytes) -> int:
        captured.append(data)
        return len(data)

    adapter.set_sink_writer(capture)

    adapter.pump()

    assert captured == [b"\x00" * 8]


def test_adapter_recovery_reenumerates_devices_and_stops_when_removed() -> None:
    devices = [AudioDeviceInfo("mock", "Mock output", (FIXTURE_FORMAT,))]
    adapter = PcmAudioSinkAdapter(lambda: tuple(devices))
    result = adapter.play(b"abcdefgh")
    devices.clear()

    adapter.on_audio_outputs_changed()

    assert result.started
    assert adapter.state is SinkState.NO_DEVICE


def test_adapter_rebinds_after_device_loss_when_output_returns() -> None:
    devices = [AudioDeviceInfo("one", "First", (FIXTURE_FORMAT,))]
    adapter = PcmAudioSinkAdapter(lambda: tuple(devices))
    adapter.set_sink_writer(lambda data: len(data))
    result = adapter.play(b"abcdefgh")
    devices.clear()
    adapter.on_audio_outputs_changed()

    devices.append(AudioDeviceInfo("two", "Second", (FIXTURE_FORMAT,)))
    adapter.on_audio_outputs_changed()

    assert adapter.state is SinkState.PLAYING
    assert adapter._device is not None
    assert adapter._device.device_id == "two"
    assert adapter.feed(result.generation, b"stale") == 0


def test_adapter_tries_supported_devices_until_one_opens(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[str] = []

    class FakeIo:
        def write(self, payload: bytes) -> int:
            return len(payload)

    class FakeSink:
        def __init__(self, device: object, _format: object, _parent: object) -> None:
            attempts.append(str(device))
            if device == "bad":
                raise RuntimeError("cannot open")
            self.stateChanged = type("Signal", (), {"connect": lambda *_args: None})()

        def start(self) -> FakeIo:
            return FakeIo()

        def processedUSecs(self) -> int:
            return 0

        def reset(self) -> None:
            return None

    monkeypatch.setattr("daemon_reborn.audio.pcm_sink.QAudioSink", FakeSink)
    devices = (
        AudioDeviceInfo("bad", "Bad", (FIXTURE_FORMAT,), qt_device="bad"),
        AudioDeviceInfo("good", "Good", (FIXTURE_FORMAT,), qt_device="good"),
    )
    adapter = PcmAudioSinkAdapter(lambda: devices)

    result = adapter.play(b"abcdefgh")

    assert result.started
    assert attempts == ["bad", "good"]
    assert adapter._device is not None and adapter._device.device_id == "good"


def test_adapter_reports_controlled_failure_when_all_devices_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSink:
        def __init__(self, _device: object, _format: object, _parent: object) -> None:
            raise RuntimeError("cannot open")

    monkeypatch.setattr("daemon_reborn.audio.pcm_sink.QAudioSink", FakeSink)
    devices = (AudioDeviceInfo("bad", "Bad", (FIXTURE_FORMAT,), qt_device="bad"),)
    adapter = PcmAudioSinkAdapter(lambda: devices)

    result = adapter.play(b"abcdefgh")

    assert not result.started
    assert result.reason == "sink-open-failed"
    assert adapter.state is SinkState.STOPPED


def test_adapter_rejects_calls_from_a_different_thread() -> None:
    device = AudioDeviceInfo("mock", "Mock output", (FIXTURE_FORMAT,))
    adapter = PcmAudioSinkAdapter(lambda: (device,))
    adapter._owner_thread_id = 123  # test-only deterministic thread guard

    with pytest.raises(RuntimeError, match="UI thread"):
        adapter.play(b"data")
