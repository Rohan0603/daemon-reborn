from __future__ import annotations

from pathlib import Path

import pytest

from daemon_reborn.voice.chatterbox_nano import (
    MODEL_REVISION,
    ChatterboxNanoSynthesizer,
    NanoConfig,
    NanoUnavailable,
)


def test_missing_checkpoint_fails_closed_without_importing_model() -> None:
    worker = ChatterboxNanoSynthesizer(NanoConfig(Path("missing-checkpoint")))

    with pytest.raises(NanoUnavailable, match="checkpoint directory is missing"):
        worker.load()


def test_approved_revision_is_pinned() -> None:
    config = NanoConfig(Path("checkpoint"))

    assert config.revision == MODEL_REVISION
    assert config.device == "cpu"


def test_empty_text_is_rejected_before_model_load(tmp_path: Path) -> None:
    worker = ChatterboxNanoSynthesizer(NanoConfig(tmp_path))

    with pytest.raises(ValueError, match="must not be empty"):
        worker.synthesize("   ")
