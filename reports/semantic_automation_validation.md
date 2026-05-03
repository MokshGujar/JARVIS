# Semantic Automation Validation

## Coverage Summary

| Area | Status | Notes |
| --- | --- | --- |
| Safe file create/write/append | Supported | Executes through `ToolExecutor` and updates `AutomationContext`. |
| Safe browser/app actions | Supported where already implemented | Uses existing tool and policy routes. |
| Risky delete/send/call/submit/click/power/terminal/code actions | Confirmation only | Confirmation is remembered, but execution remains disabled in this phase. |
| Duplicate safe mutation | Confirmation required | Repeats only the stored safe LOW/MEDIUM plan once after confirmation. |
| Dry-run planning | Supported | No actions run. |
| Launcher face gate | Preserved | Face verification remains launcher-only; `/app` does not verify face by default. |

## Confirmation Examples

- Delete: `delete it` -> `I need confirmation before deleting meeting note.txt. Should I delete it?`
- Send: `send this to Rahul: I'll be late` -> `I drafted the message to Rahul. Should I send it?`
- Close: `close this window` -> `I need confirmation before closing this window.`
- Terminal: `run terminal command dir` -> `I need confirmation before running that command.`
- Cancel: `no` -> `Cancelled. I did not delete it.`
- Expired: `yes` after expiry -> `That confirmation expired. I did not run it.`

## Duplicate Protection Examples

- First safe append executes: `put milk in it`.
- Repeated append asks: `This looks like the same action again. Should I repeat it?`
- `yes` repeats the exact stored safe append once.
- A second `yes` after the repeat does nothing dangerous.
- `no` cancels the duplicate repeat.

## Blocked Risky Actions

Confirmed risky actions stay accepted-but-disabled:

- Real file delete
- Real message send
- Real call/video call
- Real form submit
- Terminal execution
- Code edit apply
- Coordinate click
- Shutdown/restart
- Purchase/payment/login submit

## Manual Checklist

1. Create file and write hello.
2. Put more text in it.
3. Repeat same append; expect duplicate warning.
4. Say no; expect no repeat.
5. Repeat same append again; say yes; expect one repeat only.
6. Dry run delete file.
7. Ask delete file; expect confirmation.
8. Say no; expect cancel.
9. Say yes after no; expect no dangerous action.
10. Draft message to Rahul; expect ask before send.
11. Change recipient to Amit; expect pending draft update.
12. Change message; expect pending draft update.
13. Say send it; expect accepted-but-disabled send.
14. Open Chrome and search Python docs.
15. Replace that with AI news.
16. Open Notepad and type hello.
17. Force app focus failure in mock; verify typing stops.
18. Ask submit form; expect confirmation and disabled execution.
19. Ask coordinate click; expect confirmation and disabled execution.
20. Confirm `/app` does not call `/face/verify`.
21. Confirm empty transcript does not start thinking audio or chat.

## Known Gaps

- HIGH/CRITICAL destructive or external actions are intentionally not executable in this phase.
- Voice permission is surfaced through existing policy metadata only; no new voice authorization implementation was added.
- Coordinate click, terminal, code edit, form submit, payment, login, shutdown, and restart remain disabled even after confirmation.
