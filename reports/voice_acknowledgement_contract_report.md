# Voice Acknowledgement Contract Report

Date: 2026-05-06

## Contract

- Thinking display text and thinking TTS now come from one canonical acknowledgement payload per turn.
- Payloads are turn-bound and hash-bound with `turn_id`, `text`, `tts_text`, `text_hash`, `created_at`, and `expires_at`.
- `text` and `tts_text` are identical by default. Any future difference must be pronunciation-only and must not change meaning.

## Protections

- `/tts/thinking` skips stale, duplicate, interrupted, expired, no-speech, final-started, and final-completed turns.
- Frontend turn handling ignores stale or hash-mismatched thinking audio responses.
- Thinking audio does not play for no-speech turns or fast semantic commands that complete before the thinking delay.
- Final TTS remains end-only and once per turn.

## Verification

- `tests/test_thinking_ack_contract.py` covers canonical payload creation, hash matching, stale/duplicate/final-started skips, no-speech behavior, and final TTS once semantics.
- Existing voice/audio state-machine tests remain part of the final suite.

## Remaining Risk

- No known mismatch path remains. Future frontend changes should continue to use the acknowledgement payload rather than choosing independent thinking phrases.
