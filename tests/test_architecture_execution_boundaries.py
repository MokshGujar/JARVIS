from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_TOKENS = (
    "os.startfile",
    "subprocess",
    "webbrowser.open",
    "AppOpener",
    "pyautogui",
    "pywinauto",
)


def _python_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(item for item in path.rglob("*.py") if "__pycache__" not in item.parts)


def test_orchestrator_modules_do_not_use_direct_execution_apis():
    offenders: list[str] = []
    for path in _python_files(ROOT / "app" / "orchestrator"):
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            if token in text:
                offenders.append(f"{path.relative_to(ROOT)}: {token}")

    assert offenders == []


def test_automation_service_execute_enters_facade_not_legacy_brain():
    source = (ROOT / "app" / "services" / "automation_service.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    service_class = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "AutomationService")
    execute_func = next(node for node in service_class.body if isinstance(node, ast.FunctionDef) and node.name == "execute")
    calls = {
        getattr(node.func, "attr", "")
        for node in ast.walk(execute_func)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "_execute_facade" in calls
    assert "_execute_legacy" not in calls


def test_legacy_delegate_methods_are_explicitly_marked():
    source = (ROOT / "app" / "services" / "automation_service.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    service_class = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "AutomationService")
    delegate_names = {
        "_execute_app_launcher_command_legacy",
        "_execute_system_command_legacy",
        "_execute_file_command_legacy",
        "_execute_whatsapp_command_legacy",
        "_execute_browser_command_legacy",
        "_execute_browser_control_legacy",
    }

    missing: list[str] = []
    for node in service_class.body:
        if isinstance(node, ast.FunctionDef) and node.name in delegate_names:
            segment = ast.get_source_segment(source, node) or ""
            if "LEGACY DELEGATE: Only tool classes may call this." not in segment:
                missing.append(node.name)

    assert missing == []


def test_config_app_is_not_imported_by_runtime_source():
    offenders: list[str] = []
    for base in (ROOT / "app", ROOT / "tests"):
        for path in _python_files(base):
            if path.name == "test_architecture_execution_boundaries.py":
                continue
            text = path.read_text(encoding="utf-8")
            if "config.app" in text or "config/app" in text:
                offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []
