# Dead File Cleanup Inventory

Date: 2026-05-07

## Classification

- A. Active runtime import: `app/`, `run.py`, `config.py`, current config TOML files.
- B. Active test import: `tests/` source files.
- C. Documentation/report only: existing docs/reports mentioning cleanup candidates.
- D. Runtime/user data, do not delete locally: `database/chats_data`, `database/agent_tasks`, `database/camera_captures`, `database/vector_store`, `database/voice_identity`, `database/face_identity`, `database/memory`.
- E. Generated cache/artifact safe to untrack: `tests/_tmp`, tracked runtime data above, `Jarvis_main.zip`.
- F. Deprecated compatibility module still imported: none proven in this pass.
- G. Dead code candidate safe to delete after checks: untracked ignored `config/app` copied shadow tree.
- H. Unknown, do not delete: any source module still imported by app/tests.

## Proof Checks

- `config/app` was ignored and untracked by git.
- Static search found no runtime/test import of `config.app`.
- Dynamic import/path string search found only docs/reports and the guard test.
- Architecture guard covers absence of `config.app` imports.
- `Jarvis_main.zip` has no runtime/test reference and is ignored by `*.zip`.

## Cleanup Actions

- Deleted untracked `config/app` after verifying resolved path stayed inside the workspace.
- Removed generated/runtime/user state from git tracking with `git rm --cached`; local files were preserved on disk.
- Removed generated `pytest-cache-files-*` directories after the exact full pytest command failed during collection on Windows access-denied cache directories.
- Updated/kept `.gitignore` entries for future runtime pollution prevention, including full `database/vector_store/` and `database/voice_identity/` directories.

## Intentionally Kept

- Runtime/user data remains locally available.
- Source tests remain tracked; only generated `tests/_tmp` files were untracked.
