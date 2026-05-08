# Real World Laptop Access Suite

Last validation update: 2026-05-08.

This is a readiness matrix for real Jarvis commands. It documents support truthfully and does not fake unavailable capabilities.

| Command | Status |
|---|---|
| Hello Jarvis | Existing chat path |
| What can you do? | Deferred deterministic capability summary |
| Search my laptop for resume | Supported after this run |
| Can you search a file for me? | Supported clarification after this run |
| Find files about Jarvis | Supported after this run |
| Open calculator | Existing automation/app path |
| Open Chrome | Existing automation/app/browser path |
| Open WhatsApp | Existing WhatsApp Desktop/Web path |
| Search Google for cats | Existing browser path |
| Search Google for files | Browser path, explicitly web |
| Create file on desktop named semantictest and write hello | Existing file creation path |
| Put world in it | Existing file follow-up path |
| Read it | Supported for selected file context |
| Show me its path | Supported for selected file context |
| Delete it | Protected confirmation path |
| Show system status | Existing system status path |
| Volume up | Existing system tool path |
| Shutdown computer | Blocked/protected |
| Send WhatsApp message to Hetanshi India saying hello | Automated-ready, live conditional |
| Call Hetanshi India on WhatsApp | Automated-ready, live conditional |
| Send an email to forserver0101@gmail.com saying hello | Gmail fail-closed until configured |
| Draft an email to forserver0101@gmail.com saying hello | Gmail fail-closed until configured |
| Show unread Gmail count | Gmail fail-closed until configured |
| Remind me to drink water at 6 PM | Existing reminder service, not expanded in this run |
| Show due reminders | Existing/deferred verification |
| Prepare daily briefing | Deferred |
| Research latest AI news | Existing research path, not expanded in this run |
| Describe this image | Existing vision path, not expanded in this run |
| Create an agent that tracks AI news | Deferred |
| Propose terminal command but do not run it | Deferred developer mode |
| Explain this code | Existing chat/read path, developer mode deferred |
| Search project code for AutomationService | Deferred developer mode |
| Refuse unsafe command | Existing policy/blocking path |

## Validation Output

```text
python -m pytest -q tests -p no:cacheprovider
697 passed, 424 subtests passed in 58.48s
```

