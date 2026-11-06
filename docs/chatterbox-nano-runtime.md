# Chatterbox-Nano runtime

The Nano speech path is optional and offline-first. The desktop shell does not
download model files or import the heavyweight Chatterbox package at startup.
`daemon_reborn.voice.ChatterboxNanoSynthesizer` is the worker boundary: supply
an explicit local checkpoint directory and handle `NanoUnavailable` as the
honest speech-disabled state.

## Pinned artifacts

- Repository: `ResembleAI/chatterbox-nano`
- Model revision: `71ccd1d0081b430592cea481f4307e764e07bc64`
- Runtime source: upstream Chatterbox commit `ab55923c27757c90cfcc407baa57dc25a7d25217`
- License evidence: Chatterbox-Nano is distributed under MIT terms; retain the
  model and runtime license files beside the offline cache.

The model cache must be provisioned before launch. Provisioning is an
installation/release step, not an application startup side effect. A worker can
be configured as follows:

```python
from pathlib import Path

from daemon_reborn.voice import ChatterboxNanoSynthesizer, NanoConfig

synthesizer = ChatterboxNanoSynthesizer(
    NanoConfig(
        model_dir=Path(r"C:\\ProgramData\\DaemonReborn\\models\\chatterbox-nano"),
        device="cpu",  # use "cuda" only after device qualification
    )
)
waveform, sample_rate = synthesizer.synthesize("Hello from Daemon Reborn.")
```

The runtime intentionally does not call `from_pretrained`, does not contact
Hugging Face, and does not silently substitute Turbo for Nano. Missing
dependencies, missing checkpoints, load failures, and synthesis failures raise
`NanoUnavailable`, allowing the caller to keep the rest of the application
usable and report speech as unavailable.

Linear evidence: ORC-193 implementation and ORC-164 qualification.

## Qualification boundary

The Windows CPU/offline qualification recorded successful local load,
synthesis, Perth watermark detection, and offline-cache reload for the pinned
revision. CUDA qualification requires an NVIDIA/CUDA host and is not inferred
from CPU success. Reference-audio/voice-cloning qualification requires an
authorized WAV provenance record and is separate from the synthetic English
smoke sentence.
