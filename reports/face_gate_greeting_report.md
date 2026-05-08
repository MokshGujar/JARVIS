# Face Gate Greeting Report

Last validation update: 2026-05-08.

## Status

Face-gate greeting is implemented for the launcher-authenticated app entry path.

## Behavior

- Greeting only starts after `/auth/launcher/exchange-bootstrap` succeeds with a face session id.
- Greeting text: `Welcome back, Moksh. JARVIS is online.`
- Fallback behavior is display-only if TTS is unavailable.
- Greeting is guarded by `sessionStorage` and runs once per app session.
- Main app still does not perform in-app face verify or step-up face routes.
- Greeting does not use thinking audio.

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

- Real TTS playback still depends on the browser audio/TTS runtime being available.

