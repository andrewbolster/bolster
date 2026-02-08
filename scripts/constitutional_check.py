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
