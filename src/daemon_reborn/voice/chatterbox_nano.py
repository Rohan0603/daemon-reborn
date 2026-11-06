"""Optional, offline-first Chatterbox-Nano worker boundary.

The desktop shell must remain usable without the model or its heavyweight
dependencies.  This module therefore imports Chatterbox lazily and only loads
an explicitly supplied local checkpoint; it never downloads at application
startup.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

MODEL_REPOSITORY = "ResembleAI/chatterbox-nano"
MODEL_REVISION = "71ccd1d0081b430592cea481f4307e764e07bc64"


class NanoUnavailable(RuntimeError):
    """Raised when Nano is not installed or its local checkpoint is absent."""


@dataclass(frozen=True, slots=True)
class NanoConfig:
    """Explicit local Nano configuration; no network fallback is permitted."""

    model_dir: Path
    device: str = "cpu"
    revision: str = MODEL_REVISION


class ChatterboxNanoSynthesizer:
    """Lazy Nano loader and synthesizer for a separate worker process."""

    def __init__(self, config: NanoConfig) -> None:
        self.config = config
        self._model: Any | None = None

    def load(self) -> None:
        if self._model is not None:
            return
        if not self.config.model_dir.is_dir():
            raise NanoUnavailable(f"Nano checkpoint directory is missing: {self.config.model_dir}")
        try:
            from chatterbox.tts_turbo import ChatterboxTurboTTS  # type: ignore[import-not-found]
        except ImportError as exc:
            raise NanoUnavailable(
                "Chatterbox-Nano dependencies are not installed; speech remains disabled"
            ) from exc
        try:
            self._model = ChatterboxTurboTTS.from_local(
                self.config.model_dir,
                device=self.config.device,
                nano=True,
            )
        except Exception as exc:  # provider errors become an honest fallback state
            raise NanoUnavailable(f"Nano checkpoint could not be loaded: {exc}") from exc

    def synthesize(self, text: str) -> tuple[Any, int]:
        """Return a watermarked waveform and sample rate from the local model."""
        if not text.strip():
            raise ValueError("speech text must not be empty")
        self.load()
        assert self._model is not None
        try:
            waveform = self._model.generate(text)
            return waveform, int(self._model.sr)
        except Exception as exc:
            raise NanoUnavailable(f"Nano synthesis failed: {exc}") from exc


__all__ = [
    "MODEL_REPOSITORY",
    "MODEL_REVISION",
    "ChatterboxNanoSynthesizer",
    "NanoConfig",
    "NanoUnavailable",
]
