"""RED tests for ORC-197's generated PCM playback boundary."""

from __future__ import annotations

import struct

import pytest

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
    assert session.dropped_bytes == 2


def test_session_generation_cancels_stale_audio_and_mute_is_silent() -> None:
    session = PcmPlaybackSession(FIXTURE_FORMAT, max_queue_bytes=64)
    generation = session.begin(generate_fixture_pcm(duration_ms=10))
    session.set_muted(True)

    assert session.read(8, generation) == b"\x00" * 8
    assert session.cancel() is True
    assert session.read(8, generation) == b""
    assert session.state is SinkState.CANCELLED


def test_session_progress_uses_processed_bytes_not_elapsed_time() -> None:
    session = PcmPlaybackSession(FIXTURE_FORMAT, max_queue_bytes=64)
    generation = session.begin(b"abcdefgh")
    session.mark_processed(2)

    progress = session.progress(generation)

    assert progress.processed_bytes == 2
    assert progress.queued_bytes == 6
    assert progress.processed_fraction == pytest.approx(0.25)


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


def test_adapter_rejects_calls_from_a_different_thread() -> None:
    device = AudioDeviceInfo("mock", "Mock output", (FIXTURE_FORMAT,))
    adapter = PcmAudioSinkAdapter(lambda: (device,))
    adapter._owner_thread_id = 123  # test-only deterministic thread guard

    with pytest.raises(RuntimeError, match="UI thread"):
        adapter.play(b"data")
