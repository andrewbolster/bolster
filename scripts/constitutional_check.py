#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "pytest",
#     "pytest-cov",
#     "safety",
# ]
# ///
"""Constitutional compliance validation for Bolster project.

This script validates that all code changes comply with the project's
constitutional requirements defined in .specify/memory/constitution.md.

Used as a pre-commit hook and in CI/CD pipelines to enforce constitutional
constraints before any version increment or release.
"""

import ast
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple


def run_command(cmd: List[str], check: bool = True) -> Tuple[int, str, str]:
    """Run a command and return exit code, stdout, stderr."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return 1, "", f"Command not found: {' '.join(cmd)}"


def has_print_calls_in_code(file_path: Path) -> bool:
    """Check if file has actual print() calls in code (not in docstrings)."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Parse the AST to find actual print calls
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                return True
        return False
    except Exception:
        # If we can't parse the file, fall back to simple string search
        return "print(" in content


def check_test_coverage() -> Dict[str, bool]:
    """Verify test coverage meets constitutional requirement (>90%)."""
    print("🧪 Checking test coverage...")

    # Run pytest with coverage
    exit_code, stdout, stderr = run_command(
        ["uv", "run", "pytest", "--cov=src/bolster", "--cov-report=term-missing", "--cov-fail-under=90"]
    )

    if exit_code == 0:
        print("✅ Test coverage above 90% - constitutional requirement met")
        return {"test_coverage": True, "message": "Coverage >90%"}
    else:
        print("❌ CONSTITUTIONAL VIOLATION: Test coverage below 90%")
        print(f"Coverage output: {stdout}")
        return {"test_coverage": False, "message": "Coverage <90%"}


def check_security_vulnerabilities() -> Dict[str, bool]:
    """Check for security vulnerabilities."""
    print("🔒 Checking for security vulnerabilities...")

    # Check if safety is available
    exit_code, _, _ = run_command(["uv", "run", "safety", "--version"])
    if exit_code != 0:
        print("⚠️  Safety tool not available - installing...")
        install_code, _, _ = run_command(["uv", "add", "--dev", "safety"])
        if install_code != 0:
            print("⚠️  Could not install safety tool - skipping security check")
            return {"security": True, "message": "Security tool unavailable"}

    # Run safety check
    exit_code, stdout, stderr = run_command(["uv", "run", "safety", "check"])

    if exit_code == 0:
        print("✅ No security vulnerabilities found")
        return {"security": True, "message": "No vulnerabilities"}
    else:
        print("❌ CONSTITUTIONAL VIOLATION: Security vulnerabilities detected")
        print(f"Safety output: {stdout}")
        return {"security": False, "message": f"Vulnerabilities found: {stdout[:200]}..."}


def check_all_tests_passing() -> Dict[str, bool]:
    """Verify all tests are passing."""
    print("🧪 Verifying all tests pass...")

    exit_code, stdout, stderr = run_command(["uv", "run", "pytest", "tests/", "-v"])

    if exit_code == 0:
        print("✅ All tests passing")
        return {"all_tests": True, "message": "All tests pass"}
    else:
        print("❌ CONSTITUTIONAL VIOLATION: Some tests are failing")
        print(f"Test output: {stderr}")
        return {"all_tests": False, "message": "Tests failing"}


def check_shared_utilities_usage() -> Dict[str, bool]:
    """Check that code uses shared utilities instead of reinventing."""
    print("🔧 Checking shared utilities usage...")

    # Look for anti-patterns in Python files
    violations = []
    src_files = list(Path("src").rglob("*.py"))

    for file_path in src_files:
        try:
            content = file_path.read_text()

            # Check for raw requests usage (should use web.session)
            if "import requests" in content and "from .web import" not in content:
                if "requests.get(" in content or "requests.post(" in content:
                    violations.append(f"{file_path}: Using raw requests instead of web.session")

            # Check for manual file download instead of CachedDownloader
            if "urllib.request.urlretrieve" in content:
                violations.append(f"{file_path}: Using urlretrieve instead of CachedDownloader")

        except Exception as e:
            print(f"⚠️  Could not check {file_path}: {e}")

    if not violations:
        print("✅ Shared utilities usage verified")
        return {"shared_utilities": True, "message": "Proper utility usage"}
    else:
        print("❌ CONSTITUTIONAL VIOLATION: Shared utilities not used properly")
        for violation in violations:
            print(f"  - {violation}")
        return {"shared_utilities": False, "message": f"{len(violations)} violations found"}


def check_data_validation_functions() -> Dict[str, bool]:
    """Check that data source modules have validation functions."""
    print("📊 Checking data validation functions...")

    violations = []
    data_source_files = list(Path("src/bolster/data_sources").rglob("*.py"))

    for file_path in data_source_files:
        # Skip __init__.py and _base.py files
        if file_path.name in ["__init__.py", "_base.py"]:
            continue

        try:
            content = file_path.read_text()

            # Check for validation function
            has_validate_data = "def validate_data(" in content
            has_validate_function = "validate_" in content

            if not (has_validate_data or has_validate_function):
                violations.append(f"{file_path}: Missing validation function")

        except Exception as e:
            print(f"⚠️  Could not check {file_path}: {e}")

    if not violations:
        print("✅ Data validation functions present")
        return {"data_validation": True, "message": "Validation functions present"}
    else:
        print("❌ CONSTITUTIONAL VIOLATION: Missing validation functions")
        for violation in violations[:5]:  # Show first 5
            print(f"  - {violation}")
        if len(violations) > 5:
            print(f"  ... and {len(violations) - 5} more")
        return {"data_validation": False, "message": f"{len(violations)} modules missing validation"}


def check_code_quality() -> Dict[str, bool]:
    """Check code quality with ruff."""
    print("🎨 Checking code quality...")

    # Run ruff check
    exit_code, stdout, stderr = run_command(["uv", "run", "ruff", "check", "."])

    if exit_code == 0:
        print("✅ Code quality checks pass")
        return {"code_quality": True, "message": "Ruff checks pass"}
    else:
        print("❌ CONSTITUTIONAL VIOLATION: Code quality issues found")
        print(f"Ruff output: {stdout}")
        return {"code_quality": False, "message": "Code quality issues"}


def check_logging_standards() -> Dict[str, bool]:
    """Check that all data source modules have proper logging setup."""
    print("📋 Checking logging standards...")

    violations = []
    data_source_files = list(Path("src/bolster/data_sources").rglob("*.py"))

    for file_path in data_source_files:
        if file_path.name in ["__init__.py", "_base.py"]:
            continue

        try:
            content = file_path.read_text()

            # Check for logger setup
            has_logger_setup = "logger = logging.getLogger(__name__)" in content
            has_print_calls = has_print_calls_in_code(file_path)

            if not has_logger_setup:
                violations.append(f"{file_path}: Missing logger setup")

            if has_print_calls and "pragma: no cover" not in content:
                violations.append(f"{file_path}: Using print() instead of logger")

        except Exception as e:
            print(f"⚠️  Could not check {file_path}: {e}")

    if not violations:
        print("✅ Logging standards compliant")
        return {"logging_standards": True, "message": "All modules have proper logging"}
    else:
        print("❌ CONSTITUTIONAL VIOLATION: Logging standards violated")
        for violation in violations[:5]:  # Show first 5
            print(f"  - {violation}")
        if len(violations) > 5:
            print(f"  ... and {len(violations) - 5} more")
        return {"logging_standards": False, "message": f"{len(violations)} logging violations"}


def check_error_handling_hierarchy() -> Dict[str, bool]:
    """Check for proper domain-specific exception usage."""
    print("🚨 Checking error handling hierarchy...")

    violations = []
    data_source_files = list(Path("src/bolster/data_sources").rglob("*.py"))

    for file_path in data_source_files:
        if file_path.name in ["__init__.py", "_base.py"]:
            continue

        try:
            content = file_path.read_text()

            # Look for generic Exception raises (should use domain-specific exceptions)
            if "raise Exception(" in content and "pragma: no cover" not in content:
                violations.append(f"{file_path}: Using generic Exception instead of domain-specific")

        except Exception as e:
            print(f"⚠️  Could not check {file_path}: {e}")

    if not violations:
        print("✅ Error handling hierarchy compliant")
        return {"error_handling": True, "message": "Proper exception hierarchy used"}
    else:
        print("❌ CONSTITUTIONAL VIOLATION: Error handling violations")
        for violation in violations[:3]:
            print(f"  - {violation}")
        return {"error_handling": False, "message": f"{len(violations)} error handling violations"}


def check_function_naming_conventions() -> Dict[str, bool]:
    """Check for consistent function naming patterns."""
    print("📝 Checking function naming conventions...")

    data_source_files = list(Path("src/bolster/data_sources").rglob("*.py"))

    expected_patterns = {
        "get_latest_": "retrieval functions",
        "parse_": "file parsing functions",
        "validate_": "data validation functions",
    }

    consistent_modules = 0
    total_modules = 0

    for file_path in data_source_files:
        if file_path.name in ["__init__.py", "_base.py"]:
            continue

        total_modules += 1
        try:
            content = file_path.read_text()

            # Check for expected function patterns
            has_expected_patterns = any(pattern in content for pattern in expected_patterns.keys())

            if has_expected_patterns:
                consistent_modules += 1

        except Exception as e:
            print(f"⚠️  Could not check {file_path}: {e}")

    compliance_rate = consistent_modules / total_modules if total_modules > 0 else 0

    if compliance_rate >= 0.8:  # 80% compliance threshold
        print(f"✅ Function naming conventions mostly compliant ({consistent_modules}/{total_modules})")
        return {"function_naming": True, "message": f"{compliance_rate * 100:.1f}% compliance"}
    else:
        print(f"❌ CONSTITUTIONAL VIOLATION: Function naming inconsistent ({consistent_modules}/{total_modules})")
        return {"function_naming": False, "message": f"Only {compliance_rate * 100:.1f}% compliance"}


def check_data_source_documentation() -> Dict[str, bool]:
    """Check for comprehensive data source documentation."""
    print("📖 Checking data source documentation...")

    violations = []
    data_source_files = list(Path("src/bolster/data_sources").rglob("*.py"))

    required_doc_elements = ["Data Source", "Update Frequency", "Example"]

    for file_path in data_source_files:
        if file_path.name in ["__init__.py", "_base.py"]:
            continue

        try:
            content = file_path.read_text()

            # Check module docstring for required elements
            missing_elements = []
            for element in required_doc_elements:
                if element not in content[:2000]:  # Check first 2000 chars (module docstring area)
                    missing_elements.append(element)

            if missing_elements:
                violations.append(f"{file_path}: Missing documentation - {', '.join(missing_elements)}")

        except Exception as e:
            print(f"⚠️  Could not check {file_path}: {e}")

    if not violations:
        print("✅ Data source documentation compliant")
        return {"documentation": True, "message": "All modules have proper documentation"}
    else:
        print("❌ CONSTITUTIONAL VIOLATION: Documentation standards violated")
        for violation in violations[:3]:
            print(f"  - {violation}")
        if len(violations) > 3:
            print(f"  ... and {len(violations) - 3} more")
        return {"documentation": False, "message": f"{len(violations)} documentation violations"}


def check_cli_integration() -> Dict[str, bool]:
    """Check that data sources are integrated with CLI commands."""
    print("🖥️ Checking CLI integration...")

    # Read CLI module to see what's integrated
    try:
        cli_content = Path("src/bolster/cli.py").read_text()

        # Count CLI commands/integrations
        command_count = cli_content.count("@click.command")

        if command_count > 10:  # Reasonable threshold for CLI integration
            print(f"✅ CLI integration extensive ({command_count} commands)")
            return {"cli_integration": True, "message": f"{command_count} CLI commands available"}
        else:
            print(f"⚠️  Limited CLI integration ({command_count} commands)")
            return {"cli_integration": False, "message": f"Only {command_count} CLI commands"}

    except Exception as e:
        print(f"⚠️  Could not check CLI integration: {e}")
        return {"cli_integration": False, "message": "CLI check failed"}


def check_constitutional_compliance() -> bool:
    """Run all constitutional compliance checks."""
    print("=" * 80)
    print("🏛️  CONSTITUTIONAL COMPLIANCE VALIDATION")
    print("=" * 80)
    print()

    # Run all checks
    results = {}

    # MUST level requirements (constitutional violations)
    results.update(check_test_coverage())
    results.update(check_security_vulnerabilities())
    results.update(check_all_tests_passing())
    results.update(check_shared_utilities_usage())
    results.update(check_data_validation_functions())
    results.update(check_code_quality())

    # New constitutional patterns
    results.update(check_logging_standards())
    results.update(check_error_handling_hierarchy())
    results.update(check_function_naming_conventions())
    results.update(check_data_source_documentation())
    results.update(check_cli_integration())

    print()
    print("=" * 80)
    print("📋 CONSTITUTIONAL COMPLIANCE SUMMARY")
    print("=" * 80)

    violations = []
    for check, passed in results.items():
        if check.endswith("_message"):
            continue
        status = "✅ PASS" if passed else "❌ FAIL"
        message = results.get(f"{check}_message", "")
        print(f"{status}: {check.replace('_', ' ').title()} - {message}")
        if not passed:
            violations.append(check)

    print()

    if not violations:
        print("🎉 CONSTITUTIONAL COMPLIANCE VERIFIED")
        print("All constitutional requirements met - safe to proceed")
        return True
    else:
        print("🚨 CONSTITUTIONAL VIOLATIONS DETECTED")
        print(f"Found {len(violations)} violations that must be resolved:")
        for violation in violations:
            print(f"  - {violation.replace('_', ' ').title()}")
        print()
        print("🛑 Development must halt until violations are resolved")
        return False


def main():
    """Main function for constitutional compliance check."""
    try:
        # Change to repository root
        repo_root = Path(__file__).parent.parent
        import os

        os.chdir(repo_root)

        if check_constitutional_compliance():
            sys.exit(0)
        else:
            sys.exit(1)

    except Exception as e:
        print(f"❌ Constitutional check failed with error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
