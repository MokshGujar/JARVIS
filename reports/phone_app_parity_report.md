# Phone/App Parity Report

Phase: 11

## Status

- Phone/app parity status: improved for background listening, no-speech contract verification, phone contact resolution, pending phone actions, and notification-silent Android foreground service behavior.
- No-beep status: Jarvis-generated listening cues are disabled by default on Android and backend config.
- Exact config default: `JARVIS_PHONE_LISTENING_BEEP=0`.
- Android default: `JarvisPreferences.isListeningCueEnabled()` reads `listening_cue_enabled` with default `false`.

## Implemented

- Added backend feature defaults for phone listening beep, LangGraph agents, Developer Mode, and Agent Mode.
- Gated Android local cue warmup/playback behind `isListeningCueEnabled()`.
- Preserved silent foreground notification behavior with `setSilent(true)`, no channel sound, no vibration.
- Phone call/message commands now use the unified contact resolver when phone contacts are synced.
- STT no-speech behavior remains fail-closed: no chat, thinking TTS, final TTS, or interrupt.

## Platform Limitation

Jarvis code no longer plays passive/background listening cues by default. Android, Google SpeechRecognizer, OEM firmware, or system privacy indicators may still show or produce platform-level microphone indicators/sounds outside Jarvis code.

## Tests

Planned/added:

- `tests/test_phone_app_parity.py`
- `tests/test_phone_command_service.py`
- Existing STT/no-speech endpoint tests in `tests/test_stt_transcribe_endpoint.py`

## Blockers

- WhatsApp and Android live runtime still require manual device validation.
- Platform-forced microphone indicators cannot be suppressed by Jarvis code.
