#!/usr/bin/env python3
"""Constitutional compliance validation for Bolster project.

Enforces project-specific architectural conventions before release.
Standard CI (pytest, codecov, pre-commit/ruff) handles testing and linting separately.

Checks:
- Shared utilities usage (no raw requests.get())
- Data source modules have validation functions
- Logging standards (logger setup, no print() in library code)
- Domain-specific exception hierarchy (no bare raise Exception())
- Function naming conventions (get_latest_, parse_, validate_ prefixes)
- Module documentation (Data Source, Update Frequency, Example sections)
"""

import ast
import sys
from pathlib import Path
from typing import Dict

SKIP_FILES = ("__init__.py", "_base.py", "validation.py")


def has_print_calls_in_code(file_path: Path) -> bool:
    """Check if file has actual print() calls in code (not in docstrings)."""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                return True
        return False
    except Exception:
        return "print(" in file_path.read_text(encoding="utf-8", errors="replace")


def check_shared_utilities_usage() -> Dict[str, object]:
    """Check that code uses shared session instead of raw requests."""
    violations = []
    for file_path in Path("src").rglob("*.py"):
        try:
            content = file_path.read_text(encoding="utf-8")
            if "import requests" in content and ("requests.get(" in content or "requests.post(" in content):
                violations.append(f"{file_path}: raw requests usage instead of web.session")
            if "urllib.request.urlretrieve" in content:
                violations.append(f"{file_path}: urlretrieve instead of download_file")
        except Exception as e:
            print(f"⚠️  Could not check {file_path}: {e}")

    if not violations:
        print("✅ Shared utilities: OK")
        return {"shared_utilities": True}
    for v in violations:
        print(f"  ✗ {v}")
    return {"shared_utilities": False}


def check_data_validation_functions() -> Dict[str, object]:
    """Check that data source modules have validation functions."""
    violations = []
    for file_path in Path("src/bolster/data_sources").rglob("*.py"):
        if file_path.name in SKIP_FILES:
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
            if "validate_" not in content:
                violations.append(f"{file_path}: no validation function")
        except Exception as e:
            print(f"⚠️  Could not check {file_path}: {e}")

    if not violations:
        print("✅ Validation functions: OK")
        return {"data_validation": True}
    for v in violations:
        print(f"  ✗ {v}")
    return {"data_validation": False}


def check_logging_standards() -> Dict[str, object]:
    """Check data source modules have logger setup and no bare print() calls."""
    violations = []
    for file_path in Path("src/bolster/data_sources").rglob("*.py"):
        if file_path.name in SKIP_FILES:
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
            if "logger = logging.getLogger(__name__)" not in content:
                violations.append(f"{file_path}: missing logger setup")
            if has_print_calls_in_code(file_path):
                violations.append(f"{file_path}: print() in library code")
        except Exception as e:
            print(f"⚠️  Could not check {file_path}: {e}")

    if not violations:
        print("✅ Logging standards: OK")
        return {"logging_standards": True}
    for v in violations:
        print(f"  ✗ {v}")
    return {"logging_standards": False}


def check_error_handling_hierarchy() -> Dict[str, object]:
    """Check for domain-specific exceptions instead of bare Exception."""
    violations = []
    for file_path in Path("src/bolster/data_sources").rglob("*.py"):
        if file_path.name in SKIP_FILES:
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
            if "raise Exception(" in content:
                violations.append(f"{file_path}: bare raise Exception()")
        except Exception as e:
            print(f"⚠️  Could not check {file_path}: {e}")

    if not violations:
        print("✅ Exception hierarchy: OK")
        return {"error_handling": True}
    for v in violations:
        print(f"  ✗ {v}")
    return {"error_handling": False}


def check_function_naming_conventions() -> Dict[str, object]:
    """Check data source modules follow get_latest_/parse_/validate_ naming."""
    violations = []
    expected = ("get_latest_", "parse_", "validate_")
    for file_path in Path("src/bolster/data_sources").rglob("*.py"):
        if file_path.name in SKIP_FILES:
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
            if not any(p in content for p in expected):
                violations.append(f"{file_path}: no standard function prefixes")
        except Exception as e:
            print(f"⚠️  Could not check {file_path}: {e}")

    if not violations:
        print("✅ Function naming: OK")
        return {"function_naming": True}
    for v in violations:
        print(f"  ✗ {v}")
    return {"function_naming": False}


def check_module_documentation() -> Dict[str, object]:
    """Check data source modules have required docstring sections."""
    required = ("Data Source", "Update Frequency", "Example")
    violations = []
    for file_path in Path("src/bolster/data_sources").rglob("*.py"):
        if file_path.name in SKIP_FILES:
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
            missing = [s for s in required if s not in content[:2000]]
            if missing:
                violations.append(f"{file_path}: missing {', '.join(missing)}")
        except Exception as e:
            print(f"⚠️  Could not check {file_path}: {e}")

    if not violations:
        print("✅ Module documentation: OK")
        return {"module_docs": True}
    for v in violations:
        print(f"  ✗ {v}")
    return {"module_docs": False}


def main() -> int:
    """Run all constitutional checks. Returns 0 on pass, 1 on violations."""
    import os

    os.chdir(Path(__file__).parent.parent)

    print("🏛️  Constitutional compliance check")
    print("─" * 40)

    results = {}
    results.update(check_shared_utilities_usage())
    results.update(check_data_validation_functions())
    results.update(check_logging_standards())
    results.update(check_error_handling_hierarchy())
    results.update(check_function_naming_conventions())
    results.update(check_module_documentation())

    print("─" * 40)
    failures = [k for k, v in results.items() if not v]
    if not failures:
        print("✅ All checks passed")
        return 0
    else:
        print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
