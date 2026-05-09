# Tool Promotion Readiness Report

Phase: 15

## Status

- Metadata/tool promotion readiness: implemented for classification and one safe promotion.
- Promoted now: `ReminderTool` as a partial/thin wrapper.
- Deferred safely: Research, Vision, Memory, Phone, Message, Gmail/Email expansion, Google Contacts, Wake-on-LAN, Developer/Terminal/Code tools.

## Promotion Matrix

| Candidate | Classification | Reason |
| --- | --- | --- |
| ReminderTool | promote now | Existing `ReminderService` supports create and due-listing through a bounded wrapper. |
| ResearchTool | keep metadata-only/service-based | Needs provider privacy/exfiltration policy before canonical execution. |
| VisionTool | keep metadata-only/service-based | Existing vision flow is capability-based; canonical side-effect-free tool can be promoted later. |
| MemoryTool | keep metadata-only | Read/write/delete memory needs privacy policy and tests. |
| PhoneTool | keep metadata-only | Phone call/message actions are high risk and remain bridge/service-gated. |
| MessageTool | keep metadata-only | Must not duplicate WhatsApp/Gmail boundaries. |
| GmailTool/EmailTool | keep live shell/fail-closed | Connector remains not configured; no expanded promotion. |
| Google Contacts Tool | blocked by missing connector | Contact resolution uses existing synced-phone/desktop providers. |
| WakeOnLanTool | keep service-based for now | Network side effect needs connector boundary and tests before promotion. |
| Developer/Terminal/Code tools | unsafe/deferred | Proposal-only by default; no arbitrary shell execution. |

## Implemented Tool Path

- `ReminderTool` is registered from `build_readiness_tool_registry()`.
- `reminder` inventory is now `thin_wrapper`/`PARTIAL`/`ACTIVE`.
- Safe partial actions: `create`, `list`.
- Unsafe/unimplemented actions such as `cancel` and `update` remain blocked by policy metadata.
- Execution path remains `ToolExecutor -> PolicyEngine -> ToolRegistry -> ReminderTool -> ReminderService`.

## Tests

Planned/added:

- `python -m pytest -q tests/test_tool_promotion_readiness.py tests/test_tool_orchestrator_architecture.py`

## Blockers

- Terminal/code tools remain proposal-only until Developer Mode is implemented and policy-gated.
- Gmail remains fail-closed until connector configuration exists.
- No high-risk metadata-only tool was promoted.
