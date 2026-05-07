from __future__ import annotations

import logging
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import Callable, Dict, Iterable

from config import BASE_DIR as CONFIG_BASE_DIR
from app.orchestrator.action_plan import ActionPlan, ActionStep
from app.orchestrator.tool_executor import ToolExecutor
from app.services.contact_match_service import ContactCandidate, ContactMatchService
from app.services.message_action_service import MessageActionService
from app.tools.base import ToolContext

try:
    from send2trash import send2trash
    SEND2TRASH_IMPORT_ERROR = None
except Exception as exc:
    send2trash = None
    SEND2TRASH_IMPORT_ERROR = exc


logger = logging.getLogger("J.A.R.V.I.S")


def _runtime_base_dir() -> Path:
    try:
        from app.services import automation_service as automation_module

        return automation_module.BASE_DIR
    except Exception:
        return CONFIG_BASE_DIR



class AutomationFileCompatibility:

    def _sanitize_file_reference(self, path_text: str) -> str:
            cleaned = (path_text or "").strip().strip('"').strip("'")
            cleaned = re.sub(r"\bin it\b", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\b(?:uh|um|er|ah)\b", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"^(?:for me\s+)?(?:please\s+)?", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\bdot\s+([a-z0-9]{1,5})\b", r".\1", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            return cleaned.rstrip(".!?")


    def _strip_named_prefix(self, value: str) -> str:
            value = re.sub(r"^(?:named|called|name)\s+(?:the\s+)?", "", value, flags=re.IGNORECASE)
            return value.strip()


    def _clean_location_phrase(self, value: str) -> str:
            cleaned = (value or "").strip().strip('"').strip("'")
            cleaned = re.sub(
                r"^(?:the\s+)?(?:folder\s+)?(?:path\s+)?(?:location\s+)?",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )
            cleaned = re.sub(
                r"^(?:on|in|at|inside|under|from)\s+",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            return cleaned.rstrip(".!?")


    def _clean_file_name(self, value: str) -> str:
            cleaned = self._strip_named_prefix(value or "")
            cleaned = re.sub(r"^the\s+", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"^(?:the\s+)?(?:file|folder|directory)\s+", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s+\.", ".", cleaned)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            return cleaned.rstrip(".!?")


    def _looks_like_windows_absolute_path(self, value: str) -> bool:
            return bool(re.match(r'^[A-Za-z]:[\\/]', (value or "").strip()))


    def _combine_location_and_name(self, location_text: str, name_text: str) -> Path:
            location_path = self._resolve_path(self._clean_location_phrase(location_text))
            file_name = self._clean_file_name(name_text)
            return location_path / Path(file_name.replace("/", "\\"))


    def _extract_path_from_sentence(self, text: str) -> Path | None:
            cleaned = self._sanitize_file_reference(text)
            if not cleaned:
                return None

            absolute_match = re.search(r'([A-Za-z]:[\\/][^"\']*)$', cleaned)
            if absolute_match:
                return Path(absolute_match.group(1).strip().replace("/", "\\"))

            patterns = [
                r"^(?P<name>.+?)\s+(?:on|in|at|inside|under|from)\s+(?P<location>.+)$",
                r"^(?:on|in|at|inside|under|from)\s+(?P<location>.+?)\s+(?:named|called|name)\s+(?P<name>.+)$",
                r"^(?P<location>desktop|documents|downloads|pictures|videos|music|home)\s+(?:named|called|name)\s+(?P<name>.+)$",
                r"^(?:named|called|name)\s+(?P<name>.+?)\s+(?:on|in|at|inside|under|from)\s+(?P<location>.+)$",
            ]
            for pattern in patterns:
                match = re.match(pattern, cleaned, flags=re.IGNORECASE)
                if not match:
                    continue

                location = match.groupdict().get("location") or ""
                name = match.groupdict().get("name") or ""
                if location and name:
                    return self._combine_location_and_name(location, name)

            return None


    def _resolve_user_alias_path(self, path_text: str) -> Path | None:
            cleaned = self._clean_location_phrase(path_text)
            if not cleaned:
                return None

            for alias, base_path in self.USER_PATH_ALIASES.items():
                suffix_pattern = (
                    rf"^(?P<name>.+?)\s+(?:on|in|at|inside|under)\s+(?:the\s+)?{alias}(?:\s+folder)?$"
                )
                suffix_match = re.match(suffix_pattern, cleaned, flags=re.IGNORECASE)
                if suffix_match:
                    file_name = self._strip_named_prefix(suffix_match.group("name") or "")
                    if file_name:
                        return base_path / Path(file_name.replace("/", "\\"))

                pattern = (
                    rf"^(?:(?:on|in|at|inside|under)\s+(?:the\s+)?)?{alias}"
                    rf"(?:[\\/]|(?:\s+(?:folder\s+)?))?(.*)$"
                )
                match = re.match(pattern, cleaned, flags=re.IGNORECASE)
                if not match:
                    continue

                remainder = self._strip_named_prefix(match.group(1) or "")
                if not remainder:
                    return base_path

                remainder = remainder.lstrip("\\/ ").replace("/", "\\")
                return base_path / Path(remainder)

            return None


    def _resolve_path(self, path_text: str) -> Path:
            cleaned = self._sanitize_file_reference(path_text)
            extracted_path = self._extract_path_from_sentence(cleaned)
            if extracted_path is not None:
                return extracted_path

            alias_path = self._resolve_user_alias_path(cleaned)
            if alias_path is not None:
                return alias_path

            path_candidate = self._clean_location_phrase(cleaned)
            path = Path(path_candidate.replace("/", "\\"))
            if path.is_absolute() or self._looks_like_windows_absolute_path(path_candidate):
                return path

            return _runtime_base_dir() / path


    def _resolve_file_target(self, path_text: str) -> Path:
            cleaned = self._sanitize_file_reference(path_text)
            lowered = cleaned.lower()

            if lowered in {"that file", "the file", "it"}:
                if self._last_file_target is None:
                    raise ValueError("I don't know which file you mean yet. Tell me the file name once first.")
                return self._last_file_target

            return self._resolve_laptop_path(cleaned)


    def _resolve_folder_target(self, path_text: str) -> Path:
            cleaned = self._sanitize_file_reference(path_text)
            lowered = cleaned.lower()

            if lowered in {"that folder", "the folder", "that directory", "the directory", "it"}:
                if self._last_folder_target is None:
                    raise ValueError("I don't know which folder you mean yet. Tell me the folder name once first.")
                return self._last_folder_target

            return self._resolve_laptop_path(cleaned)


    def _resolve_existing_target(self, path_text: str, target_kind: str = "") -> Path:
            cleaned = self._sanitize_file_reference(path_text)
            lowered = cleaned.lower()

            if target_kind == "file" and lowered in {"that file", "the file", "it"}:
                if self._last_file_target is None:
                    raise ValueError("I don't know which file you mean yet. Tell me the file name once first.")
                return self._last_file_target

            if target_kind in {"folder", "directory"} and lowered in {"that folder", "the folder", "that directory", "the directory", "it"}:
                if self._last_folder_target is None:
                    raise ValueError("I don't know which folder you mean yet. Tell me the folder name once first.")
                return self._last_folder_target

            if lowered in {"it", "that", "that item", "the item"}:
                if self._last_file_target is not None and self._last_file_target.exists():
                    return self._last_file_target
                if self._last_folder_target is not None and self._last_folder_target.exists():
                    return self._last_folder_target
                raise ValueError("I don't know which file or folder you mean yet. Tell me the name once first.")

            path = self._resolve_laptop_path(cleaned)
            if target_kind == "file" and path.exists() and path.is_dir():
                raise ValueError("That is a folder, not a file.")
            if target_kind in {"folder", "directory"} and path.exists() and not path.is_dir():
                raise ValueError("That is a file, not a folder.")
            return path


    def _resolve_laptop_path(self, path_text: str) -> Path:
            path = self._resolve_path(path_text).resolve()
            if self._is_protected_path(path):
                raise ValueError("That location is protected. Jarvis cannot access Windows or critical system folders.")
            return path


    def _create_file_in_folder(self, folder_text: str, name_text: str, content: str) -> Dict[str, str | bool]:
            try:
                folder = self._resolve_folder_target(folder_text)
            except ValueError as exc:
                return {"success": False, "action": "create_file", "message": str(exc)}

            file_name = self._clean_file_name(name_text)
            if not file_name:
                return {"success": False, "action": "create_file", "message": "Tell me the file name you want to use."}

            path = folder / Path(file_name.replace("/", "\\"))
            return self._create_file(str(path), content)


    def _create_file_or_ask_for_location(self, path_text: str, content: str) -> Dict[str, str | bool]:
            cleaned = self._sanitize_file_reference(path_text)
            if not cleaned:
                return {"success": False, "action": "create_file", "message": "Tell me the file name you want to use."}

            if not self._looks_like_explicit_path_request(cleaned):
                file_name = self._clean_file_name(cleaned)
                if not file_name:
                    return {"success": False, "action": "create_file", "message": "Tell me the file name you want to use."}
                self._pending_create_file = {
                    "name": file_name,
                    "content": content or "",
                }
                return {
                    "success": False,
                    "action": "create_file_location_needed",
                    "message": f"Where should I save {file_name}?",
                }

            return self._create_file(cleaned, content)


    def _handle_create_file_location_followup(self, command: str) -> Dict[str, str | bool]:
            pending = self._pending_create_file
            if not pending:
                return {
                    "success": False,
                    "action": "create_file",
                    "message": "I don't have a pending file to save.",
                }

            reply = self._normalize_spoken_command(command)
            lowered = reply.lower().rstrip(".!?")
            if lowered in {"cancel", "stop", "never mind", "no", "skip"}:
                self._pending_create_file = None
                return {
                    "success": False,
                    "action": "create_file",
                    "message": "File creation cancelled.",
                }

            try:
                folder = self._resolve_folder_target(reply)
            except ValueError as exc:
                return {"success": False, "action": "create_file", "message": str(exc)}

            self._pending_create_file = None
            file_name = str(pending.get("name", "")).strip()
            content = str(pending.get("content", ""))
            steps = [
                ActionStep("step1", "file", "file", "create_file", {"parent": str(folder), "filename": file_name}),
            ]
            if content:
                steps.append(
                    ActionStep(
                        "step2",
                        "file",
                        "file",
                        "write_file",
                        {"path": "{step1.path}", "content": content, "overwrite": False},
                        depends_on=["step1"],
                    )
                )
                steps.append(
                    ActionStep(
                        "step3",
                        "file",
                        "file",
                        "verify_exists",
                        {"path": "{step1.path}", "expected_content": content},
                        depends_on=["step1", "step2"],
                    )
                )
            target_path = folder / Path(file_name.replace("/", "\\"))
            plan_command = f"create file {target_path}"
            executor = ToolExecutor(registry=self._build_automation_tool_registry(), enforce_policy=True)
            return executor.execute(
                ActionPlan(
                    original_text=plan_command,
                    steps=steps,
                    is_multistep=bool(content),
                ),
                ToolContext(
                    command=plan_command,
                    intent="file",
                    session_id=self._active_session_id,
                    request_id=self._active_turn_id,
                    payload={"turn_id": self._active_turn_id} if self._active_turn_id else {},
                    security_state={"step_up_verified": self._active_step_up_verified},
                ),
            )


    def _resolve_openable_path(self, target: str) -> Path | None:
            cleaned = self._sanitize_file_reference(target)
            lowered = cleaned.lower()

            if lowered in {"that folder", "the folder", "that directory", "the directory"}:
                return self._last_folder_target if self._last_folder_target and self._last_folder_target.exists() else None

            if lowered in {"that file", "the file"}:
                return self._last_file_target if self._last_file_target and self._last_file_target.exists() else None

            if lowered == "it":
                if self._last_folder_target and self._last_folder_target.exists():
                    return self._last_folder_target
                if self._last_file_target and self._last_file_target.exists():
                    return self._last_file_target
                return None

            if not self._looks_like_explicit_path_request(cleaned):
                return None

            try:
                path = self._resolve_laptop_path(cleaned)
            except ValueError:
                return None

            return path if path.exists() else None


    def _looks_like_explicit_path_request(self, target: str) -> bool:
            cleaned = (target or "").strip().lower()
            if not cleaned:
                return False

            if cleaned.startswith(("on ", "in ", "at ", "inside ", "under ")):
                return True

            if self._looks_like_windows_absolute_path(cleaned):
                return True

            if any(token in cleaned for token in ("\\", "/", ":")):
                return True

            if any(alias in cleaned for alias in self.USER_PATH_ALIASES):
                return True

            if any(keyword in cleaned for keyword in ("folder", "directory", "file")):
                return True

            return False


    def _display_file_name(self, path: Path) -> str:
            return path.name or str(path)


    def _display_target_name(self, path: Path) -> str:
            return path.name or str(path)


    def _display_parent_name(self, path: Path) -> str:
            parent = path.parent
            try:
                resolved_parent = parent.resolve()
                for alias, alias_path in self.USER_PATH_ALIASES.items():
                    try:
                        if resolved_parent == alias_path.resolve():
                            return alias.capitalize()
                    except Exception:
                        continue
                base_dir = _runtime_base_dir()
                if resolved_parent == base_dir.resolve():
                    return base_dir.name
            except Exception:
                pass
            return parent.name or str(parent)


    def _remember_target(self, path: Path) -> None:
            if path.exists() and path.is_dir():
                self._last_folder_target = path
            else:
                self._last_file_target = path


    def _create_file(self, path_text: str, content: str) -> Dict[str, str | bool]:
            try:
                path = self._resolve_file_target(path_text)
            except ValueError as exc:
                return {"success": False, "action": "create_file", "message": str(exc)}

            if path.exists() and path.is_dir():
                return {
                    "success": False,
                    "action": "create_file",
                    "message": "That path is a folder, not a file.",
                }

            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            except Exception as exc:
                return {
                    "success": False,
                    "action": "create_file",
                    "message": f"Could not create {self._display_file_name(path)} at {path}: {exc}",
                }

            self._last_file_target = path
            return {
                "success": True,
                "action": "create_file",
                "message": f"Created {self._display_file_name(path)} in {self._display_parent_name(path)}.",
            }


    def _create_folder(self, path_text: str) -> Dict[str, str | bool]:
            try:
                path = self._resolve_folder_target(path_text)
            except ValueError as exc:
                return {"success": False, "action": "create_folder", "message": str(exc)}

            if path.exists() and not path.is_dir():
                return {
                    "success": False,
                    "action": "create_folder",
                    "message": "That path is a file, not a folder.",
                }

            try:
                path.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                return {
                    "success": False,
                    "action": "create_folder",
                    "message": f"Could not create folder {self._display_target_name(path)} at {path}: {exc}",
                }

            self._last_folder_target = path
            return {
                "success": True,
                "action": "create_folder",
                "message": f"Folder {self._display_target_name(path)} created at {path}.",
            }


    def create_file_with_content(self, path_text: str, content: str) -> Dict[str, str | bool]:
            return self._create_file(path_text, content)


    def _format_size(self, byte_count: int) -> str:
            size = float(max(byte_count, 0))
            for unit in ("B", "KB", "MB", "GB", "TB"):
                if size < 1024 or unit == "TB":
                    return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
                size /= 1024
            return f"{size:.1f} TB"


    def _list_files(self, folder_text: str = "downloads", limit: int = 30) -> Dict[str, str | bool]:
            try:
                folder = self._resolve_folder_target(folder_text or "downloads")
            except ValueError as exc:
                return {"success": False, "action": "list_files", "message": str(exc)}

            if not folder.exists():
                return {"success": False, "action": "list_files", "message": f"{self._display_target_name(folder)} does not exist."}
            if not folder.is_dir():
                return {"success": False, "action": "list_files", "message": "That is a file, not a folder."}

            try:
                items = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except PermissionError:
                return {"success": False, "action": "list_files", "message": f"Permission denied: {folder}."}
            except Exception as exc:
                return {"success": False, "action": "list_files", "message": f"Could not list {folder}: {exc}"}

            visible_items = [item for item in items if not item.name.startswith(".")]
            lines = []
            for item in visible_items[:limit]:
                if item.is_dir():
                    lines.append(f"[folder] {item.name}/")
                else:
                    try:
                        size = self._format_size(item.stat().st_size)
                    except Exception:
                        size = "unknown size"
                    lines.append(f"[file] {item.name} ({size})")

            self._last_folder_target = folder
            if not lines:
                message = f"{self._display_target_name(folder)} is empty."
            else:
                suffix = f"\n... and {len(visible_items) - limit} more item(s)." if len(visible_items) > limit else ""
                message = f"Files in {self._display_target_name(folder)}:\n" + "\n".join(lines) + suffix
            return {"success": True, "action": "list_files", "message": message}


    def _read_file(self, path_text: str, max_chars: int = 4000) -> Dict[str, str | bool]:
            try:
                path = self._resolve_existing_target(path_text, target_kind="file")
            except ValueError as exc:
                return {"success": False, "action": "read_file", "message": str(exc)}

            if not path.exists():
                return {"success": False, "action": "read_file", "message": f"{self._display_file_name(path)} does not exist."}
            if not path.is_file():
                return {"success": False, "action": "read_file", "message": "That is a folder, not a file."}
            try:
                if path.stat().st_size > 2_000_000:
                    return {"success": False, "action": "read_file", "message": "That file is too large to read safely in chat."}
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                return {"success": False, "action": "read_file", "message": f"Could not read {self._display_file_name(path)}: {exc}"}

            self._last_file_target = path
            if len(content) > max_chars:
                content = content[:max_chars].rstrip() + f"\n\n... truncated at {max_chars} characters."
            return {
                "success": True,
                "action": "read_file",
                "message": f"{self._display_file_name(path)}:\n{content}" if content else f"{self._display_file_name(path)} is empty.",
            }


    def _find_files(self, query_text: str, folder_text: str = "home", limit: int = 20) -> Dict[str, str | bool]:
            try:
                folder = self._resolve_folder_target(folder_text or "home")
            except ValueError as exc:
                return {"success": False, "action": "find_files", "message": str(exc)}

            if not folder.exists():
                return {"success": False, "action": "find_files", "message": f"{self._display_target_name(folder)} does not exist."}
            if not folder.is_dir():
                return {"success": False, "action": "find_files", "message": "That is a file, not a folder."}

            query = self._sanitize_file_reference(query_text).lower()
            extension = ""
            extension_aliases = {
                "pdf": ".pdf",
                "pdfs": ".pdf",
                "document": ".docx",
                "documents": ".docx",
                "word": ".docx",
                "text": ".txt",
                "notes": ".txt",
                "image": ".jpg",
                "images": ".jpg",
                "photo": ".jpg",
                "photos": ".jpg",
                "video": ".mp4",
                "videos": ".mp4",
            }
            for token, ext in extension_aliases.items():
                if re.search(rf"\b{re.escape(token)}\b", query):
                    extension = ext
                    break
            ext_match = re.search(r"\.([a-z0-9]{1,8})\b", query)
            if ext_match:
                extension = "." + ext_match.group(1)

            name_query = re.sub(
                r"\b(find|files?|all|the|named|called|documents?|pdfs?|images?|photos?|videos?|music|text|notes)\b",
                " ",
                query,
            )
            name_query = re.sub(r"\.[a-z0-9]{1,8}\b", " ", name_query)
            name_query = re.sub(r"\s+", " ", name_query).strip()

            pattern = f"*{extension}" if extension else "*"
            results = []
            scanned = 0
            try:
                for item in folder.rglob(pattern):
                    scanned += 1
                    if scanned > 8000:
                        break
                    if not item.is_file():
                        continue
                    if name_query and name_query not in item.name.lower():
                        continue
                    try:
                        size = self._format_size(item.stat().st_size)
                    except Exception:
                        size = "unknown size"
                    results.append(f"{item.name} ({size}) - {item.parent}")
                    if len(results) >= limit:
                        break
            except PermissionError:
                return {"success": False, "action": "find_files", "message": f"Permission denied while searching {folder}."}
            except Exception as exc:
                return {"success": False, "action": "find_files", "message": f"Could not search {folder}: {exc}"}

            self._last_folder_target = folder
            if not results:
                return {"success": True, "action": "find_files", "message": f"No matching files found in {self._display_target_name(folder)}."}
            return {"success": True, "action": "find_files", "message": "Found files:\n" + "\n".join(results)}


    def _largest_files(self, folder_text: str = "home", limit: int = 10) -> Dict[str, str | bool]:
            try:
                folder = self._resolve_folder_target(folder_text or "home")
            except ValueError as exc:
                return {"success": False, "action": "largest_files", "message": str(exc)}

            if not folder.exists():
                return {"success": False, "action": "largest_files", "message": f"{self._display_target_name(folder)} does not exist."}
            if not folder.is_dir():
                return {"success": False, "action": "largest_files", "message": "That is a file, not a folder."}

            candidates: list[tuple[int, Path]] = []
            scanned = 0
            try:
                for item in folder.rglob("*"):
                    scanned += 1
                    if scanned > 8000:
                        break
                    if item.is_file():
                        try:
                            candidates.append((item.stat().st_size, item))
                        except Exception:
                            continue
            except PermissionError:
                return {"success": False, "action": "largest_files", "message": f"Permission denied while scanning {folder}."}
            except Exception as exc:
                return {"success": False, "action": "largest_files", "message": f"Could not scan {folder}: {exc}"}

            candidates.sort(reverse=True, key=lambda pair: pair[0])
            lines = [f"{path.name} ({self._format_size(size)}) - {path.parent}" for size, path in candidates[:limit]]
            if not lines:
                return {"success": True, "action": "largest_files", "message": f"No files found in {self._display_target_name(folder)}."}
            return {"success": True, "action": "largest_files", "message": "Largest files:\n" + "\n".join(lines)}


    def _organize_folder_preview(self, folder_text: str = "downloads") -> Dict[str, str | bool]:
            try:
                folder = self._resolve_folder_target(folder_text or "downloads")
            except ValueError as exc:
                return {"success": False, "action": "organize_folder_preview", "message": str(exc)}

            if not folder.exists():
                return {"success": False, "action": "organize_folder_preview", "message": f"{self._display_target_name(folder)} does not exist."}
            if not folder.is_dir():
                return {"success": False, "action": "organize_folder_preview", "message": "That is a file, not a folder."}

            categories = {
                "Images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"},
                "Documents": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".csv", ".xlsx", ".pptx"},
                "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
                "Installers": {".exe", ".msi", ".apk", ".dmg", ".pkg"},
                "Videos": {".mp4", ".mov", ".avi", ".mkv", ".webm"},
                "Audio": {".mp3", ".wav", ".flac", ".m4a", ".ogg"},
            }
            counts = {name: 0 for name in categories}
            counts["Other"] = 0

            try:
                for item in folder.iterdir():
                    if not item.is_file():
                        continue
                    suffix = item.suffix.lower()
                    matched = False
                    for category, suffixes in categories.items():
                        if suffix in suffixes:
                            counts[category] += 1
                            matched = True
                            break
                    if not matched:
                        counts["Other"] += 1
            except Exception as exc:
                return {"success": False, "action": "organize_folder_preview", "message": f"Could not inspect {folder}: {exc}"}

            lines = [f"{name}: {count}" for name, count in counts.items() if count]
            if not lines:
                message = f"{self._display_target_name(folder)} has no files to organize."
            else:
                message = (
                    f"Organization preview for {self._display_target_name(folder)}:\n"
                    + "\n".join(lines)
                    + "\nNo files were moved."
                )
            self._last_folder_target = folder
            return {"success": True, "action": "organize_folder_preview", "message": message}


    def _update_file(self, path_text: str, content: str, append: bool = True) -> Dict[str, str | bool]:
            if not content:
                return {
                    "success": False,
                    "action": "update_file",
                    "message": "Tell me what text you want me to add.",
                }

            try:
                path = self._resolve_file_target(path_text)
            except ValueError as exc:
                return {"success": False, "action": "update_file", "message": str(exc)}

            if path.exists() and path.is_dir():
                return {
                    "success": False,
                    "action": "update_file",
                    "message": "That is a folder, not a file.",
                }

            path.parent.mkdir(parents=True, exist_ok=True)

            existing = ""
            if path.exists():
                try:
                    existing = path.read_text(encoding="utf-8")
                except Exception:
                    existing = ""

            if append and existing:
                separator = "" if existing.endswith(("\n", "\r")) else "\n"
                new_content = existing + separator + content
            elif append and not existing:
                new_content = content
            else:
                new_content = content

            try:
                path.write_text(new_content, encoding="utf-8")
            except Exception as exc:
                return {
                    "success": False,
                    "action": "update_file",
                    "message": f"Could not update {self._display_file_name(path)} at {path}: {exc}",
                }

            self._last_file_target = path

            return {
                "success": True,
                "action": "update_file",
                "message": f"Updated {self._display_file_name(path)} in {self._display_parent_name(path)}.",
            }


    def _show_last_file_path(self) -> Dict[str, str | bool]:
            if self._last_file_target is None:
                return {
                    "success": False,
                    "action": "show_path",
                    "message": "I don't know which file you mean yet.",
                }
            return {
                "success": True,
                "action": "show_path",
                "message": f"{self._display_file_name(self._last_file_target)} is at {self._last_file_target}.",
            }


    def _delete_file(self, path_text: str) -> Dict[str, str | bool]:
            try:
                path = self._resolve_existing_target(path_text, target_kind="file")
            except ValueError as exc:
                return {"success": False, "action": "delete_file", "message": str(exc)}

            if not path.exists():
                return {
                    "success": False,
                    "action": "delete_file",
                    "message": f"{self._display_file_name(path)} does not exist.",
                }

            if path.is_dir():
                return {
                    "success": False,
                    "action": "delete_file",
                    "message": "That is a folder, not a file.",
                }

            self._pending_delete_target = path
            return {
                "success": False,
                "action": "delete_file",
                "message": f"Do you want me to delete {self._display_file_name(path)}? Reply yes or no.",
            }


    def _delete_folder(self, path_text: str) -> Dict[str, str | bool]:
            try:
                path = self._resolve_existing_target(path_text, target_kind="folder")
            except ValueError as exc:
                return {"success": False, "action": "delete_folder", "message": str(exc)}

            if not path.exists():
                return {
                    "success": False,
                    "action": "delete_folder",
                    "message": f"{self._display_target_name(path)} does not exist.",
                }

            if not path.is_dir():
                return {
                    "success": False,
                    "action": "delete_folder",
                    "message": "That is a file, not a folder.",
                }

            self._pending_delete_target = path
            self._last_folder_target = path
            return {
                "success": False,
                "action": "delete_folder",
                "message": f"Do you want me to delete folder {self._display_target_name(path)}? Reply yes or no.",
            }


    def _rename_target(self, source_text: str, new_name: str, target_kind: str = "") -> Dict[str, str | bool]:
            try:
                source = self._resolve_existing_target(source_text, target_kind=target_kind)
            except ValueError as exc:
                return {"success": False, "action": "rename", "message": str(exc)}

            if not source.exists():
                return {
                    "success": False,
                    "action": "rename",
                    "message": f"{self._display_target_name(source)} does not exist.",
                }

            clean_name = self._clean_file_name(new_name)
            if not clean_name:
                return {
                    "success": False,
                    "action": "rename",
                    "message": "Tell me the new name you want to use.",
                }

            if "\\" in clean_name or "/" in clean_name:
                return {
                    "success": False,
                    "action": "rename",
                    "message": "For renaming, give me just the new name, not a full path.",
                }

            destination = source.with_name(clean_name)
            if self._is_protected_path(destination):
                return {
                    "success": False,
                    "action": "rename",
                    "message": "That location is protected. Jarvis cannot rename items inside Windows or critical system folders.",
                }

            if destination.exists():
                return {
                    "success": False,
                    "action": "rename",
                    "message": f"{self._display_target_name(destination)} already exists at {destination}.",
                }

            try:
                source.rename(destination)
            except Exception as exc:
                return {
                    "success": False,
                    "action": "rename",
                    "message": f"Could not rename {self._display_target_name(source)}: {exc}",
                }

            self._remember_target(destination)
            return {
                "success": True,
                "action": "rename",
                "message": f"Renamed {self._display_target_name(source)} to {self._display_target_name(destination)}.",
            }


    def _move_target(self, source_text: str, destination_text: str, target_kind: str = "") -> Dict[str, str | bool]:
            try:
                source = self._resolve_existing_target(source_text, target_kind=target_kind)
            except ValueError as exc:
                return {"success": False, "action": "move", "message": str(exc)}

            if not source.exists():
                return {
                    "success": False,
                    "action": "move",
                    "message": f"{self._display_target_name(source)} does not exist.",
                }

            try:
                destination = self._resolve_move_destination(source, destination_text)
            except ValueError as exc:
                return {"success": False, "action": "move", "message": str(exc)}

            if destination.exists():
                return {
                    "success": False,
                    "action": "move",
                    "message": f"{self._display_target_name(destination)} already exists at {destination}.",
                }

            try:
                self.local_files_connector.move(source, destination)
            except Exception as exc:
                return {
                    "success": False,
                    "action": "move",
                    "message": f"Could not move {self._display_target_name(source)}: {exc}",
                }

            moved_path = Path(destination)
            self._remember_target(moved_path)
            return {
                "success": True,
                "action": "move",
                "message": f"Moved {self._display_target_name(moved_path)} to {moved_path}.",
            }


    def _resolve_move_destination(self, source: Path, destination_text: str) -> Path:
            cleaned = self._sanitize_file_reference(destination_text)
            if not cleaned:
                raise ValueError("Tell me where you want me to move it.")

            folder_target = self._resolve_folder_phrase(cleaned)
            if folder_target is not None:
                if self._is_protected_path(folder_target):
                    raise ValueError("That location is protected. Jarvis cannot access Windows or critical system folders.")
                return folder_target / source.name

            destination = self._resolve_laptop_path(cleaned)
            if destination.exists() and destination.is_dir():
                return destination / source.name

            if cleaned.endswith(("\\", "/")):
                return destination / source.name

            return destination


    def _resolve_folder_phrase(self, path_text: str) -> Path | None:
            raw_cleaned = self._sanitize_file_reference(path_text)
            explicit_folder_match = re.match(
                r"^(?:on|in|at|inside|under)\s+(?:the\s+)?(?:folder|directory)\s+(.+)$|^(?:the\s+)?(?:folder|directory)\s+(.+)$",
                raw_cleaned,
                flags=re.IGNORECASE,
            )
            if explicit_folder_match:
                explicit_value = (explicit_folder_match.group(1) or explicit_folder_match.group(2) or "").strip()
                if explicit_value:
                    return self._resolve_path(explicit_value).resolve()

            cleaned = self._clean_location_phrase(path_text)
            if not cleaned:
                return None

            alias_path = self._resolve_user_alias_path(cleaned)
            if alias_path is not None:
                lowered = cleaned.lower()
                if lowered in self.USER_PATH_ALIASES or lowered.startswith("the "):
                    return alias_path

            lowered = cleaned.lower()
            if lowered in self.USER_PATH_ALIASES:
                return self.USER_PATH_ALIASES[lowered]

            if self._looks_like_windows_absolute_path(cleaned) and cleaned.endswith(("\\", "/")):
                return Path(cleaned.replace("/", "\\"))

            return None


    def _handle_delete_confirmation(self, command: str) -> Dict[str, str | bool]:
            target = self._pending_delete_target
            response = command.strip().lower().rstrip(".!?")

            if response in {"yes", "y", "delete it", "confirm", "go ahead"}:
                self._pending_delete_target = None
                if not target or not target.exists():
                    return {
                        "success": False,
                        "action": "delete",
                        "message": "That item is no longer available to delete.",
                    }
                action = "delete_folder" if target.is_dir() else "delete_file"
                plan_command = f"delete {'folder' if target.is_dir() else 'file'} {target}"
                executor = ToolExecutor(registry=self._build_automation_tool_registry(), enforce_policy=True)
                return executor.execute(
                    ActionPlan(
                        original_text=plan_command,
                        steps=[
                            ActionStep(
                                step_id="step1",
                                tool_name="file",
                                intent="file",
                                action=action,
                                args={"path": str(target), "confirmed": True},
                            )
                        ],
                        is_multistep=False,
                    ),
                    ToolContext(
                        command=plan_command,
                        intent="file",
                        session_id=self._active_session_id,
                        request_id=self._active_turn_id,
                        payload={"turn_id": self._active_turn_id} if self._active_turn_id else {},
                        confirmation_state={"confirmed": True},
                        security_state={"step_up_verified": self._active_step_up_verified},
                    ),
                )

            if response in {"no", "n", "cancel", "stop", "don't", "do not"}:
                self._pending_delete_target = None
                return {
                    "success": False,
                    "action": "delete",
                    "message": "Deletion cancelled.",
                }

            return {
                "success": False,
                "action": "delete",
                "message": f"Please reply yes or no to confirm deleting {self._display_target_name(target)}.",
            }


    def _is_protected_path(self, path: Path) -> bool:
            try:
                resolved = path.resolve()
            except Exception:
                resolved = path

            resolved_text = str(resolved).lower()
            drive_root_match = re.match(r"^[a-z]:\\?$", resolved_text)
            if drive_root_match:
                return True

            workspace_text = str(_runtime_base_dir().resolve()).lower()
            if resolved_text.startswith(workspace_text):
                return False

            for prefix in self.PROTECTED_PATH_PREFIXES:
                prefix_text = str(prefix.resolve()).lower()
                if resolved_text == prefix_text or resolved_text.startswith(prefix_text + "\\"):
                    return True

            for pattern in self.PROTECTED_PATH_PATTERNS:
                if pattern.match(resolved_text):
                    return True

            return False

