from __future__ import annotations

import re
from typing import Any

from app.connectors.browser_connector import BrowserConnector
from app.services.automation_response import normalize_automation_response
from app.services.command_risk_service import CommandRiskService
from app.tools.base import BaseTool, ToolContext, ToolRisk, ToolSpec


class BrowserTool(BaseTool):
    name = "browser"
    spec = ToolSpec(
        name="browser",
        description="Browser and web automation through the Jarvis compatibility facade.",
        category="browser",
        safety_level="HIGH",
        supported_intents=[
            "browser",
            "browser_control",
            "browser_search",
            "browser_open_url",
            "browser_open_site",
            "browser_youtube_search",
            "browser_youtube_play",
            "browser_navigation",
            "browser_tab_control",
            "browser_form_input",
        ],
        metadata={"extraction_phase": "legacy_bridge"},
    )

    def __init__(
        self,
        connector: BrowserConnector | None = None,
        *,
        automation_bridge: Any | None = None,
        risk_service: CommandRiskService | None = None,
    ) -> None:
        self.connector = connector
        self.automation_bridge = automation_bridge
        self.risk_service = risk_service or CommandRiskService()

    def can_handle(self, intent: str) -> bool:
        return super().can_handle(intent)

    def classify_risk(self, command: str) -> ToolRisk:
        risk = self.risk_service.classify(command, command_action="automation")
        return ToolRisk(level=risk.risk_level, step_up_required=risk.step_up_required, reasons=list(risk.reasons))

    def execute(self, context: ToolContext) -> dict[str, Any] | None:
        planned_action = str(context.payload.get("action") or "").strip()
        if planned_action:
            planned_result = self._execute_planned_action(planned_action, dict(context.payload.get("args") or {}), context=context)
            if planned_result is not None:
                planned_result["tool_name"] = self.name
                return planned_result

        if self.automation_bridge and hasattr(self.automation_bridge, "_execute_browser_command_legacy"):
            result = self.automation_bridge._execute_browser_command_legacy(context.command, context=context)
            if result is None:
                return None
            normalized = normalize_automation_response(result)
            normalized["tool_name"] = self.name
            return normalized

        if self.connector is None:
            return {"success": False, "action": "unsupported", "message": "Browser tool is not wired yet."}

        command = context.command or ""
        match = re.match(r"^(?:browser search|search browser|search in browser)\s+(.+?)[.!?]*$", command, flags=re.IGNORECASE)
        if match:
            return self.connector.execute("search", query=match.group(1).strip(), engine="google")

        match = re.match(r"^(?:open url|go to|browser open|browser go to)\s+(.+?)[.!?]*$", command, flags=re.IGNORECASE)
        if match:
            return self.connector.execute("go_to", url=match.group(1).strip())

        match = re.match(r"^(?:click browser|browser click|smart click)\s+(.+?)[.!?]*$", command, flags=re.IGNORECASE)
        if match:
            return self.connector.execute("click", text=match.group(1).strip())

        match = re.match(r"^(?:type in browser|browser type|smart type in browser|fill form)\s+(.+?)[.!?]*$", command, flags=re.IGNORECASE)
        if match:
            return self.connector.execute("smart_type", text=match.group(1).strip(), clear_first=True)

        if re.match(r"^(?:get page text|read page text|browser get text)[.!?]*$", command, flags=re.IGNORECASE):
            return self.connector.execute("get_text")

        if re.match(r"^(?:close browser|browser close)[.!?]*$", command, flags=re.IGNORECASE):
            return self.connector.execute("close")

        match = re.match(r"^(?:browser scroll|scroll browser)\s*(up|down)?(?:\s+(\d+))?[.!?]*$", command, flags=re.IGNORECASE)
        if match:
            return self.connector.execute("scroll", direction=(match.group(1) or "down"), amount=int(match.group(2) or 500))

        match = re.match(r"^incognito(?:\s+(.+?))?[.!?]*$", command, flags=re.IGNORECASE)
        if match:
            return self.connector.execute("incognito", url=(match.group(1) or "https://www.google.com").strip())

        return None

    def _execute_planned_action(self, action: str, args: dict[str, Any], *, context: ToolContext) -> dict[str, Any] | None:
        if action == "search":
            query = str(args.get("query") or "").strip()
            if not query:
                return {"success": False, "action": "search", "message": "Tell me what to search for."}
            if self.automation_bridge and hasattr(self.automation_bridge, "_execute_browser_command_legacy"):
                result = self.automation_bridge._execute_browser_command_legacy(f"search {query} on google", context=context)
                if result is None:
                    return None
                return normalize_automation_response(result)
            if self.connector is not None:
                return self.connector.execute("search", query=query, engine="google")
            return {"success": False, "action": "search", "message": "Browser tool is not wired yet."}

        if action in {"open_url", "open_site"}:
            target = str(args.get("url") or args.get("site") or "").strip()
            if not target:
                return {"success": False, "action": action, "message": "Tell me which site to open."}
            if self.automation_bridge and hasattr(self.automation_bridge, "_execute_browser_command_legacy"):
                result = self.automation_bridge._execute_browser_command_legacy(f"open {target}", context=context)
                if result is None:
                    return None
                return normalize_automation_response(result)
            if self.connector is not None:
                return self.connector.execute("go_to", url=target)
            return {"success": False, "action": action, "message": "Browser tool is not wired yet."}

        return None
