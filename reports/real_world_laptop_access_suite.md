# Real-World Laptop Access Suite

Phase: 13

## Status

- Suite expansion: implemented as documented matrix and importable test data.
- Source of truth for tests: `app/services/real_world_command_suite.py`.
- Test file: `tests/test_real_world_jarvis_commands.py`.
- Privacy note: raw email addresses are redacted in this report and suite data.

## Summary

| Range | Area | Status |
| --- | --- | --- |
| 1-8 | Core/voice/chat | Mixed: mostly supported; repeat-last deterministic route not implemented. |
| 9-21 | Local laptop/files | Supported for search/read/follow-ups; destructive delete protected. |
| 22-30 | Apps/browser/system | Supported for safe actions; shutdown protected. |
| 31-39 | Contacts/WhatsApp/Gmail | WhatsApp/contact paths supported with mocks; Gmail setup required. |
| 40-45 | Phone/app | Phone bridge supported; no-beep added; live Android validation pending. |
| 46-50 | Reminders/research/vision | Reminder tool promoted; research requires provider; vision requires image input. |
| 51-56 | Agents/developer/security | Agents/developer deferred; unsafe commands denied by policy. |

## Matrix

| ID | Command | Route | Tool/Domain | Policy | Direct | Clarify | Status | Blocker/Test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Hello Jarvis | local | chat_service | ALLOW | yes | no | supported now | covered |
| 2 | What can you do? | capability_summary | CapabilitySummaryService | ALLOW | yes | no | supported after this phase | covered |
| 3 | Stop listening | voice_control | frontend_phone_voice | ALLOW | yes | no | metadata/planned | UI-side path |
| 4 | Cancel that | pending_action | pending_confirmation | ALLOW | yes | no | supported now | covered |
| 5 | Repeat that | chat | conversation_service | ALLOW | yes | no | not implemented | deterministic repeat route missing |
| 6 | Give me a short answer | chat | conversation_service | ALLOW | yes | no | supported now | covered |
| 7 | Continue | chat | conversation_service | ALLOW | yes | no | supported now | covered |
| 8 | Explain this simply | chat | conversation_service | ALLOW | yes | no | supported now | covered |
| 9 | Search my laptop for resume | automation | file | ALLOW | yes | no | supported now | covered |
| 10 | Can you search a file for me? | capability_summary | CapabilitySummaryService | ALLOW | yes | no | supported after this phase | covered |
| 11 | Search a file | automation | file | CLARIFY | no | yes | supported now | covered |
| 12 | Find files about Jarvis | automation | file | ALLOW | yes | no | supported now | covered |
| 13 | Find recently modified files | automation | file | ALLOW | yes | no | supported now | covered |
| 14 | List files on Desktop | automation | file | ALLOW | yes | no | supported now | covered |
| 15 | Read it | automation_followup | file | ALLOW | yes | yes | supported now | covered |
| 16 | Open the second one | automation_followup | file/app | ALLOW | yes | yes | supported now | covered |
| 17 | Show me its path | automation_followup | file | ALLOW | yes | yes | supported now | covered |
| 18 | Summarize it | automation_followup | summary | ALLOW | yes | yes | supported now | covered |
| 19 | Create file on desktop named semantictest and write hello | automation | file | ALLOW | yes | no | supported now | covered |
| 20 | Put world in it | automation_followup | file | CONFIRM | no | yes | supported now | protected write/follow-up |
| 21 | Delete it | automation_followup | file | STEP_UP | no | yes | blocked for safety | delete requires confirmation and voice permission |
| 22 | Open calculator | automation | app | ALLOW | yes | no | supported now | covered |
| 23 | Open Chrome | automation | app | ALLOW | yes | no | supported now | covered |
| 24 | Open WhatsApp | automation | whatsapp/app | ALLOW | yes | no | supported now | covered |
| 25 | Search Google for cats | automation | browser | ALLOW | yes | no | supported now | covered |
| 26 | Search Google for files | automation | browser | ALLOW | yes | no | supported now | covered |
| 27 | Show system status | automation | system | ALLOW | yes | no | supported now | covered |
| 28 | Volume up | automation | system | ALLOW | yes | no | supported now | covered |
| 29 | Take screenshot | automation | system | ALLOW | yes | no | supported now | covered |
| 30 | Shutdown computer | automation | system | STEP_UP | no | no | blocked for safety | power action protected |
| 31 | Open WhatsApp chat with Hetanshi India | automation | whatsapp | ALLOW | yes | no | supported now | mocked |
| 32 | Send WhatsApp message to Hetanshi India saying hello | automation | whatsapp | ALLOW | yes | no | supported now | mocked, no real send |
| 33 | Call Hetanshi India on WhatsApp | automation | whatsapp | ALLOW | yes | no | supported now | mocked, no real call |
| 34 | Make WhatsApp video call to Hetanshi India | automation | whatsapp | ALLOW | yes | no | supported now | mocked, no real call |
| 35 | Hitanchi India contact variant | contact_clarification | contact | CLARIFY | no | yes | supported now | asks confirmation first |
| 36 | Send email to [email] saying hello | automation | gmail | DENY | no | no | external setup required | Gmail not configured |
| 37 | Draft email to [email] saying hello | automation | gmail | DENY | no | no | external setup required | Gmail not configured |
| 38 | Show unread Gmail count | automation | gmail | DENY | no | no | external setup required | Gmail not configured |
| 39 | Search Gmail for emails from [email] | automation | gmail | DENY | no | no | external setup required | Gmail not configured |
| 40 | Sync phone contacts | phone_bridge | PhoneCommandService | ALLOW | yes | no | supported now | covered |
| 41 | Show incoming caller | phone_bridge | CallerLookupService | ALLOW | yes | no | supported now | covered |
| 42 | Acknowledge phone pending action | phone_bridge | PhoneCommandService | ALLOW | yes | no | supported now | covered |
| 43 | Background listening without beep | android_service | BackgroundVoiceService | ALLOW | yes | no | supported after this phase | static + assemble |
| 44 | App-side no-speech handling | stt | STTTool | ALLOW | yes | no | supported now | covered |
| 45 | App-side final TTS once | voice_stream | Android stream consumer | ALLOW | yes | no | supported now | covered by existing contracts |
| 46 | Remind me to drink water at 6 PM | reminder | ReminderTool | ALLOW | yes | no | supported after this phase | covered |
| 47 | Show due reminders | notification_center | NotificationCenterService | ALLOW | yes | no | supported after this phase | covered |
| 48 | Prepare daily briefing | agent_workflow | LangGraph/agents | DENY | no | no | metadata/planned | deferred |
| 49 | Research latest AI news | realtime | ResearchToolsService | ALLOW | yes | no | external setup required | requires provider |
| 50 | Describe this image | vision | VisionService | ALLOW | yes | no | supported now | requires image input |
| 51 | Create an agent that tracks AI news | agent | agent_builder | DENY | no | yes | metadata/planned | deferred |
| 52 | List my agents | agent | agent_registry | DENY | no | no | metadata/planned | deferred |
| 53 | Propose terminal command but do not run it | developer | terminal | DENY | no | no | metadata/planned | developer phase deferred |
| 54 | Explain this code | chat | conversation_service | ALLOW | yes | no | supported now | covered by chat |
| 55 | Search project code for AutomationService | developer | code_search | DENY | no | no | metadata/planned | developer mode deferred |
| 56 | Refuse unsafe command | policy | PolicyEngine | DENY | no | no | supported now | covered |

## Blockers

- Gmail connector not configured.
- LangGraph and self-created agents remain disabled/deferred unless Phase 16+ gates pass.
- Developer/code/terminal tools remain proposal-only/deferred.
- Android and WhatsApp live runtime need manual validation outside pytest.
