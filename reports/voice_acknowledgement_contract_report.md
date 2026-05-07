# Voice Acknowledgement Contract Report

Date: 2026-05-07

## Contract

- One canonical thinking acknowledgement payload is registered per turn.
- Thinking display text and thinking TTS text share the same acknowledgement payload and hash.
- Final TTS remains once and end-only.
- No-speech STT must not trigger chat, thinking TTS, final TTS, or interrupt.

## Change

- Added observable fast-response skip logging for thinking TTS:
  `[TTS_THINKING] status=skipped reason=fast_response`.
- No behavior change forces thinking audio for fast responses.
