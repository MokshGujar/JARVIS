# Semantic Routing Reliability Report

Date: 2026-05-06

## Fixed

- `search files` no longer routes to browser search.
- `search files` without a query returns: `What file name or content should I search for?`
- `search files for resume`, `search my files for invoice`, and `find files about project jarvis` route to `FileTool.search_files`.
- Explicit web commands such as `search Google for files` still route to `BrowserTool`.
- Subject context now supports follow-up searches such as `change the subject to MS Dhoni` followed by `search about him on Google`.
- Browser pronouns resolve from subject/entity/browser query context, not file paths.
- Empty STT/no-speech now returns a structured no-speech response and does not trigger chat/thinking/final TTS.

## Guardrails

- Deterministic preemption is intentionally narrow. It fixes the file-search ambiguity without bypassing existing semantic characterization for app actions, file create/write, or high-risk confirmation flows.

## Remaining

- Broader service-level containment is still transitional. Direct service APIs remain documented in the containment report and should be moved behind connectors/adapters in narrow future batches.
