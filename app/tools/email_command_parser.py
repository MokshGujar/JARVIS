from __future__ import annotations

import re
from dataclasses import dataclass


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class EmailCommand:
    action: str
    recipient: str = ""
    body: str = ""
    subject: str = ""
    query: str = ""


class EmailCommandParser:
    def parse(self, command: str) -> EmailCommand | None:
        text = re.sub(r"\s+", " ", str(command or "").strip()).strip(" .!?")
        if not text:
            return None

        lowered = text.lower()
        if re.match(r"^(?:show\s+)?(?:my\s+)?unread\s+gmail\s+count$", lowered) or re.match(
            r"^(?:show|get)\s+(?:my\s+)?unread\s+(?:email|mail)\s+count$",
            lowered,
        ):
            return EmailCommand("get_unread_count")

        search = re.match(r"^search\s+(?:gmail|emails?|mail)\s+for\s+(?:emails?\s+)?from\s+(?P<recipient>.+)$", text, re.I)
        if search:
            recipient = self._clean_recipient(search.group("recipient"))
            return EmailCommand("search_emails", recipient=recipient, query=f"from:{recipient}")

        read = re.match(r"^read\s+(?:the\s+)?latest\s+(?:gmail|email|mail)\s+from\s+(?P<recipient>.+)$", text, re.I)
        if read:
            return EmailCommand("read_latest_email", recipient=self._clean_recipient(read.group("recipient")))

        reply = re.match(
            r"^reply\s+to\s+(?:the\s+)?latest\s+(?:gmail|email|mail)\s+from\s+(?P<recipient>.+?)\s+(?:saying|that says|body)\s+(?P<body>.+)$",
            text,
            re.I,
        )
        if reply:
            return EmailCommand(
                "reply_email",
                recipient=self._clean_recipient(reply.group("recipient")),
                body=reply.group("body").strip(),
            )

        subject_body = re.match(
            r"^(?P<verb>send|draft|compose|write)\s+(?:an?\s+)?(?:gmail|email|mail)\s+to\s+(?P<recipient>.+?)\s+with\s+subject\s+(?P<subject>.+?)\s+and\s+body\s+(?P<body>.+)$",
            text,
            re.I,
        )
        if subject_body:
            action = "draft_email" if subject_body.group("verb").lower() in {"draft", "compose", "write"} else "send_email"
            return EmailCommand(
                action,
                recipient=self._clean_recipient(subject_body.group("recipient")),
                subject=subject_body.group("subject").strip(),
                body=subject_body.group("body").strip(),
            )

        send_or_draft = re.match(
            r"^(?P<verb>send|draft|compose|write)\s+(?:an?\s+)?(?:gmail|email|mail)\s+to\s+(?P<recipient>.+?)(?:\s+(?:saying|that says|body)\s+(?P<body>.+))?$",
            text,
            re.I,
        )
        if send_or_draft:
            action = "draft_email" if send_or_draft.group("verb").lower() in {"draft", "compose", "write"} else "send_email"
            return EmailCommand(
                action,
                recipient=self._clean_recipient(send_or_draft.group("recipient")),
                body=(send_or_draft.group("body") or "").strip(),
            )

        shorthand = re.match(r"^email\s+(?P<recipient>.+?)\s+(?:that|saying)\s+(?P<body>.+)$", text, re.I)
        if shorthand:
            return EmailCommand(
                "send_email",
                recipient=self._clean_recipient(shorthand.group("recipient")),
                body=shorthand.group("body").strip(),
            )

        return None

    @staticmethod
    def explicit_email(value: str) -> str:
        match = EMAIL_RE.search(str(value or ""))
        return match.group(0) if match else ""

    @staticmethod
    def _clean_recipient(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).strip(" ,;.!?")
