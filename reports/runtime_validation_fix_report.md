# Runtime Validation Fix Report

Date: 2026-05-07

## Semantic Bugs Fixed

- Bare `search files` is file-domain `SEARCH_FILES` with missing query, not browser `SEARCH_WEB`.
- `search files` returns `status=clarification_required` with `What file name or content should I search for?`; BrowserTool is not invoked.
- Explicit web searches such as `search Google for files` and `search web for files` continue to route to BrowserTool with query `files`.
- Subject-setting phrases update `current_subject` and `last_explicit_entity` before general chat or browser routing.
- Browser pronoun resolution now uses subject/entity before browser query; `him/her` without subject/entity asks clarification.
- Browser query extraction normalizes repeated search-engine prefixes such as `google for`.
- System status/update/health phrases route to `SystemTool.safe_system_info`.
- Fast-response thinking TTS skips now log `[TTS_THINKING] status=skipped reason=fast_response`.

## Files Changed

- Semantic/router/tool path: planner, semantic mapper/adapter, intent router, browser/file tools, orchestration/executor status logging.
- Facade path: `AutomationService.execute()` now uses `AutomationContextBuilder`, `AutomationFacadeResponseFormatter`, and `PendingConfirmationService`.
- Observability: realtime thinking pipeline logs fast-response thinking TTS skip.

## Test Notes

- `tests/test_runtime_observability.py` is not present; `tests/test_canonical_chain_observability.py` is the nearest equivalent.
- `tests/test_stt_no_speech.py` and `tests/test_tts_streaming_contract.py` are not present; STT and browser/thinking streaming equivalents were used.

## Test Results

- Semantic validation suite: `57 passed, 1 warning, 40 subtests passed in 7.12s`.
- Focused runtime/streaming suite: `104 passed, 1 warning, 46 subtests passed in 8.82s`.
- Final full suite with cache disabled: `665 passed, 405 subtests passed in 52.85s`.
- Exact `python -m pytest -q` was attempted and failed during collection because generated `pytest-cache-files-*` directories had Windows access-denied permissions; the generated cache directories were removed and the full suite was rerun with `-p no:cacheprovider`.
