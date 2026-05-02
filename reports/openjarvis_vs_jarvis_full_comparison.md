# OpenJarvis vs JARVIS_MAIN Full Forensic Comparison

Generated: 2026-04-28

Scope: inspection only. No application code, imports, routes, frontend files, automation behavior, auth behavior, or data files were modified for this report. The only intentional file output is this report.

## 1. Executive Summary

JARVIS_MAIN is a product-first personal desktop assistant. Its strongest parts are the actual user-facing experience: HUD, launcher, face auth, step-up auth, Windows desktop automation, WhatsApp Desktop/Web control, browser/file/app/system actions, and behavior-specific tests.

OpenJarvis is a framework-first assistant platform. Its strongest parts are architecture: typed registries, tool metadata, tool execution contracts, connector/channel contracts, engine/provider abstraction, event taxonomy, telemetry, security policy modules, route grouping, docs, and broad test organization.

The blunt conclusion: do not replace JARVIS_MAIN with OpenJarvis. JARVIS_MAIN has the local Jarvis identity and real desktop behavior. OpenJarvis has better scaffolding. The correct strategy is selective extraction of framework patterns into JARVIS_MAIN while preserving the current UI, routes, auth, and automation behavior.

## 2. Brutal Verdict

- JARVIS_MAIN wins as a working personal Jarvis app. OpenJarvis does not have your Windows desktop/WhatsApp/launcher/face-auth product flow.
- OpenJarvis wins as an extensible framework. JARVIS_MAIN still has large god files and too much behavior in services.
- The single biggest JARVIS_MAIN problem is `app/services/automation_service.py`: 3,992 lines, one class, parsing/routing/state/execution/security-sensitive behavior all mixed together.
- The second biggest JARVIS_MAIN problem is boundary confusion: `services/`, `tools/`, `connectors/`, `agents/`, and `capabilities/` exist, but many are still wrappers around service internals.
- OpenJarvis is not clean everywhere. It has its own god files: `src/openjarvis/core/config.py` at 1,930 lines, `src/openjarvis/server/agent_manager_routes.py` at 2,187 lines, and a 4,083-line React page. Do not copy those shapes.
- OpenJarvis has too much surface area for your use case: Rust crates, Tauri, MCP, eval/learning pipelines, dozens of social channels, deployment stacks. Most of that would slow your Jarvis down.
- Your security model is stronger where it matters: face auth plus fresh step-up auth for high-risk local actions. OpenJarvis security patterns are useful, but any OpenJarvis flow that uses confirmation without face step-up is weaker for your machine-control assistant.

## 3. Repo Stats

Exclusions used for inventory: `__pycache__`, `.pytest_cache`, `.git`, `.venv`, `venv`, `node_modules`, `build`, `dist`, `.gradle`, `target`, `pytest-cache-files-*`, and binary zip artifacts.

### Summary Counts

| Metric | JARVIS_MAIN | OpenJarvis |
|---|---:|---:|
| Total files | 425 | 1,741 |
| Total folders | 90 | 221 |
| Python files | 144 | 1,121 |
| Test files | 51 | 554 |
| Frontend files | 25 | 100 |
| Config files | 22 | 293 |
| Documentation files | 3 | 85 |
| Total textual lines | 64,185 | 332,454 |

### JARVIS_MAIN Top 20 Largest Files By Line Count

| File | Lines |
|---|---:|
| `database/face_identity/profile.json` | 12,245 |
| `app/services/automation_service.py` | 3,992 |
| `frontend/script.js` | 3,932 |
| `app/main.py` | 1,890 |
| `android-companion/.idea/caches/deviceStreaming.xml` | 1,610 |
| `android-companion/app/src/main/java/com/jarvis/companion/MainActivity.kt` | 1,480 |
| `android-companion/app/src/main/java/com/jarvis/companion/BackgroundVoiceService.kt` | 1,375 |
| `app/services/brain_service.py` | 1,189 |
| `frontend/enroll.js` | 993 |
| `app/services/chat_service.py` | 978 |
| `frontend/enroll.css` | 936 |
| `frontend/launcher.js` | 818 |
| `frontend/launcher.css` | 814 |
| `frontend/style.css` | 710 |
| `app/services/agent_service.py` | 687 |
| `app/services/phone_command_service.py` | 674 |
| `android-companion/app/src/main/java/com/jarvis/companion/VoiceprintMatcher.kt` | 665 |
| `android-companion/app/src/main/java/com/jarvis/companion/JarvisApiClient.kt` | 626 |
| `config.py` | 604 |
| `database/vector_store/index_manifest.json` | 602 |

### OpenJarvis Top 20 Largest Files By Line Count

| File | Lines |
|---|---:|
| `frontend/package-lock.json` | 12,542 |
| `uv.lock` | 10,299 |
| `frontend/src-tauri/Cargo.lock` | 6,222 |
| `frontend/src/pages/AgentsPage.tsx` | 4,083 |
| `rust/Cargo.lock` | 3,523 |
| `src/openjarvis/server/agent_manager_routes.py` | 2,187 |
| `frontend/src/pages/DataSourcesPage.tsx` | 1,944 |
| `src/openjarvis/core/config.py` | 1,930 |
| `frontend/src-tauri/src/lib.rs` | 1,721 |
| `src/openjarvis/evals/datasets/coding_assistant.py` | 1,632 |
| `src/openjarvis/evals/cli.py` | 1,462 |
| `src/openjarvis/engine/cloud.py` | 1,359 |
| `src/openjarvis/channels/whatsapp_baileys_bridge/package-lock.json` | 1,351 |
| `frontend/src/components/Desktop/AgentsPanel.tsx` | 1,210 |
| `src/openjarvis/evals/environments/lifelong_agent_env.py` | 1,185 |
| `src/openjarvis/evals/core/runner.py` | 1,156 |
| `docs/getting-started/configuration.md` | 1,115 |
| `src/openjarvis/evals/datasets/doc_qa.py` | 1,106 |
| `tests/evals/test_lifelong_agent.py` | 1,097 |
| `src/openjarvis/evals/datasets/security_scanner.py` | 1,074 |

### JARVIS_MAIN Top Folders By File Count

| Folder | Files |
|---|---:|
| `database/chats_data` | 106 |
| `app/services` | 45 |
| `tests` | 33 |
| `database/agent_tasks` | 28 |
| `android-companion/app/src/main/java/com/jarvis/companion` | 25 |
| `frontend` | 11 |
| `app/tools` | 11 |
| `android-companion/.idea` | 11 |
| `frontend/audio` | 10 |
| `app/core` | 9 |
| `app/capabilities` | 9 |
| `app/connectors` | 8 |
| `app/agents` | 8 |
| `android-companion` | 7 |
| `app/adapters/face` | 6 |
| `database/camera_captures` | 6 |
| `config` | 6 |
| `.` | 6 |
| `app/utils` | 5 |
| `frontend/assets/hud` | 4 |

### OpenJarvis Top Folders By File Count

| Folder | Files |
|---|---:|
| `src/openjarvis/evals/configs` | 169 |
| `tests/agents` | 44 |
| `src/openjarvis/cli` | 42 |
| `tests/connectors` | 41 |
| `tests/tools` | 40 |
| `tests/cli` | 39 |
| `src/openjarvis/evals/datasets` | 39 |
| `src/openjarvis/evals/scorers` | 39 |
| `src/openjarvis/connectors` | 36 |
| `src/openjarvis/tools` | 36 |
| `src/openjarvis/channels` | 34 |
| `tests/channels` | 33 |
| `tests/learning` | 28 |
| `tests/learning/distillation` | 27 |
| `tests/evals` | 25 |
| `tests/telemetry` | 25 |
| `tests/server` | 24 |
| `tests/security` | 24 |
| `tests/engine` | 22 |
| `src/openjarvis/agents` | 22 |

### JARVIS_MAIN Top Folders By Python Lines

| Folder | Python lines | Python files |
|---|---:|---:|
| `app/services` | 15,286 | 45 |
| `tests` | 4,468 | 33 |
| `app` | 2,089 | 4 |
| `app/core` | 931 | 9 |
| `.` | 841 | 2 |
| `app/adapters/face` | 409 | 6 |
| `app/tools` | 381 | 11 |
| `app/capabilities` | 251 | 9 |
| `app/bootstrap` | 188 | 1 |
| `app/adapters/storage` | 155 | 1 |
| `app/connectors` | 138 | 8 |
| `app/utils` | 113 | 5 |
| `app/agents` | 79 | 8 |

### OpenJarvis Top Folders By Python Lines

| Folder | Python lines | Python files |
|---|---:|---:|
| `src/openjarvis/evals/datasets` | 12,234 | 39 |
| `src/openjarvis/cli` | 11,506 | 42 |
| `src/openjarvis/connectors` | 9,684 | 36 |
| `src/openjarvis/server` | 8,464 | 21 |
| `tests/agents` | 7,660 | 44 |
| `src/openjarvis/tools` | 7,603 | 36 |
| `tests/connectors` | 7,139 | 41 |
| `tests/tools` | 7,106 | 40 |
| `tests/learning` | 7,103 | 28 |
| `src/openjarvis/evals/scorers` | 7,072 | 39 |
| `src/openjarvis/agents` | 6,532 | 22 |
| `src/openjarvis/channels` | 5,887 | 34 |
| `tests/evals` | 5,724 | 25 |
| `tests/channels` | 5,484 | 33 |
| `tests/telemetry` | 5,293 | 25 |
| `tests/cli` | 5,205 | 39 |
| `tests/engine` | 5,050 | 22 |
| `tests/learning/distillation` | 4,472 | 27 |
| `src/openjarvis/evals/core` | 4,045 | 15 |
| `tests/skills` | 3,572 | 20 |

## 4. Folder-By-Folder Comparison

### JARVIS_MAIN Folders

| Folder/file | Responsibility | Quality | Better than OpenJarvis | Worse than OpenJarvis | Pattern to copy | Do not copy | Equivalent | Risk |
|---|---|---|---|---|---|---|---|---|
| `app/` | FastAPI app package, models, main app, generated audio helper | Mixed | Real product routes and desktop assistant behavior | Too much in `main.py`; package boundaries are uneven | OpenJarvis route/module grouping | OpenJarvis app sprawl | `src/openjarvis/` | Medium |
| `app/services/` | Most business logic and automation | Product-rich but overloaded | Strong local automation, face auth, step-up, phone bridge | God folder; services include tools, connectors, repositories, providers, routers | Split by tool/connector/security/provider | Big-bang service rewrite | `src/openjarvis/{tools,agents,engine,security,server}` | High |
| `app/tools/` | Thin tool wrappers | Good start after Phase 1, still shallow | Names align with your domains | Most tools delegate back into `AutomationService` | OpenJarvis `ToolSpec`/executor pattern | OpenJarvis generic shell/code tools | `src/openjarvis/tools/` | Medium |
| `app/connectors/` | Thin local connector wrappers | Underdeveloped | Local desktop concepts fit your app | Missing rich connector lifecycle/status/sync | OpenJarvis connector contracts | Cloud connector bloat | `src/openjarvis/connectors/`, `channels/` | Medium |
| `app/agents/` | Placeholder agents | Weak | Names match target architecture | Mostly stubs | OpenJarvis agent base/context/result | Autonomous long-running agents now | `src/openjarvis/agents/` | Medium |
| `app/core/` | Contracts, orchestrator, config loader, event bus, face vector utils | Improving | Simpler and Jarvis-specific | Event/config/contract system still young | Typed events, trace/result contracts | Huge OpenJarvis config file | `src/openjarvis/core/` | Low |
| `app/capabilities/` | Capability adapters for orchestrator | Decent adapter layer | Keeps route-facing capability names stable | Some overlap with tools/services | Keep as compatibility layer | Over-abstracting every service | OpenJarvis tool/agent bridge concepts | Medium |
| `frontend/` | Main HUD, launcher, enroll UI, JS/CSS/audio | Product-strong but large | Your HUD and launcher are the Jarvis identity | `script.js` is 3,932 lines; many states in one file | Maybe split internal modules later | OpenJarvis React/Tauri UI | `frontend/` | High if touched |
| `tests/` | Characterization and unit tests | Better than typical hobby app | Strong behavior capture for automation/auth | Flat layout will strain as suite grows | OpenJarvis grouped tests by subsystem | Massive eval test machinery | `tests/` | Low |
| `config/` | TOML configs for automation/browser/models/security | Good direction | Small and readable | Still coexists with huge `config.py` | OpenJarvis config docs and typed sections | Hardware auto-detection complexity | `configs/openjarvis/` | Low |
| `database/` | Runtime data, chats, face profile, vector store, tasks | Risky in repo | Works locally and tests real state | Stores personal/biometric/runtime artifacts in repo tree | OpenJarvis stores under user config/data dirs | OpenJarvis home-dir hidden writes without migration | `.openjarvis` data patterns | Critical |
| `run.py` | Launcher/startup wrapper | Useful and specific | Face-gate launcher flow is yours | Subprocess/browser path hardcoding | OpenJarvis CLI separation only conceptually | OpenJarvis CLI/deployment matrix | `src/openjarvis/cli`, server entrypoints | Medium |
| `config.py` | Env loading, paths, prompts, constants | Useful but too broad | Clear single-file compatibility | 604-line global config/prompt/constants file | Move typed sections gradually | OpenJarvis 1,930-line config blob | `src/openjarvis/core/config.py` | Medium |

### OpenJarvis Folders

| Folder/file | Responsibility | Quality | Better than JARVIS_MAIN | Worse than JARVIS_MAIN | Pattern to copy | Do not copy | Equivalent | Risk |
|---|---|---|---|---|---|---|---|---|
| `src/openjarvis/` | Framework package root | Broad and modular | Clean subsystem split | Too broad for your app | Package-level subsystem separation | Import-all optional dependency churn | `app/` | Medium |
| `src/openjarvis/core/` | Registry, config, events, types | Strong concepts, mixed execution | Typed registries/events/types | `config.py` is a god file | `registry.py`, `events.py`, `types.py` ideas | Full config implementation | `app/core/` | Low |
| `src/openjarvis/tools/` | Tool specs and tool executor | Strong | Metadata, confirmation flag, timeouts, OpenAI function shape | Generic tools not tied to your security | Tool metadata/executor discipline | Shell/code interpreter as-is | `app/tools/` | Medium |
| `src/openjarvis/agents/` | Agent bases, managers, loops | Strong but broad | Agent context/result, manager concepts | Long-running autonomous scope is overkill | Base agent/result/event helpers | Operative/OpenHands/Claude subprocess stack | `app/agents/`, `agent_service.py` | Medium |
| `src/openjarvis/connectors/` | Data source sync connectors | Strong pattern | Document schema, sync status, auth lifecycle | Many irrelevant cloud integrations | BaseConnector/Document/SyncStatus | Google/Slack/Notion zoo | `app/connectors/` | Medium |
| `src/openjarvis/channels/` | Messaging send/receive channels | Strong abstraction | Separates channels from data connectors | Most channels irrelevant; many broad exceptions | BaseChannel/ChannelMessage/status | Cloud WhatsApp/Baileys now | Phone/WhatsApp services | High |
| `src/openjarvis/engine/` | Provider/inference backends | Strong | Provider abstraction and multi-engine routing | Too many engines for immediate need | Base provider, stream/generate contract | Hardware/engine matrix now | `groq_service.py`, `realtime_service.py` | Medium |
| `src/openjarvis/security/` | Capability, guardrail, scanners, policies | Useful | Capability labels, guardrail wrapping, scanners | Lacks your biometric step-up boundary | Capability vocabulary and audit concepts | Open-by-default policy, confirmation-only flows | `command_risk_service.py`, `secure_execution_service.py` | High |
| `src/openjarvis/memory/` | Not present as source folder | N/A | Tests exist under `tests/memory`; source memory is under tools/storage/sessions | Folder requested by prompt does not exist | Storage/retrieval test patterns | Inventing a fake module | `personal_memory_service.py`, `vector_store.py` | Low |
| `src/openjarvis/server/` | FastAPI app/routes/session/websocket | Strong structure but has god route files | Route grouping, middleware separation | `agent_manager_routes.py` is 2,187 lines | Split route modules | Copying route bloat | `app/main.py` | Medium |
| `tests/` | Large subsystem test suite | Very strong | Organization by subsystem | Too large to port wholesale | Folder structure and contract tests | Eval-heavy suites | `tests/` | Low |
| `examples/` | Usage demos | Good docs aid | Helps understand intended APIs | Not product code | Small examples for future docs | Twitter/security examples as features | `DEVELOPMENT.md` | Low |
| `configs/` | Config examples/prompts | Good | Example-driven configuration | Too many unrelated recipes | Config examples and persona docs | Full config matrix | `config/`, `config.py` | Low |
| `docs/` | Architecture/user/deployment docs | Strong | Much better documentation discipline | Deployment docs irrelevant now | Architecture docs structure | Docker/systemd/Tauri deployment docs | none | Low |
| `frontend/` | React/Tauri UI | Mixed | Componentized app | Huge pages, wrong product identity | Maybe SSE/event UI ideas | Replacing HUD | `frontend/` | High |
| `rust/` | Rust crates for core/tools/security/telemetry | Strong engineering but overkill | Performance and compiled policies | Adds build/deploy complexity | None for now | Rust stack | none | High |

## 5. Service-By-Service Comparison

Every file in `JARVIS_MAIN/app/services` is classified below.

| Service file | Lines | Responsibility | Nearest OpenJarvis equivalent | Cleaner OpenJarvis pattern? | Keep as service? | Future placement | Risk | Suggested action |
|---|---:|---|---|---|---|---|---|---|
| `automation_service.py` | 3,992 | Local automation parser/router/executor/pending state | `tools/*`, `channels/*`, `security/*` | Yes | Facade only | tools/connectors/security | Critical | Characterize then extract one domain at a time |
| `brain_service.py` | 1,189 | LLM/rule intent classification and payload parsing | `agents/*`, `prompt/*`, routing policies | Partial | No | core router/agent | High | Split routing, prompt, payload extraction |
| `chat_service.py` | 978 | Chat sessions, streams, Jarvis route execution | `server/routes.py`, `sessions`, agents | Yes | Partly | conversation service + server stream layer | High | Keep API behavior; split streaming/orchestration later |
| `agent_service.py` | 687 | Local agent task abstractions | `agents/manager.py`, `agents/executor.py` | Yes | Partly | agents manager | Medium | Align with agent context/result contracts |
| `phone_command_service.py` | 674 | Phone bridge contacts/pending actions | `channels/*`, `server/channel_bridge.py` | Yes | Yes | connector/channel plus repository | High | Keep behavior; split storage and channel contract |
| `face_enrollment_service.py` | 587 | Face enrollment workflow | OpenJarvis has no equivalent | No | Yes | security/auth service | Medium | Keep; add more auth tests only |
| `caller_lookup_service.py` | 565 | Caller identity lookup | connectors/gcontacts style | Partial | Yes | contact service/connector | Medium | Keep; isolate provider/source logic |
| `fast_intent_router_service.py` | 449 | Fast route heuristics | router policies, agents | Yes | No | core router | Medium | Move after characterization |
| `groq_service.py` | 442 | Groq chat provider with key fallback | `engine/cloud.py`, `_stubs.py`, `multi.py` | Yes | No | providers/groq | Medium | Phase 5 provider abstraction |
| `realtime_service.py` | 439 | Realtime/search-augmented Groq provider | `engine/*`, web search tools | Yes | No | providers + research tool | Medium | Split provider from search orchestration |
| `jarvis_orchestrator_service.py` | 432 | Tool route planning/orchestration | `agents/orchestrator.py`, system orchestrator | Yes | No | agents/orchestrator | Medium | Consolidate with `app/core/orchestrator.py` later |
| `task_executor.py` | 418 | Task execution for content/image/automation | `tools/_stubs.py`, agent executor | Yes | Partly | tool executor/agent executor | Medium | Add result contracts, then split |
| `vector_store.py` | 385 | FAISS/vector retrieval | `tools/storage/*`, `tests/memory/*` | Yes | Yes | memory/retrieval service | Medium | Keep; wrap with memory interface |
| `contact_match_service.py` | 368 | Fuzzy contact matching | connector/contact patterns | Partial | Yes | contact service | Medium | Keep; add alias/ambiguity tests |
| `face_identity_service.py` | 333 | Face verification/session auth | no equivalent | No | Yes | security/auth service | High | Keep untouched unless auth tests demand |
| `browser_control_service.py` | 227 | Playwright browser control | `tools/browser.py` | Yes | No | browser connector/tool | High | Extract only after browser characterization |
| `research_tools_service.py` | 221 | Safe research helpers | `tools/web_search.py`, research agent | Yes | Partly | research tool | Low | Keep, then tool metadata |
| `whatsapp_desktop_automation.py` | 221 | Windows WhatsApp UI automation | no clean OpenJarvis equivalent | No | No | WhatsApp desktop connector | High | Preserve exact behavior; connector wrapper only |
| `reminder_service.py` | 207 | Reminder persistence and due checks | scheduler/store/tools | Yes | Yes | reminders service/tool | Medium | Add scheduler contract later |
| `chat_session_store.py` | 200 | Chat persistence | `server/session_store.py`, `sessions/session.py` | Yes | Yes | repository | Low | Keep; standardize interface |
| `game_service.py` | 194 | Steam/Epic/game actions | generic tools | No | No | game tool/connector | Medium | Leave until core automation cleaned |
| `vision_service.py` | 165 | Vision model calls | engine/provider abstraction | Yes | No | provider/tool | Medium | Phase 5 provider abstraction |
| `task_manager.py` | 159 | Background task state/execution | scheduler/agents manager | Yes | Yes | task manager | Medium | Add events and storage boundary |
| `personal_memory_service.py` | 158 | Personal notes/session notes | sessions/storage/memory tools | Yes | Yes | memory service/repository | Medium | Add TTL/query tests first |
| `computer_control_service.py` | 144 | Keyboard/mouse primitives | system/shell tools | Partial | No | Windows system connector | High | Keep locked behind security wrapper later |
| `automation_response.py` | 140 | Normalize automation response shape | `ToolResult` | Yes | No | core/action_result | Low | Move after compatibility tests |
| `step_up_auth_service.py` | 139 | Fresh face challenge/token issue/consume | no equivalent | No | Yes | security/auth service | Critical | Keep stronger than OpenJarvis |
| `secure_execution_service.py` | 114 | Security wrapper for tool execution | `tools/_stubs.py`, `security/*` | Partial | Yes | security service | High | Centralize only after extractions |
| `youtube_tools_service.py` | 110 | YouTube web actions | browser/web tools | Yes | No | browser/content tool | Medium | Extract after browser tool stable |
| `computer_settings_service.py` | 109 | Windows settings/app open actions | system tools | Partial | No | Windows system connector | High | Keep behavior; wrap later |
| `message_action_service.py` | 90 | Telegram/Instagram/web message actions | channel tools | Yes | No | communication tool/channel | High | Treat as high-risk send path |
| `acknowledgement_service.py` | 89 | Dynamic acknowledgement phrases | templates/prompts | Partial | Yes | response service | Low | Keep or move to response planner |
| `wake_on_lan_service.py` | 86 | Wake-on-LAN packet sender | system/network tool | Partial | Yes | system connector/tool | Medium | Add event/security classification |
| `launcher_bootstrap_service.py` | 76 | Launcher bootstrap token exchange | no equivalent | No | Yes | auth service | High | Keep untouched |
| `command_risk_service.py` | 71 | Risk classification regex/policy | `security/capabilities.py`, guardrails | Yes | Yes | security service | High | Expand with capability labels |
| `safe_command_info_service.py` | 65 | Read-only command info | shell/system info tool | Partial | No | system info tool | Medium | Keep read-only and tested |
| `interrupt_manager.py` | 61 | Interrupt token manager | agent/session control | Partial | Yes | core/session control | Low | Keep |
| `decision_types.py` | 54 | Decision constants/types | `core/types.py` | Yes | No | core/contracts | Low | Merge into contracts later |
| `observability_service.py` | 53 | Recent event persistence | telemetry/store | Yes | Yes | telemetry service | Low | Wire to event bus later |
| `automation_file_ops.py` | 46 | Recycle-bin delete helper | file tools/security file policy | Yes | No | file repository/tool util | Medium | Keep behind file tool |
| `contact_resolution_service.py` | 45 | Contact resolution wrapper | connectors/contact concepts | Partial | Yes | contact service | Low | Merge with contact match later |
| `latency_metrics_service.py` | 34 | Latency snapshots | telemetry/phase_metrics | Yes | Yes | telemetry | Low | Keep and emit event bus data |
| `liveness_service.py` | 29 | Liveness wrapper | no equivalent | No | Yes | security/face adapter | High | Keep |
| `context_memory.py` | 28 | TTL session memory | sessions/context | Yes | Yes | memory/context | Low | Expand carefully |
| `__init__.py` | 13 | Package marker | N/A | N/A | No | N/A | Low | No action |

## 6. Architecture Comparison

| Area | OpenJarvis approach | JARVIS_MAIN approach | Better | Adopt | Avoid | Exact files |
|---|---|---|---|---|---|---|
| Tool/plugin architecture | Registry, `ToolSpec`, `BaseTool`, executor, timeouts, confirmation | Thin `AutomationTool` wrappers, many bridge back to service | OpenJarvis | Tool metadata, timeout/result contracts | Generic shell/code tools | `src/openjarvis/tools/_stubs.py`; `app/tools/*` |
| Agent design | BaseAgent, AgentContext, AgentResult, manager/executor | Placeholder `app/agents`, plus separate `agent_service.py` | OpenJarvis for structure | Agent result/context shape | Long-running autonomous operative stack | `src/openjarvis/agents/_stubs.py`; `app/agents/*` |
| Connector/channel system | Separate data connectors and message channels | Connectors are thin; phone/WhatsApp live in services | OpenJarvis | BaseConnector/BaseChannel split | Broad cloud channel list | `src/openjarvis/connectors/_stubs.py`, `channels/_stubs.py`; `app/connectors/*` |
| Config management | Typed config, examples, hardware detection | `config.py` globals plus TOML loader | Tie | Gradual TOML typed sections | 1,930-line monolithic config | `src/openjarvis/core/config.py`; `config.py`, `app/core/config_loader.py` |
| Event bus/telemetry | EventType taxonomy, telemetry stores/wrappers | Small sanitized event bus, latency metrics | OpenJarvis | Event taxonomy, trace discipline | GPU/energy telemetry now | `src/openjarvis/core/events.py`, `telemetry/*`; `app/core/event_bus.py` |
| Security model | Capabilities, guardrails, scanners, confirmation | Command risk plus face session plus fresh step-up token | JARVIS_MAIN for local actions | Capability labels/audit events | Open-by-default policy and no-face confirmation | `src/openjarvis/security/*`; `app/services/*auth*`, `command_risk_service.py` |
| Provider/model abstraction | Engine interface, multi-engine, cloud/local backends | Groq-specific services | OpenJarvis | `generate`/`stream` provider interface | Full engine matrix initially | `src/openjarvis/engine/*`; `groq_service.py`, `realtime_service.py` |
| Memory/context | Session store, storage backends, memory tests | Vector store, personal memory, TTL memory | OpenJarvis for architecture | Session/context interfaces | Eval learning memory stack | `tools/storage/*`, `server/session_store.py`; `vector_store.py`, `personal_memory_service.py` |
| Server/API structure | `server/app.py`, route modules, middleware | One huge `app/main.py` | OpenJarvis | Route grouping by domain | Agent manager route bloat | `src/openjarvis/server/*`; `app/main.py` |
| Frontend/backend boundary | React/Tauri frontend API libs | Plain JS HUD tightly bound to backend SSE/actions | JARVIS_MAIN product, OpenJarvis structure | Event/action contract docs | Replacing HUD with React/Tauri | `frontend/script.js`; OpenJarvis `frontend/src/*` |
| Testing strategy | Subsystem folders, broad contract tests | Good characterization but flat | OpenJarvis organization | Group tests by subsystem | Massive eval suites | `tests/*` both repos |
| Startup/dependency loading | CLI/server/app split; many optional imports | `run.py`, `build_container`, startup loads vector store | Tie | Container assembly and route split | Multi-deployment CLI stack | `run.py`, `app/bootstrap/container.py`; `src/openjarvis/cli/*` |
| Automation execution flow | Generic tool executor, not Windows-product specific | Real Windows/WhatsApp automation in service | JARVIS_MAIN behavior | Tool executor boundary | OpenJarvis browser/shell behavior as replacement | `automation_service.py`; `tools/_stubs.py` |
| Error handling | Many broad exceptions but usually wrapped | Many broad exceptions, especially automation/main | Neither fully | Structured result errors | Silent catch-all patterns | hotspot tables |
| Logging/observability | Telemetry and trace modules | Logger plus recent events and latency metrics | OpenJarvis | Sanitized event traces | Heavy energy telemetry | `telemetry/*`, `traces/*`; `observability_service.py` |

## 7. Feature Comparison

| Feature | Winner | Why | Copy? | Ignore? |
|---|---|---|---|---|
| HUD | JARVIS_MAIN | Product identity; OpenJarvis UI is different | No | Ignore OpenJarvis UI |
| Launcher | JARVIS_MAIN | Face-gated local launcher is specific and working | No | Ignore Tauri launcher |
| Face auth | JARVIS_MAIN | OpenJarvis has no equivalent local biometric flow | No | Keep current |
| Step-up auth | JARVIS_MAIN | Fresh face step-up and single-use token is stronger | Only add audit events | Ignore weaker confirmation-only flows |
| Local desktop automation | JARVIS_MAIN | Real Windows behavior exists | Use OpenJarvis tool boundary only | Ignore generic shell approach |
| WhatsApp Desktop/Web | JARVIS_MAIN | Desktop/Web automation fits current use | Use channel/connector contracts only | Avoid Cloud/Baileys now |
| Browser control | Tie | JARVIS has product behavior; OpenJarvis has cleaner tool spec | Adopt metadata/contracts | Do not replace behavior |
| File automation | JARVIS_MAIN behavior | Current behavior is characterized | Adopt file policy/result shape | Do not change semantics now |
| Voice flow | JARVIS_MAIN | Browser and Android voice flows are product-specific | Maybe event contracts | Ignore OpenJarvis speech stack for now |
| Groq integration | JARVIS_MAIN current | Works with current app | Adopt provider abstraction later | Do not rewrite now |
| Image/content generation | JARVIS_MAIN current | Already routed in task executor | Tool metadata later | Ignore eval examples |
| Tool framework | OpenJarvis | Better spec/executor/registry | Yes | No |
| Agents | OpenJarvis | Better base contracts | Yes, lightly | Avoid operative/OpenHands stack |
| Connectors/channels | OpenJarvis | Cleaner separation | Yes, selectively | Avoid broad channel zoo |
| Engine/provider abstraction | OpenJarvis | Much cleaner than Groq-specific services | Yes, Phase 5 | Avoid full hardware matrix |
| Memory | OpenJarvis pattern | Better interfaces/tests | Yes, selectively | Avoid learning stack |
| Evals | OpenJarvis | Powerful but not needed | Maybe test style only | Ignore eval infra |
| Server/API | OpenJarvis | Better route organization | Yes | Avoid route god files |
| Security policy | Tie | OpenJarvis has capabilities; Jarvis has stronger face auth | Adopt labels/audit | Avoid open-by-default/confirmation-only |
| Docs | OpenJarvis | Much better | Yes | Do not copy deployment docs |
| Deployment | OpenJarvis | Broad, but irrelevant | No | Ignore Docker/systemd for now |
| Rust stack | OpenJarvis engineering, not fit | Adds complexity | No | Ignore |

## 8. Line-Level Hotspot Analysis

### JARVIS_MAIN Hotspots

| File/range | Problem | Why it matters | OpenJarvis comparison | Recommendation |
|---|---|---|---|---|
| `database/face_identity/profile.json:1-12245` | Biometric profile stored in repo tree | Critical privacy/security risk; huge data file pollutes repo stats | OpenJarvis tends to use user config/data dirs | Move runtime biometric data outside repo after migration plan |
| `database/chats_data/*` | 106 chat JSON files in repo tree | Personal data and noisy runtime artifacts | OpenJarvis session store defaults outside repo | Move to runtime data dir; add `.gitignore` strategy |
| `app/services/automation_service.py:96-3986` | God class | Parses, routes, stages confirmations, controls apps, files, browser, WhatsApp, system | OpenJarvis splits tools/connectors/security | Keep facade, extract by characterized domains |
| `app/services/automation_service.py:518-862` | Central legacy routing cascade | Hard to reason about precedence and regressions | OpenJarvis uses registry/executor | Characterization tests before any move |
| `app/services/automation_service.py:1214-1734` | WhatsApp parsing/resolution/pending state mixed in automation | Send/call actions are high-risk | OpenJarvis separates channels but lacks your desktop behavior | Extract to `whatsapp_tool` + connectors, keep behavior |
| `app/services/automation_service.py:1980-2829` | App/browser/system opening and subprocess fallbacks mixed | Direct OS control paths need central security | OpenJarvis uses tools with capability labels | Wrap later through `secure_execute` after tests |
| `app/services/automation_service.py:2861-3837` | File path parsing, CRUD, delete confirmation in same class | File mutation is high-risk; hard to audit | OpenJarvis has file tools and file policy | Extract file tool after characterization |
| `app/services/automation_service.py:3886-3968` | Direct `Popen`, `os.startfile`, process close | Security-sensitive execution path | OpenJarvis shell/system tools mark confirmation | Move to Windows app/system connectors |
| `frontend/script.js:57-3932` | Frontend god file | HUD behavior is fragile to change | OpenJarvis React is componentized but wrong identity | Do not touch now; later split internal modules only |
| `app/main.py:174-289` | Startup lifecycle initializes many globals | Hard to test and slow startup | OpenJarvis has server app/container split | Move route groups later, not now |
| `app/main.py:563-707` | Face/auth routes embedded in giant app file | Security endpoints deserve separate router | OpenJarvis route modules are cleaner | Extract routes only with API tests |
| `app/main.py:1043-1268` | Streaming/TTS/SSE generator complexity | Many responsibilities and timing branches | OpenJarvis stream bridges separate concerns | Keep behavior; add stream characterization |
| `app/main.py:1509-1675` | Jarvis realtime pipeline inside app module | Backend boundary confusion | OpenJarvis routes delegate to system/orchestrator | Move to service after tests |
| `app/services/brain_service.py:164-1189` | Classifier plus prompt building plus regex payload extraction | Routing decisions are hard to verify | OpenJarvis uses agent/router concepts | Split into router policy and payload extractors |
| `app/services/chat_service.py:247-976` | Chat streaming, automation routing, vision, action emission in one method region | Risky frontend regressions | OpenJarvis separates server/session/agent | Characterize frontend action stream first |
| `app/bootstrap/container.py:5-38` | Imports almost every service | Container is central dependency magnet | OpenJarvis has broader but structured app builders | Keep but split provider/tool registration later |
| `config.py:76-604` | Global paths, model config, prompts, security constants | Hard to validate and override cleanly | OpenJarvis typed config, but too large | Gradually move to TOML/typed config |
| `run.py:64-151` | Managed subprocess and browser launching | Useful but Windows/browser hardcoded | OpenJarvis CLI split | Keep; test startup only |

### OpenJarvis Hotspots

| File/range | Problem | Why it matters | JARVIS_MAIN comparison | Recommendation |
|---|---|---|---|---|
| `src/openjarvis/server/agent_manager_routes.py:1-2187` | Server route god file | OpenJarvis also has route bloat | JARVIS `main.py` has same problem | Copy route grouping idea, not this file shape |
| `src/openjarvis/core/config.py:1-1930` | Giant config/hardware/model file | Too much central config complexity | JARVIS `config.py` is smaller but similar risk | Adopt typed config sections, not monolith |
| `frontend/src/pages/AgentsPage.tsx:1-4083` | Huge React page | Componentization is incomplete | JARVIS `script.js` has same problem | Do not copy frontend |
| `src/openjarvis/engine/cloud.py:1-1359` | Provider mega-adapter | Useful but too broad | JARVIS Groq services are narrower | Build small provider interface first |
| `src/openjarvis/evals/cli.py:1-1462` | Heavy eval command surface | Not needed for local assistant migration | JARVIS tests are characterization-focused | Ignore eval infra |
| `src/openjarvis/tools/shell_exec.py:1-170` | Shell command execution tool | Dangerous in personal desktop assistant | JARVIS must require face step-up for shell/system | Do not copy as live tool |
| `src/openjarvis/channels/whatsapp_baileys.py:1-230` | Node subprocess bridge for WhatsApp | Adds account/session/security complexity | JARVIS already controls Desktop/Web | Avoid until explicit requirement |
| `src/openjarvis/security/capabilities.py:1-190` | Policy defaults open unless configured | Weaker than fail-closed local control | JARVIS command risk is safer for high-risk actions | Use labels, not open-by-default behavior |
| `src/openjarvis/channels/*` broad exceptions | Many adapters catch `Exception` | Failure can be opaque | JARVIS also overuses broad exceptions | Adopt result contracts and logs |
| `rust/` | Extra implementation stack | Build/deploy/debug complexity | JARVIS is Python/Kotlin/JS local app | Do not add Rust now |

## 9. What To Copy From OpenJarvis

| Rank | OpenJarvis idea/module | Exact OpenJarvis files/folders | Why useful | Current JARVIS_MAIN equivalent | Target in JARVIS_MAIN | Risk | Phase |
|---:|---|---|---|---|---|---|---|
| 1 | Typed registry base | `src/openjarvis/core/registry.py` | Clean plugin discovery | `app/tools/registry.py` | `app/core/registry.py` or extend tool registry | Low | 1 |
| 2 | Tool metadata | `src/openjarvis/tools/_stubs.py` | Tool docs, risk, capabilities, timeout | `app/tools/base.py` | `app/tools/base.py` | Low | 1 |
| 3 | Tool executor result discipline | `src/openjarvis/tools/_stubs.py` | Centralizes execution shape | `SecureExecutionService` partial | `app/services/secure_execution_service.py` | High | 4 |
| 4 | Connector contract | `src/openjarvis/connectors/_stubs.py` | Lifecycle/status/document schema | `app/connectors/base.py` | `app/connectors/base.py` | Low | 1 |
| 5 | Channel contract | `src/openjarvis/channels/_stubs.py` | Separates send/receive channels | Phone/WhatsApp services | `app/connectors` or `app/channels` | Medium | 2 |
| 6 | Event taxonomy | `src/openjarvis/core/events.py` | Consistent telemetry names | `app/core/event_bus.py` | `app/core/event_bus.py` | Low | 1/7 |
| 7 | Agent context/result | `src/openjarvis/agents/_stubs.py` | Removes ad hoc agent returns | `app/agents/*` stubs | `app/agents/base.py` | Medium | 3 |
| 8 | Engine/provider interface | `src/openjarvis/engine/_stubs.py` | Groq/OpenAI/local swap | `groq_service.py` | `app/providers/base.py` | Medium | 5 |
| 9 | Multi-provider routing | `src/openjarvis/engine/multi.py` | Model-to-provider routing | none | `app/providers/router.py` | Medium | 5 |
| 10 | Stream chunk model | `src/openjarvis/engine/_stubs.py` | Structured streaming | SSE dict chunks | `app/core/contracts.py` | Medium | 5 |
| 11 | Capability labels | `src/openjarvis/security/capabilities.py` | Tool permissions vocabulary | `CommandRiskService` regex | `app/services/command_risk_service.py` | High | 4 |
| 12 | Guardrail wrapper concept | `src/openjarvis/security/guardrails.py` | Wraps model/tool boundaries | `SecureExecutionService` | `secure_execution_service.py` | High | 4 |
| 13 | Secret/PII scanners | `src/openjarvis/security/scanner.py` | Sanitized logs/events | event sanitization | `app/core/event_bus.py` | Medium | 4/7 |
| 14 | Session store shape | `src/openjarvis/server/session_store.py` | Channel/session history | `chat_session_store.py` | repository interface | Low | 6 |
| 15 | Server route modules | `src/openjarvis/server/*` | Shrinks app file | `app/main.py` | `app/routes/*` later | Medium | 7 |
| 16 | Middleware separation | `src/openjarvis/server/middleware.py` | Cleaner app setup | `TimingMiddleware` in main | `app/server/middleware.py` | Low | 7 |
| 17 | Tool tests grouping | `tests/tools/*` | Focused contracts | flat tests | `tests/tools/*` | Low | 2 |
| 18 | Security tests grouping | `tests/security/*` | Security is first-class | auth/risk tests mixed | `tests/security/*` | Low | 2 |
| 19 | Connector tests grouping | `tests/connectors/*` | Connector lifecycle tests | characterization only | `tests/connectors/*` | Low | 2 |
| 20 | Docs architecture layout | `docs/architecture/*` | Maintains decisions | minimal docs | `docs/architecture/*` | Low | 1/7 |
| 21 | Config examples | `configs/openjarvis/examples/*` | Shows valid setups | `config/*.toml` | `config/examples/*` | Low | 7 |
| 22 | Prompt/persona files | `configs/openjarvis/prompts/*` | Moves prompts out of code | `config.py` prompt constants | `config/prompts/*` | Medium | 7 |
| 23 | Trace collector pattern | `src/openjarvis/traces/*` | Debuggable automation flow | recent events only | `app/services/observability_service.py` | Medium | 7 |
| 24 | Telemetry wrapper idea | `src/openjarvis/telemetry/wrapper.py` | Measures provider/tool latency | `latency_metrics_service.py` | telemetry service | Medium | 7 |
| 25 | Storage backend test discipline | `tests/memory/*`, `tools/storage/*` | Retrieval regressions become visible | `vector_store.py` tests | `tests/memory/*` | Medium | 6 |
| 26 | CLI command grouping concept | `src/openjarvis/cli/*` | Keeps operations separate | `run.py` only | future dev CLI | Low | 7 |
| 27 | Webhook/session bridge concept | `server/channel_bridge.py` | Future phone/channel bridge | phone bridge service | later `app/channels` | Medium | 6 |
| 28 | Tool description override | `tools/description_loader.py` | Better LLM tool prompts | none | future tool descriptions | Low | 3 |
| 29 | Boundary guard concept | security boundary modules | Prevent outbound leakage | event sanitization only | security wrapper | High | 4 |
| 30 | Test fixture organization | `tests/fixtures/*` | Cleaner repeatable tests | ad hoc `_tmp` | `tests/fixtures/*` | Low | 2 |

## 10. What Not To Copy

| OpenJarvis component | Why not useful for your Jarvis | Risk if copied blindly | Better JARVIS_MAIN alternative |
|---|---|---|---|
| Rust stack | Adds build, packaging, debugging complexity | Slows iteration; breaks simple local dev | Stay Python for backend; Kotlin only for companion |
| Tauri/frontend stack | Replaces your HUD identity | Large rewrite with no behavior gain | Keep current HUD/launcher |
| MCP stack | Not needed for current local assistant | New protocol surface and security review | Use internal tool registry first |
| Eval/learning infrastructure | Research platform scope | Massive complexity and irrelevant test failures | Keep characterization tests |
| Broad social-channel integrations | You need WhatsApp/phone now, not 30 platforms | Credential sprawl and maintenance burden | Implement only WhatsApp/phone/contact connectors |
| Deployment complexity | Docker/systemd/launchd not current goal | Breaks local Windows-first workflow | Keep `run.py` launcher |
| Shell execution tool | High-risk for local machine | Security bypass if not face-step-up gated | Use `CommandRiskService` + `SecureExecutionService` |
| WhatsApp Cloud API channel | Different product behavior from Desktop/Web | Account/API dependency, send semantics change | Keep Desktop/Web automation connectors |
| Baileys WhatsApp bridge | Node subprocess/session complexity | Account/session risk, hidden side effects | Current WhatsApp Desktop/Web flow |
| Open-by-default capability policy | Weaker than fail-closed security | Agents may get capabilities accidentally | Default deny for high-risk actions |
| Hardware auto-detection engine matrix | Not needed for Groq-first app | Config bloat | Small provider abstraction |
| OpenHands/Claude subprocess agents | Coding-agent scope, not personal assistant | Process/security complexity | Simple Jarvis agents only |
| Energy/GPU telemetry | Irrelevant now | Noise and dependencies | Basic latency/status telemetry |

## 11. Technical Debt In JARVIS_MAIN

| File/folder | Severity | Why | Recommended fix | OpenJarvis better pattern? |
|---|---|---|---|---|
| `database/face_identity/profile.json` | Critical | Biometric runtime data in repo tree | Move to external runtime data dir and ignore | Yes, user data dirs |
| `database/chats_data/` | High | Personal chat history in repo tree | Externalize runtime data; fixture-only test data | Yes, session store |
| `app/services/automation_service.py` | Critical | God class and high-risk execution paths | Characterization-first extraction | Yes, tools/connectors |
| `frontend/script.js` | High | Frontend god file | Do not touch now; later split modules | Partial, but do not copy React |
| `app/main.py` | High | Routes, startup, streaming, metrics, static assets all together | Route modules after API tests | Yes, server modules |
| `config.py` | Medium | Global config/prompt/constants | Gradual typed TOML sections | Yes, but not monolith |
| `app/services/brain_service.py` | High | Routing, LLM prompts, regex extraction mixed | Split router/prompt/payload | Yes, agent/router pattern |
| `app/services/chat_service.py` | High | Streaming, routing, automation, vision, actions mixed | Split conversation vs route execution | Yes, server/session/agent |
| `app/tools/*` | Medium | Tools mostly delegate into legacy service | Extract real domain logic later | Yes, tool executor |
| `app/connectors/*` | Medium | Mostly thin wrappers | Add lifecycle/status and real connector ownership | Yes |
| `app/agents/*` | Medium | Mostly placeholders | Add base agent context/result before use | Yes |
| `app/bootstrap/container.py` | Medium | Imports and builds nearly everything | Add registries/providers gradually | Partial |
| Broad `except Exception` usage | Medium | Can hide automation/security failures | Convert high-risk paths to explicit result errors | OpenJarvis also flawed |
| Direct subprocess/browser automation | High | Many OS effects outside central wrapper | Centralize after extraction | Yes, capability wrapper |
| Duplicate routing | High | Brain, fast router, chat service, automation service all route | Define one route contract | Yes, router policies |
| Data artifacts in repo | High | Vector store, camera captures, tasks, chats | Move runtime artifacts out | Yes |
| Naming overlap | Medium | tools/connectors/capabilities/services overlap | Define ownership rules | Yes |
| Weak tests for route modules | Medium | Main routes are hard to refactor | Add route characterization | OpenJarvis server tests |

## 12. Recommended Migration Phases

### Phase 1: Safest Immediate Improvements

- Files to touch: `app/tools/base.py`, `app/tools/registry.py`, `app/connectors/base.py`, `app/core/event_bus.py`, `app/core/config_loader.py`, `tests/test_architecture_foundation.py`.
- Files not to touch: `frontend/*`, `app/services/automation_service.py`, auth internals, route behavior.
- Tests required: foundation architecture tests and full suite.
- Risk: Low.
- Rollback: revert foundation-only files; no behavior path should depend on new features yet.

### Phase 2: Tool/Connector Cleanup

- Files to touch: `app/tools/*`, `app/connectors/*`, `tests/test_*_characterization.py`.
- Files not to touch: frontend/HUD, face auth internals, `app/main.py` routes.
- Tests required: WhatsApp/browser/file/app/system characterization before each extraction.
- Risk: High.
- Rollback: keep `AutomationService` legacy methods callable and switch tool bridge back.

### Phase 3: Service Folder Cleanup

- Files to touch: `automation_response.py`, `browser_control_service.py`, `whatsapp_desktop_automation.py`, `computer_*`, `message_action_service.py`.
- Files not to touch: UI and public API routes.
- Tests required: unchanged automation characterization plus service unit tests.
- Risk: High.
- Rollback: restore compatibility bridge in `AutomationService`.

### Phase 4: Security Wrapper Centralization

- Files to touch: `secure_execution_service.py`, `command_risk_service.py`, extracted tools only.
- Files not to touch: `step_up_auth_service.py` token semantics except tests.
- Tests required: high-risk confirmation, face session, fresh step-up, token single-use, fail-closed unknown risk.
- Risk: Critical.
- Rollback: route only selected tools through wrapper until stable.

### Phase 5: Provider Abstraction

- Files to touch: `groq_service.py`, `realtime_service.py`, `vision_service.py`, new `app/providers/*`.
- Files not to touch: chat route response shape and frontend stream protocol.
- Tests required: provider fallback, streaming chunks, rate-limit handling, vision behavior.
- Risk: Medium.
- Rollback: keep old Groq services behind provider adapter.

### Phase 6: Memory/Context Improvement

- Files to touch: `personal_memory_service.py`, `context_memory.py`, `vector_store.py`, `chat_session_store.py`.
- Files not to touch: current chat history API behavior.
- Tests required: TTL expiry, follow-ups, retrieval regression, session persistence.
- Risk: Medium.
- Rollback: keep old memory service and disable new retrieval layer by config.

### Phase 7: Legacy Cleanup

- Files to touch: `automation_service.py`, `app/main.py`, `config.py`, route modules.
- Files not to touch: frontend behavior unless separate UI phase is approved.
- Tests required: full suite, route tests, automation characterization, startup tests.
- Risk: High.
- Rollback: do cleanup in small PR-sized patches and leave facade imports stable.

## 13. Risk Table

| Area | Risk | Why | Mitigation |
|---|---|---|---|
| Face auth / step-up | Critical | Security boundary for local high-risk actions | Do not weaken; tests before every security change |
| WhatsApp send/call | Critical | External communication side effects | Confirmation plus fresh face step-up |
| File delete/overwrite | Critical | Data loss risk | Characterization and recycle-bin/file-policy tests |
| `AutomationService` extraction | High | Behavior precedence is complex | One domain at a time behind facade |
| Frontend/HUD | High | User identity and stream contract | Do not touch until backend stable |
| Provider abstraction | Medium | Can break chat/streaming | Adapter preserving old Groq behavior |
| Config migration | Medium | Defaults can shift silently | TOML/env precedence tests |
| OpenJarvis channel adoption | High | Credentials and external APIs | Do not adopt broad channels |
| Runtime data externalization | High | Can break existing profiles/history | Migration plan and backup |
| Route splitting | Medium | Public API regressions | Route characterization tests |

## 14. Next Exact Execution Prompt

Use this prompt next if you want a safe implementation step:

```text
Implement Phase 2A only: add missing characterization tests for current WhatsApp and browser behavior before extraction.

Do not move behavior.
Do not refactor AutomationService.
Do not touch frontend/HUD.
Do not change security behavior.

Add tests that lock:
- WhatsApp open Desktop/Web behavior
- WhatsApp contact required and ambiguous contact states
- WhatsApp send-message pending confirmation shape
- WhatsApp call pending confirmation shape
- Browser search/open/follow-up behavior
- Browser control result shapes
- Current auth_required/frontend action payloads for high-risk actions

Run:
- python -m pytest tests\test_whatsapp_characterization.py tests\test_browser_characterization.py -q
- python -m pytest tests -q -p no:cacheprovider
```

