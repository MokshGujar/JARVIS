# Thinking Audio Runtime Report

Last validation update: 2026-05-08.

## Status

Thinking audio and voice turn contracts remain green after the Phases 0-10 changes.

## Behavior Confirmed

- Fast responses skip thinking TTS and log `reason=fast_response`.
- Registered thinking ACK text and TTS hash contract remain intact.
- Duplicate thinking TTS requests skip.
- Final-started turns skip thinking TTS.
- No-speech STT responses do not send chat or trigger thinking audio.
- Final TTS remains end-only in the browser source tests.
- Face-gate greeting is a separate TTS/display path and does not trigger thinking audio.

## Validation Output

```text
python -m pytest -q tests/test_launcher_bootstrap_and_startup.py tests/test_face_gate_launcher_only.py tests/test_thinking_ack_contract.py tests/test_browser_streaming_ux.py tests/test_stt_transcribe_endpoint.py
69 passed, 1 warning in 8.15s
```

```text
python -m pytest -q tests -p no:cacheprovider
697 passed, 424 subtests passed in 58.48s
```

## Blockers

- No new phone-side/background-listening changes were implemented in this run.

