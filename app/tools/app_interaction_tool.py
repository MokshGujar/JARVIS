from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from config import (
    APP_INTERACTION_BACKEND,
    APP_INTERACTION_CLICK_COORDINATES_ENABLED,
    APP_INTERACTION_DEBUG,
    APP_INTERACTION_ENABLED,
    APP_INTERACTION_REQUIRE_FOCUSED_WINDOW,
    APP_INTERACTION_SEMANTIC_ACTIONS_ENABLED,
    APP_INTERACTION_TYPE_DELAY_MS,
)
from app.adapters.ui import PywinautoAdapter
from app.tools.base import BaseTool, ToolContext, ToolResult, ToolSpec, normalize_tool_result


@dataclass(slots=True)
class AppInteractionConfig:
    enabled: bool = APP_INTERACTION_ENABLED
    backend: str = APP_INTERACTION_BACKEND
    require_focused_window: bool = APP_INTERACTION_REQUIRE_FOCUSED_WINDOW
    click_coordinates_enabled: bool = APP_INTERACTION_CLICK_COORDINATES_ENABLED
    type_delay_ms: int = APP_INTERACTION_TYPE_DELAY_MS
    semantic_actions_enabled: bool = APP_INTERACTION_SEMANTIC_ACTIONS_ENABLED
    debug: bool = APP_INTERACTION_DEBUG


class AppInteractionTool(BaseTool):
    name = "app_interaction"
    spec = ToolSpec(
        name="app_interaction",
        description="Safe interaction with the active desktop app through an injectable UI adapter.",
        category="ui_automation",
        safety_level="MEDIUM",
        supported_intents=[
            "app_interaction",
            "type_text",
            "type_into_active_field",
            "press_safe_key",
            "press_key",
            "press_hotkey",
            "select_address_bar",
            "submit_current_field",
            "clear_current_field",
            "replace_current_field",
            "copy_selection",
            "paste_text",
            "select_all",
            "undo",
            "redo",
            "open_new_tab",
            "close_current_tab",
            "browser_back",
            "browser_forward",
            "refresh",
            "click_text",
            "click_coordinates",
            "read_window_title",
        ],
        metadata={"extraction_phase": "ui_automation_boundary"},
    )

    SAFE_KEYS = {"enter", "tab", "escape", "esc", "backspace", "delete", "space", "left", "right", "up", "down", "f5"}
    HOTKEY_ACTIONS: dict[str, tuple[str, ...]] = {
        "select_address_bar": ("ctrl", "l"),
        "copy_selection": ("ctrl", "c"),
        "select_all": ("ctrl", "a"),
        "undo": ("ctrl", "z"),
        "redo": ("ctrl", "y"),
        "open_new_tab": ("ctrl", "t"),
        "close_current_tab": ("ctrl", "w"),
        "browser_back": ("alt", "left"),
        "browser_forward": ("alt", "right"),
        "refresh": ("ctrl", "r"),
    }

    def __init__(
        self,
        adapter: Any | None = None,
        *,
        config: AppInteractionConfig | None = None,
        adapter_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config or AppInteractionConfig()
        self.adapter = adapter
        self.adapter_factory = adapter_factory or PywinautoAdapter

    def execute(self, context: ToolContext, **kwargs: Any) -> dict[str, Any] | None:
        action = str(context.payload.get("action") or context.intent or "").strip() or "type_text"
        args = dict(context.payload.get("args") or {})
        if kwargs:
            args.update(kwargs)
        try:
            result = self._execute_action(action, args)
        except Exception as exc:  # Defensive boundary: never leak stack traces through ToolResult.
            result = ToolResult(
                success=False,
                message=f"Desktop interaction failed: {exc}",
                tool_name=self.name,
                error="app_interaction_error",
                safety_level="MEDIUM",
                data={"action": action, "verification_status": "failed"},
            ).as_dict()
        normalized = normalize_tool_result(result, default_action=action)
        normalized["tool_name"] = self.name
        normalized.setdefault("selected_tool", self.name)
        return normalized

    def _execute_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        if not self.config.enabled:
            return self._blocked(action, "Desktop interaction is disabled.", error="app_interaction_disabled")
        if not self.config.semantic_actions_enabled:
            return self._blocked(action, "Desktop semantic interactions are disabled.", error="app_interaction_semantic_disabled")

        adapter = self._adapter()
        if not bool(adapter.is_available()):
            return ToolResult(
                success=False,
                message="Desktop interaction is unavailable because pywinauto is missing.",
                tool_name=self.name,
                error="pywinauto_unavailable",
                safety_level="MEDIUM",
                data={"action": action, "verification_status": "failed"},
            ).as_dict()

        if action in {"type_text", "type_into_active_field"}:
            return self._type_text(adapter, action, str(args.get("text") or args.get("content") or ""))
        if action == "append_text":
            text = str(args.get("text") or args.get("content") or "")
            focus = self._ensure_focused_window(adapter, action)
            if focus is not None:
                return focus
            enter = self._adapter_call(adapter, "press_key", "enter", planned_action=action)
            if not bool(enter.get("success")):
                return enter
            typed = self._adapter_call(adapter, "type_text", text, planned_action=action)
            typed["action"] = action
            return self._with_verification(typed, "likely_success")
        if action in {"press_safe_key", "press_key"}:
            key = str(args.get("key") or "").strip().lower()
            if key not in self.SAFE_KEYS:
                return self._blocked(action, "That key is not in the safe key list.", error="unsafe_key")
            return self._with_verification(self._adapter_call(adapter, "press_key", key, planned_action=action), "likely_success")
        if action == "press_hotkey":
            keys = args.get("keys") or []
            if isinstance(keys, str):
                keys = [item.strip() for item in keys.split("+") if item.strip()]
            return self._with_verification(self._adapter_call(adapter, "press_hotkey", list(keys), planned_action=action), "likely_success")
        if action == "submit_current_field":
            return self._with_verification(self._adapter_call(adapter, "press_key", "enter", planned_action=action), "likely_success")
        if action == "clear_current_field":
            return self._clear_current_field(adapter, action)
        if action == "replace_current_field":
            return self._replace_current_field(adapter, action, str(args.get("text") or args.get("content") or ""))
        if action == "paste_text":
            text = str(args.get("text") or args.get("content") or "")
            if text:
                return self._type_text(adapter, action, text)
            return self._with_verification(self._adapter_call(adapter, "press_hotkey", ["ctrl", "v"], planned_action=action), "likely_success")
        if action in self.HOTKEY_ACTIONS:
            return self._with_verification(self._adapter_call(adapter, "press_hotkey", list(self.HOTKEY_ACTIONS[action]), planned_action=action), "likely_success")
        if action == "click_text":
            return self._click_text(adapter, str(args.get("text") or args.get("label") or ""))
        if action == "click_coordinates":
            return self._click_coordinates(adapter, args)
        if action == "read_window_title":
            return self._read_window_title(adapter)
        if action == "verify_text_present":
            return self._with_verification(
                self._adapter_call(adapter, "verify_text_present", str(args.get("text") or ""), planned_action=action),
                "verified",
            )
        return self._blocked(action, "That desktop interaction is not supported.", error="unsupported_action")

    def _adapter(self) -> Any:
        if self.adapter is None:
            self.adapter = self.adapter_factory(backend=self.config.backend, type_delay_ms=self.config.type_delay_ms)
        return self.adapter

    def _type_text(self, adapter: Any, action: str, text: str) -> dict[str, Any]:
        if not text:
            return self._blocked(action, "Tell me what to type.", error="missing_text")
        focus = self._ensure_focused_window(adapter, action)
        if focus is not None:
            return focus
        return self._with_verification(self._adapter_call(adapter, "type_text", text, planned_action=action), "likely_success")

    def _clear_current_field(self, adapter: Any, action: str) -> dict[str, Any]:
        focus = self._ensure_focused_window(adapter, action)
        if focus is not None:
            return focus
        selected = self._adapter_call(adapter, "press_hotkey", ["ctrl", "a"], planned_action=action)
        if not bool(selected.get("success")):
            return selected
        cleared = self._adapter_call(adapter, "press_key", "backspace", planned_action=action)
        cleared["action"] = action
        return self._with_verification(cleared, "likely_success")

    def _replace_current_field(self, adapter: Any, action: str, text: str) -> dict[str, Any]:
        if not text:
            return self._blocked(action, "Tell me what to type.", error="missing_text")
        focus = self._ensure_focused_window(adapter, action)
        if focus is not None:
            return focus
        selected = self._adapter_call(adapter, "press_hotkey", ["ctrl", "a"], planned_action=action)
        if not bool(selected.get("success")):
            return selected
        typed = self._adapter_call(adapter, "type_text", text, planned_action=action)
        typed["action"] = action
        return self._with_verification(typed, "likely_success")

    def _click_text(self, adapter: Any, text: str) -> dict[str, Any]:
        if not text:
            return self._blocked("click_text", "Tell me what to click.", error="missing_target")
        focus = self._ensure_focused_window(adapter, "click_text")
        if focus is not None:
            return focus
        return self._with_verification(self._adapter_call(adapter, "click_text", text, planned_action="click_text"), "likely_success")

    def _click_coordinates(self, adapter: Any, args: dict[str, Any]) -> dict[str, Any]:
        if not self.config.click_coordinates_enabled:
            return self._blocked("click_coordinates", "Coordinate clicking is disabled.", error="coordinate_click_disabled")
        focus = self._ensure_focused_window(adapter, "click_coordinates")
        if focus is not None:
            return focus
        try:
            x = int(args.get("x"))
            y = int(args.get("y"))
        except Exception:
            return self._blocked("click_coordinates", "Tell me the coordinates to click.", error="missing_coordinates")
        return self._with_verification(self._adapter_call(adapter, "click_coordinates", x, y, planned_action="click_coordinates"), "likely_success")

    def _read_window_title(self, adapter: Any) -> dict[str, Any]:
        active = self._adapter_call(adapter, "get_active_window", planned_action="read_window_title")
        if not bool(active.get("success")):
            active["action"] = "read_window_title"
            return self._with_verification(active, "failed")
        title = str(active.get("title") or active.get("data", {}).get("title") or "").strip()
        active["action"] = "read_window_title"
        active["title"] = title
        active["message"] = f"Active window: {title}." if title else "I could not read the active window title."
        active["success"] = bool(title)
        return self._with_verification(active, "verified" if title else "failed")

    def _ensure_focused_window(self, adapter: Any, action: str) -> dict[str, Any] | None:
        if not self.config.require_focused_window:
            return None
        active = self._adapter_call(adapter, "get_active_window", planned_action="get_active_window")
        if not bool(active.get("success")) or not str(active.get("title") or "").strip():
            return ToolResult(
                success=False,
                message="I could not verify the active window, so I did not interact with it.",
                tool_name=self.name,
                error="active_window_unknown",
                safety_level="MEDIUM",
                data={"action": action, "verification_status": "blocked"},
            ).as_dict()
        return None

    def _adapter_call(self, adapter: Any, method_name: str, *args: Any, planned_action: str) -> dict[str, Any]:
        method = getattr(adapter, method_name)
        result = method(*args)
        if isinstance(result, ToolResult):
            data = result.as_dict()
        elif isinstance(result, dict):
            data = dict(result)
        else:
            data = {"success": bool(result), "action": planned_action, "message": "Desktop interaction completed." if result else "Desktop interaction failed."}
        data["success"] = bool(data.get("success"))
        data["action"] = str(data.get("action") or planned_action)
        data["message"] = str(data.get("message") or ("Done." if data["success"] else "Desktop interaction failed."))
        data.setdefault("tool_name", self.name)
        return data

    @staticmethod
    def _with_verification(result: dict[str, Any], status: str) -> dict[str, Any]:
        data = dict(result)
        data.setdefault("data", {})
        if isinstance(data["data"], dict):
            data["data"] = {**data["data"], "verification_status": status if data.get("success") else "failed"}
        data["verification_status"] = status if data.get("success") else "failed"
        return data

    def _blocked(self, action: str, message: str, *, error: str) -> dict[str, Any]:
        return ToolResult(
            success=False,
            message=message,
            tool_name=self.name,
            error=error,
            safety_level="MEDIUM",
            data={"action": action, "verification_status": "blocked"},
        ).as_dict()
