# TaskPlanner Deterministic Pattern Roadmap

This roadmap documents future deterministic planning patterns only. It is not an implementation list for the current phase.

## File
- Create, write, append, verify, read, list, search, rename, move, and delete with explicit safe-path handling.
- Multi-file workflows such as find files, summarize matches, then open or move selected results.

## App/Window
- Open, focus, close with confirmation where unsaved-work risk exists.
- Window positioning, switching, minimize/maximize, and app-specific follow-up actions.

## Browser
- Open site, search, navigate, extract text, summarize page, and download-safe workflows.
- Form entry remains gated and must not submit sensitive data without confirmation.

## System
- Volume, brightness, screenshot, safe system info, lock, shutdown, restart, sleep, and settings flows.
- Critical power actions remain confirmation plus fresh face step-up candidates.

## WhatsApp/Message
- Open WhatsApp, resolve contact, prepare message, confirm, send, call, video call, and end call.
- External communication must keep confirmation and no-fake-success behavior.

## Voice/Audio
- Start listening, transcribe, summarize spoken notes, speak response, and control audio devices.
- Voice or face identity checks remain security services, not ordinary tools.

## Memory/Reminder
- Remember facts, retrieve prior context, create reminders, update reminders, and explain reminder status.
- Follow-up resolution needs session scoping and expiry.

## Research/Summary
- Search, collect sources, summarize, compare, and produce citations where available.
- Missing or failed sources should return partial results rather than fabricated summaries.

## Contact/Phone
- Resolve contact, disambiguate, call, message, and inspect recent phone command status.
- Ambiguous contacts must ask for clarification before action.

## Clipboard/Keyboard/Mouse
- Read clipboard, paste, hotkey, type text, click, scroll, and mouse navigation.
- UI automation must avoid destructive clicks without confirmation.

## Vision/Screen
- Screenshot, inspect screen, describe image, find UI target, and verify visual state.
- Visual actions should fail closed when target confidence is low.

## Device/Network
- Wake-on-LAN, safe network status, device reachability, and local device commands.
- Network-changing actions need explicit safety classification.

## Developer/Project
- Open project, run safe tests, inspect files, summarize errors, and prepare patch plans.
- Destructive git/file operations remain outside deterministic auto-execution unless explicitly confirmed.
