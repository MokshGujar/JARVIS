# STT Provider Migration

## Current Provider Status

- `STTTool` remains the public tool wrapper for transcription.
- `STT_PROVIDER=none` stays safe and disabled.
- `STT_PROVIDER=fake` remains test-only/local deterministic behavior.
- `STT_PROVIDER=nemo_parakeet` is the preferred and only local model-backed STT provider.
- `requirements.txt` now includes `nemo_toolkit[asr]`; CUDA-enabled PyTorch installation still needs to match the target GPU environment.
- The legacy `local_whisper` provider path has been removed after Parakeet mocked tests and manual smoke testing passed.

## Parakeet Status

- Preferred model: `nvidia/parakeet-tdt-0.6b-v2`.
- Provider module: `app/adapters/providers/nemo_parakeet_provider.py`.
- Unit tests mock model loading and transcription.
- Readiness does not load the model, download a model, or transcribe audio.
- WAV is required by default through `PARAKEET_REQUIRE_WAV=true` because earlier `.m4a` input failed through the Lhotse/torchaudio path.
- Post-processing is conservative: trim text and normalize repeated whitespace.
- Domain correction is enabled by default and only applies explicit configured replacements, such as `Jaris=Jarvis` and `Javier=Jarvis`.
- Startup warmup is enabled by default for the Jarvis voice profile: `PARAKEET_PRELOAD_ON_STARTUP=true` and `STT_WARMUP_ON_STARTUP=true`. Backend startup is slower, but the first voice command should use the cached model.
- To restore lazy loading, set `PARAKEET_PRELOAD_ON_STARTUP=false` and `STT_WARMUP_ON_STARTUP=false`.
- Manual GPU verification succeeded with PyTorch CUDA on RTX 3060 Laptop GPU. Example output included: `Hello. This is a test for checking if the whisper stt is working or not. This is for Jaris. Hello Jarvis, how are you. This is a new speech to text provider.`
- Known limitation: Parakeet also misrecognized one `Jarvis` occurrence as `Jaris`; do not treat output as perfect transcription.

## Removed Legacy Provider

- `LocalWhisperProvider` was removed from production factory selection.
- The local Whisper manual smoke script and provider-specific unit tests were removed.
- The external package dependency for the removed provider was deleted from `requirements.txt`.
- `STT_PROVIDER=local_whisper` now reports `unsupported_stt_provider` and builds a disabled provider.

## Manual Smoke Test

```powershell
$env:STT_PROVIDER="nemo_parakeet"
$env:PARAKEET_MODEL="nvidia/parakeet-tdt-0.6b-v2"
$env:PARAKEET_DEVICE="cuda"
$env:PARAKEET_COMPUTE_TYPE="float16"
python scripts\manual_test_nemo_parakeet_stt.py "C:\path\to\audio.wav"
```

## Active STT Providers

1. `none`
2. `fake`
3. `nemo_parakeet`
