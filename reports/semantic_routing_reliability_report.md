# Semantic Routing Reliability Report

Date: 2026-05-07

## Covered Behaviors

- `search files` claims file/search_files with missing query.
- `search files for resume` routes to FileTool search.
- `search Google for files` and `search web for files` route to BrowserTool.
- Subject-setting commands are deterministic and do not call Brain/Groq.
- `search about him` uses current subject/entity or asks clarification.
- Neutral browser pronouns may use last browser query.
- System status/update/health commands route to SystemTool before general/camera.

## Remaining Risks

- AutomationService still contains legacy fallback helpers, so guards must continue checking known tool-routable commands enter the canonical path before legacy branches.
