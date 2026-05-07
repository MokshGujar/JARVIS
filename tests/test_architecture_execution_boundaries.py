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
DANGEROUS_IMPORTS = {
    "AppOpener",
    "keyboard",
    "pyautogui",
    "pywinauto",
    "subprocess",
    "webbrowser",
}
DANGEROUS_CALLS = {
    ("os", "startfile"),
    ("os", "system"),
    ("webbrowser", "open"),
    ("shutil", "move"),
    ("shutil", "rmtree"),
    ("Path", "unlink"),
}
DANGEROUS_CALL_BASES = {"pyautogui", "pywinauto", "keyboard", "subprocess"}
COMPATIBILITY_FACADE_SERVICES = {
    "automation_service.py",
    "browser_control_service.py",
    "computer_control_service.py",
    "computer_settings_service.py",
    "game_service.py",
    "message_action_service.py",
    "safe_command_info_service.py",
    "whatsapp_desktop_automation.py",
    "youtube_tools_service.py",
}


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


def test_automation_service_execute_uses_extracted_facade_seams():
    source = (ROOT / "app" / "services" / "automation_service.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    service_class = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "AutomationService")
    init_func = next(node for node in service_class.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
    execute_func = next(node for node in service_class.body if isinstance(node, ast.FunctionDef) and node.name == "execute")
    init_segment = ast.get_source_segment(source, init_func) or ""
    execute_segment = ast.get_source_segment(source, execute_func) or ""

    assert "AutomationContextBuilder()" in init_segment
    assert "AutomationFacadeResponseFormatter()" in init_segment
    assert "PendingConfirmationService()" in init_segment
    assert "self._context_builder.build" in execute_segment
    assert "self._response_formatter.normalize" in execute_segment


def test_legacy_delegate_methods_have_been_migrated_out_of_automation_service():
    source = (ROOT / "app" / "services" / "automation_service.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    service_class = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "AutomationService")
    removed_delegate_names = {
        "_execute_app_launcher_command_legacy",
        "_execute_system_command_legacy",
        "_execute_file_command_legacy",
        "_execute_whatsapp_command_legacy",
        "_execute_browser_command_legacy",
        "_execute_browser_control_legacy",
    }

    remaining = []
    for node in service_class.body:
        if isinstance(node, ast.FunctionDef) and node.name in removed_delegate_names:
            remaining.append(node.name)

    assert remaining == []


def test_tools_and_tests_do_not_call_or_patch_removed_automation_service_delegates():
    removed_delegate_names = {
        "_execute_app_launcher_command_legacy",
        "_execute_system_command_legacy",
        "_execute_file_command_legacy",
        "_execute_whatsapp_command_legacy",
        "_execute_browser_command_legacy",
        "_execute_browser_control_legacy",
    }
    offenders: list[str] = []
    for base in (ROOT / "app" / "tools", ROOT / "tests"):
        for path in _python_files(base):
            if path.name == "test_architecture_execution_boundaries.py":
                continue
            text = path.read_text(encoding="utf-8")
            for name in removed_delegate_names:
                if name in text:
                    offenders.append(f"{path.relative_to(ROOT)} references {name}")

    assert offenders == []


def test_monolithic_automation_compatibility_mixin_has_been_removed():
    assert not (ROOT / "app" / "services" / "automation_compatibility_mixins.py").exists()

    source = (ROOT / "app" / "services" / "automation_service.py").read_text(encoding="utf-8")
    assert "AutomationCompatibilityMixin" not in source
    assert "automation_compatibility_mixins" not in source


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


def _dangerous_imports(module: ast.Module) -> list[str]:
    imports: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in DANGEROUS_IMPORTS:
                    imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root in DANGEROUS_IMPORTS:
                imports.append(node.module or "")
    return imports


def _call_name(node: ast.AST) -> tuple[str, str] | None:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    base = node.func.value
    if isinstance(base, ast.Name):
        return base.id, node.func.attr
    return None


def test_service_facades_do_not_contain_direct_execution_apis_except_automation_legacy():
    offenders: list[str] = []
    services_root = ROOT / "app" / "services"
    for path in _python_files(services_root):
        if path.name == "automation_service.py":
            continue
        if path.name not in COMPATIBILITY_FACADE_SERVICES:
            continue
        source = path.read_text(encoding="utf-8")
        module = ast.parse(source)
        for imported in _dangerous_imports(module):
            offenders.append(f"{path.relative_to(ROOT)} imports {imported}")
        for node in ast.walk(module):
            call = _call_name(node)
            if call is None:
                continue
            base, attr = call
            if base in DANGEROUS_CALL_BASES or (base, attr) in DANGEROUS_CALLS:
                offenders.append(f"{path.relative_to(ROOT)} calls {base}.{attr}")

    assert offenders == []


def test_high_level_routing_paths_do_not_call_connectors_or_adapters_directly():
    high_level_methods = {
        "app/services/automation_service.py": {"execute", "_execute_facade"},
        "app/orchestrator/main_orchestrator.py": {"execute", "handle_command"},
        "app/orchestrator/intent_router.py": {"route", "resolve"},
    }
    offenders: list[str] = []
    for relative_path, method_names in high_level_methods.items():
        path = ROOT / relative_path
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in ast.walk(module):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in method_names:
                continue
            segment = ast.get_source_segment(source, node) or ""
            if ".connector." in segment or ".adapter." in segment:
                offenders.append(f"{relative_path}:{node.name} directly touches connector/adapter state")
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                    called = call.func.id
                    if called.endswith("Connector") or called.endswith("Adapter"):
                        offenders.append(f"{relative_path}:{node.name} constructs {called}")

    assert offenders == []
