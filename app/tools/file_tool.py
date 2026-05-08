from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from app.utils.runtime_observability import log_boundary
from app.services.clarification_service import ClarificationService
from app.services.automation_file_ops import move_to_recycle_bin
from app.services.command_risk_service import CommandRiskService
from app.services.automation_response import normalize_automation_response
from app.tools.base import BaseTool, ToolContext, ToolRisk, ToolSpec
from app.tools.compatibility_runners import FileCompatibilityRunner

logger = logging.getLogger(__name__)

try:
    from send2trash import send2trash
except Exception:
    send2trash = None


class FileTool(BaseTool):
    name = "file"
    spec = ToolSpec(
        name="file",
        description="Local file and folder operations through the Jarvis compatibility facade.",
        category="file",
        safety_level="CRITICAL",
        requires_confirmation=False,
        requires_face_step_up=False,
        supported_intents=[
            "file",
            "files",
            "local_files",
            "resolve_path",
            "create_file",
            "write_file",
            "append_file",
            "create_folder",
            "verify_exists",
            "read_file",
            "list_files",
            "search_files",
            "rename_file",
            "move_file",
            "delete_file",
            "delete_folder",
        ],
        metadata={"extraction_phase": "legacy_bridge"},
    )

    OPERATION_PATTERNS: tuple[tuple[str, str, tuple[re.Pattern[str], ...]], ...] = (
        (
            "list",
            "A",
            (
                re.compile(r"^(?:list|show)(?:\s+me)?\s+(?:the\s+)?files\b", re.I),
                re.compile(r"^(?:show\s+)?(?:the\s+)?(?:largest|biggest)\s+files\b", re.I),
                re.compile(r"^(?:(?:preview\s+)?organize|organize\s+preview)\b", re.I),
            ),
        ),
        (
            "search",
            "A",
            (
                re.compile(r"^find\s+", re.I),
                re.compile(r"^(?:can\s+you\s+)?(?:please\s+)?search\s+(?:a\s+)?file(?:\s+for\s+me)?[.!?]*$", re.I),
                re.compile(r"^(?:search\s+(?:my\s+)?files?|search\s+local\s+files?|search\s+in\s+files?|look\s+in\s+my\s+files?|look\s+for\s+(?:a\s+)?file|search\s+(?:my\s+)?(?:laptop|computer|pc)|search\s+(?:desktop|documents|downloads|home))\b", re.I),
            ),
        ),
        ("read", "B", (re.compile(r"^(?:read|show|display)(?:\s+me)?\s+(?:the\s+)?(?:file|text\s+file)\b", re.I),)),
        (
            "create",
            "C",
            (
                re.compile(r"^(?:create|make)(?:\s+a)?(?:\s+new)?\s+(?:file|folder|directory)\b", re.I),
                re.compile(r"^(?:in\s+)?(?P<folder>(?:that|the)\s+folder|.+?)\s+(?:add|create|make)\s+(?:a\s+)?file\b", re.I),
            ),
        ),
        ("update", "C", (re.compile(r"^(?:in\s+)?(?:(?:that|the)\s+file|it)\s+(?:add|write|append|put|insert)\b", re.I),)),
        ("rename", "D", (re.compile(r"^rename(?:\s+the)?\s+(?:(?:file|folder|directory)\s+)?", re.I),)),
        ("move", "D", (re.compile(r"^move(?:\s+the)?\s+(?:(?:file|folder|directory)\s+)?", re.I),)),
        ("delete", "E", (re.compile(r"^(?:delete|remove)(?:\s+the)?\s+(?:file|folder|directory)\b", re.I),)),
        (
            "path",
            "A",
            (
                re.compile(
                    r"^(?:where\s+is\s+(?:it|that|that\s+file|the\s+file)|show\s+(?:me\s+)?(?:the\s+)?full\s+path|copy\s+(?:the\s+)?path)[.!?]*$",
                    re.I,
                ),
                re.compile(r"^(?:show me|display)\s+(?:(?:that|the)\s+(?:file|folder|directory|item)|.+?)[.!?]*$", re.I),
            ),
        ),
    )

    def __init__(self, automation_bridge: Any | None = None, *, risk_service: CommandRiskService | None = None) -> None:
        self.automation_bridge = getattr(automation_bridge, "file_domain", automation_bridge)
        self.risk_service = risk_service or CommandRiskService()

    def can_handle(self, intent: str) -> bool:
        normalized = str(intent or "").strip().lower()
        return normalized in {"file", "files", "local_files"} or self.operation_for(normalized) is not None

    def operation_for(self, command: str) -> dict[str, str] | None:
        text = str(command or "").strip()
        for operation, group, patterns in self.OPERATION_PATTERNS:
            if any(pattern.search(text) for pattern in patterns):
                safety = "CRITICAL" if operation == "delete" else "MEDIUM" if operation in {"create", "update", "rename", "move"} else "LOW"
                return {"operation": operation, "group": group, "safety_level": safety}
        return None

    def classify_risk(self, command: str) -> ToolRisk:
        risk = self.risk_service.classify(command, command_action="automation")
        return ToolRisk(level=risk.risk_level, step_up_required=risk.step_up_required, reasons=list(risk.reasons))

    def policy_args(self, action: str, args: dict[str, Any], context: ToolContext | None = None) -> dict[str, Any]:
        if self.automation_bridge is None:
            return {}
        aliases = getattr(self.automation_bridge, "USER_PATH_ALIASES", {}) or {}
        safe_roots = [
            str(path)
            for alias, path in aliases.items()
            if str(alias).strip().lower() in {"desktop", "documents", "downloads"} and path
        ]
        return {"_safe_roots": safe_roots}

    def execute(self, context: ToolContext) -> dict[str, Any]:
        planned_step = context.payload.get("planned_step") if isinstance(context.payload.get("planned_step"), dict) else {}
        planned_action = str(context.payload.get("action") or planned_step.get("action") or "").strip()
        action_name = planned_action or "legacy_command"
        if planned_action:
            planned_result = self._execute_planned_action(planned_action, dict(context.payload.get("args") or {}))
            if planned_result is not None:
                planned_result["tool_name"] = self.name
                log_boundary(logger, "TOOL", name="FileTool", action=action_name, delegate="native" if planned_action else "file_compatibility_runner", status=self._result_status(planned_result), target=planned_result.get("path") or "")
                return planned_result

        operation = self.operation_for(context.command)
        if operation is None and not self.can_handle(context.intent):
            return None
        if self.automation_bridge:
            result = FileCompatibilityRunner(self.automation_bridge).execute(context.command, context=context)
            if result is None:
                return None
            normalized = normalize_automation_response(result)
            normalized["tool_name"] = self.name
            normalized["file_operation"] = operation
            log_boundary(logger, "TOOL", name="FileTool", action=(operation or {}).get("operation") or action_name, delegate="file_compatibility_runner", status=self._result_status(normalized), target=context.command)
            return normalized
        result = {"success": False, "action": "unsupported", "message": "File tool is not wired yet."}
        log_boundary(logger, "TOOL", name="FileTool", action=action_name, delegate="file_compatibility_runner", status="failed", target="")
        return result

    def _execute_planned_action(self, action: str, args: dict[str, Any]) -> dict[str, Any] | None:
        if self.automation_bridge is None:
            return {"success": False, "action": action, "message": "File tool is not wired yet."}

        handlers = {
            "resolve_path": self._planned_resolve_path,
            "create_file": self._planned_create_file,
            "write_file": self._planned_write_file,
            "append_file": self._planned_append_file,
            "create_folder": self._planned_create_folder,
            "verify_exists": self._planned_verify_exists,
            "read_file": self._planned_read_file,
            "list_files": self._planned_list_files,
            "search_files": self._planned_search_files,
            "rename_file": self._planned_rename_file,
            "move_file": self._planned_move_file,
            "delete_file": self._planned_delete_file,
            "delete_folder": self._planned_delete_folder,
        }
        handler = handlers.get(action)
        return handler(args) if handler is not None else None

    def _planned_resolve_path(self, args: dict[str, Any]) -> dict[str, Any]:
        location = str(args.get("location") or args.get("path") or "").strip()
        try:
            path = self.automation_bridge._resolve_laptop_path(location)
        except ValueError as exc:
            return {"success": False, "action": "resolve_path", "message": str(exc)}
        return {
            "success": True,
            "action": "resolve_path",
            "message": f"Resolved {self.automation_bridge._display_target_name(path)}.",
            "data": {"path": str(path)},
            "path": str(path),
        }

    def _planned_create_file(self, args: dict[str, Any]) -> dict[str, Any]:
        parent = args.get("parent")
        filename = str(args.get("filename") or args.get("name") or "").strip()
        if not parent or not filename:
            return {"success": False, "action": "create_file", "message": "Tell me the folder and file name to create."}
        try:
            parent_path = self.automation_bridge._resolve_laptop_path(str(parent))
        except ValueError as exc:
            return {"success": False, "action": "create_file", "message": str(exc)}

        path = parent_path / Path(filename.replace("/", "\\")).name
        if path.exists():
            return {
                "success": False,
                "action": "create_file",
                "message": f"{self.automation_bridge._display_file_name(path)} already exists.",
            }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=False)
        except Exception as exc:
            return {
                "success": False,
                "action": "create_file",
                "message": f"Could not create {self.automation_bridge._display_file_name(path)} at {path}: {exc}",
            }
        self.automation_bridge._last_file_target = path
        return {
            "success": True,
            "action": "create_file",
            "message": f"Created {self.automation_bridge._display_file_name(path)} in {self.automation_bridge._display_parent_name(path)}.",
            "data": {"path": str(path)},
            "path": str(path),
        }

    def _planned_write_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path_value = args.get("path")
        content = str(args.get("content") or "")
        overwrite = bool(args.get("overwrite", False))
        if not path_value:
            return {"success": False, "action": "write_file", "message": "Tell me which file to write."}
        try:
            path = self.automation_bridge._resolve_file_target(str(path_value))
        except ValueError as exc:
            return {"success": False, "action": "write_file", "message": str(exc)}
        if path.exists() and path.is_dir():
            return {"success": False, "action": "write_file", "message": "That path is a folder, not a file."}
        if path.exists() and path.stat().st_size > 0 and not overwrite:
            return {
                "success": False,
                "action": "write_file",
                "message": f"{self.automation_bridge._display_file_name(path)} already has content. I did not overwrite it.",
            }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except Exception as exc:
            return {
                "success": False,
                "action": "write_file",
                "message": f"Could not write {self.automation_bridge._display_file_name(path)}: {exc}",
            }
        self.automation_bridge._last_file_target = path
        return {
            "success": True,
            "action": "write_file",
            "message": f"Wrote content to {self.automation_bridge._display_file_name(path)}.",
            "data": {"path": str(path), "content": content},
            "path": str(path),
            "content": content,
        }

    def _planned_append_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path_value = args.get("path")
        content = str(args.get("content") or "")
        if not path_value:
            return {"success": False, "action": "append_file", "message": "Tell me which file to update."}
        try:
            path = self.automation_bridge._resolve_file_target(str(path_value))
        except ValueError as exc:
            return {"success": False, "action": "append_file", "message": str(exc)}
        if path.exists() and path.is_dir():
            return {"success": False, "action": "append_file", "message": "That path is a folder, not a file."}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(content)
        except Exception as exc:
            return {"success": False, "action": "append_file", "message": f"Could not update {path.name}: {exc}"}
        self.automation_bridge._last_file_target = path
        return {
            "success": True,
            "action": "append_file",
            "message": f"Updated {self.automation_bridge._display_file_name(path)}.",
            "data": {"path": str(path), "content": content},
            "path": str(path),
            "content": content,
        }

    def _planned_create_folder(self, args: dict[str, Any]) -> dict[str, Any]:
        parent = args.get("parent")
        name = str(args.get("name") or "").strip()
        if not parent or not name:
            return {"success": False, "action": "create_folder", "message": "Tell me the folder location and name."}
        try:
            parent_path = self.automation_bridge._resolve_laptop_path(str(parent))
        except ValueError as exc:
            return {"success": False, "action": "create_folder", "message": str(exc)}
        path = parent_path / Path(name.replace("/", "\\")).name
        if path.exists() and not path.is_dir():
            return {"success": False, "action": "create_folder", "message": "That path is a file, not a folder."}
        try:
            path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return {"success": False, "action": "create_folder", "message": f"Could not create folder {path.name} at {path}: {exc}"}
        self.automation_bridge._last_folder_target = path
        return {
            "success": True,
            "action": "create_folder",
            "message": f"Folder {self.automation_bridge._display_target_name(path)} created at {path}.",
            "data": {"path": str(path)},
            "path": str(path),
        }

    def _planned_verify_exists(self, args: dict[str, Any]) -> dict[str, Any]:
        path_value = args.get("path")
        expected_content = args.get("expected_content")
        if not path_value:
            return {"success": False, "action": "verify_exists", "message": "Tell me which path to verify."}
        try:
            path = self.automation_bridge._resolve_laptop_path(str(path_value))
        except ValueError as exc:
            return {"success": False, "action": "verify_exists", "message": str(exc)}
        if not path.exists():
            return {"success": False, "action": "verify_exists", "message": f"{path.name} does not exist."}
        content = None
        if expected_content is not None:
            if not path.is_file():
                return {"success": False, "action": "verify_exists", "message": "That is a folder, not a file."}
            content = path.read_text(encoding="utf-8", errors="replace")
            if content != str(expected_content):
                return {"success": False, "action": "verify_exists", "message": f"{path.name} exists but its content did not match."}
        return {
            "success": True,
            "action": "verify_exists",
            "message": f"Verified {path.name}.",
            "data": {"path": str(path), "content": content},
            "path": str(path),
            "content": content,
        }

    def _planned_read_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path_or_name = str(args.get("path_or_name") or args.get("path") or "").strip()
        if not path_or_name:
            return {"success": False, "action": "read_file", "message": "Tell me which file to read."}
        result = self.automation_bridge._read_file(path_or_name)
        normalized = normalize_automation_response(result)
        if not bool(normalized.get("success")):
            return normalized
        try:
            path = self.automation_bridge._resolve_existing_target(path_or_name, target_kind="file")
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            path = None
            content = str(normalized.get("message") or "")
        data = {"content": content}
        if path is not None:
            data["path"] = str(path)
        normalized["data"] = {**dict(normalized.get("data") or {}), **data}
        normalized.update(data)
        return normalized

    def _planned_list_files(self, args: dict[str, Any]) -> dict[str, Any]:
        return normalize_automation_response(self.automation_bridge._list_files(str(args.get("folder") or args.get("location") or "downloads")))

    def _planned_search_files(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query") or "").strip()
        if not query and not bool(args.get("recent") or args.get("large")):
            result = ClarificationService.build("missing_file_query", "What file name or content should I search for?")
            result["action"] = "search_files"
            result["missing_query"] = True
            return result
        return normalize_automation_response(
            self.automation_bridge._find_files(
                query or "*",
                str(args.get("folder") or args.get("location") or "home"),
                recent=bool(args.get("recent")),
                large=bool(args.get("large")),
            )
        )

    @staticmethod
    def _result_status(result: dict[str, Any]) -> str:
        if result.get("status") == "clarification_required" or result.get("requires_followup") or result.get("action") == "clarification_required":
            return "clarification_required"
        return "success" if result.get("success") else "failed"

    def _planned_rename_file(self, args: dict[str, Any]) -> dict[str, Any]:
        return normalize_automation_response(self.automation_bridge._rename_target(str(args.get("source") or ""), str(args.get("new_name") or ""), target_kind="file"))

    def _planned_move_file(self, args: dict[str, Any]) -> dict[str, Any]:
        return normalize_automation_response(self.automation_bridge._move_target(str(args.get("source") or ""), str(args.get("destination") or ""), target_kind="file"))

    def _planned_delete_file(self, args: dict[str, Any]) -> dict[str, Any]:
        if args.get("confirmed"):
            return self._confirmed_delete(str(args.get("path") or args.get("path_or_name") or ""), target_kind="file")
        return normalize_automation_response(self.automation_bridge._delete_file(str(args.get("path") or args.get("path_or_name") or "")))

    def _planned_delete_folder(self, args: dict[str, Any]) -> dict[str, Any]:
        if args.get("confirmed"):
            return self._confirmed_delete(str(args.get("path") or args.get("path_or_name") or ""), target_kind="folder")
        return normalize_automation_response(self.automation_bridge._delete_folder(str(args.get("path") or args.get("path_or_name") or "")))

    def _confirmed_delete(self, path_text: str, *, target_kind: str) -> dict[str, Any]:
        if self.automation_bridge is None:
            return {"success": False, "action": f"delete_{target_kind}", "message": "File tool is not wired yet."}
        try:
            path = self.automation_bridge._resolve_existing_target(path_text, target_kind=target_kind)
        except ValueError as exc:
            return {"success": False, "action": f"delete_{target_kind}", "message": str(exc)}
        result = move_to_recycle_bin(
            path,
            send_to_trash=send2trash,
            is_protected_path=self.automation_bridge._is_protected_path,
            display_target_name=self.automation_bridge._display_target_name,
        )
        normalized = normalize_automation_response(result)
        normalized["tool_name"] = self.name
        return normalized
