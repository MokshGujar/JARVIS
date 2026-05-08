# Laptop Access Report

Last validation update: 2026-05-08.

## Status

Local laptop file search is fixed for the requested phase. Local phrases route to `FileTool`; explicit web phrases route to `BrowserTool`.

## Routing Confirmed

Local file commands now route to `FileTool.search_files` or clarification:

- `Can you search a file for me?`
- `search a file`
- `search my laptop for resume`
- `find resume on my laptop`
- `search documents for assignment`
- `find recently modified files`

Explicit web commands still route to `BrowserTool.search`:

- `search Google for files`
- `search web for files`
- `search internet for files`
- `search online for files`

## Search Bounds

`search my laptop` uses the user/home search root and excludes heavy or protected locations:

- system/protected paths
- `.git`, `.venv`, `venv`, `env`, `node_modules`
- `AppData`, caches, model caches
- database/runtime folders
- pytest/cache/temp folders
- common build/runtime folders

Search has time, scan-count, result-count, and content-size limits. If a limit is hit, results return with `partial=True` and a partial-results message instead of hanging.

## File Understanding

Supported directly:

- TXT/MD/code/text-like files
- CSV preview via stdlib
- selected result follow-ups: path/read/open-select/summarize-attempt

Optional and fail-closed:

- PDF needs `pypdf` or `PyPDF2`
- DOCX needs `python-docx`
- XLSX needs `openpyxl`

Unsupported file types return a clear unsupported/setup-needed response.

## Validation Output

```text
python -m pytest -q tests/test_file_characterization.py tests/test_browser_tool_orchestrator.py tests/test_chat_service_routing.py
32 passed, 1 warning, 21 subtests passed in 6.26s
```

```text
python -m pytest -q tests -p no:cacheprovider
697 passed, 424 subtests passed in 58.48s
```

## Blockers

- True folder summarization and multi-file compare are not expanded beyond the safe selected-file/read path in this run.
- Very large content search intentionally returns partial results or skips oversized files.

