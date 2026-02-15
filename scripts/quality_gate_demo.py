#!/usr/bin/env python3
"""Quick demo of the quality gate system without running full test suite."""

import json
import subprocess
import sys
from pathlib import Path


def run_ruff_demo():
    """Run ruff on a subset of files for demo."""
    print("🔍 Running ruff quality checks (demo)...")

    try:
        # Run ruff on just a few files for demo
        result = subprocess.run(
            ["uv", "run", "ruff", "check", "--output-format=json", "src/bolster/cli.py", "src/bolster/__init__.py"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        violations = []
        if result.stdout.strip():
            violations = json.loads(result.stdout)

        return {
            "tool": "ruff",
            "passed": len(violations) == 0,
            "total_violations": len(violations),
            "violations": violations[:5],  # Show first 5 only
            "exit_code": result.returncode,
        }

    except Exception as e:
        return {"tool": "ruff", "passed": False, "error": str(e), "exit_code": 1}


def run_custom_demo():
    """Run custom checks on a subset of files."""
    print("🔧 Running custom checks (demo)...")

    violations = []

    # Check just a few files for demo
    demo_files = [Path("src/bolster/cli.py"), Path("src/bolster/__init__.py")]

    for file_path in demo_files:
        if not file_path.exists():
            continue

        try:
            content = file_path.read_text(encoding="utf-8")

            # Check for raw requests usage
            if "import requests" in content and ("requests.get(" in content or "requests.post(" in content):
                violations.append(
                    {
                        "file": str(file_path),
                        "rule": "shared-utilities",
                        "message": "Use bolster.utils.web.session instead of raw requests",
                        "severity": "error",
                    }
                )

        except Exception as e:
            print(f"⚠️  Could not check {file_path}: {e}")

    return {
        "tool": "custom",
        "passed": len(violations) == 0,
        "total_violations": len(violations),
        "violations": violations,
    }


def main():
    """Demo the quality gate system."""
    print("🏗️  Bolster Quality Gate Demo")
    print("=" * 40)

    # Run demo checks
    ruff_results = run_ruff_demo()
    custom_results = run_custom_demo()

    # Report results
    print("\n📊 Results Summary:")

    # Ruff results
    if ruff_results.get("passed"):
        print("✅ Code Quality (ruff): PASSED")
    else:
        violations = ruff_results.get("total_violations", 0)
        print(f"❌ Code Quality (ruff): {violations} violations found")

        for violation in ruff_results.get("violations", [])[:3]:
            filename = violation.get("filename", "").replace("/Users/bolster/src/bolster/", "")
            line = violation.get("location", {}).get("row", "?")
            code = violation.get("code", "")
            message = violation.get("message", "")
            print(f"   {filename}:{line} [{code}] {message}")

    # Custom results
    if custom_results.get("passed"):
        print("✅ Domain-Specific Rules: PASSED")
    else:
        violations = custom_results.get("total_violations", 0)
        print(f"❌ Domain-Specific Rules: {violations} violations found")

        for violation in custom_results.get("violations", []):
            file_path = violation.get("file", "").replace("src/bolster/", "")
            message = violation.get("message", "")
            print(f"   {file_path} - {message}")

    print("\n" + "=" * 40)
    all_passed = ruff_results.get("passed", False) and custom_results.get("passed", False)

    if all_passed:
        print("🎉 Quality demo checks PASSED!")
    else:
        print("⚠️  Some quality issues found (this is normal in advisory mode)")
        print("This demonstrates how the system identifies issues for improvement")

    print("\nNote: This was a demo run on a subset of files.")
    print("The full system would check all source files and include test coverage.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
