#!/usr/bin/env python3
"""Quality Gate System for Bolster Project.

Replaces constitutional_check.py with a proper standards-based validation system
that leverages existing mature tools (ruff, pytest-cov) instead of custom validation.

This script orchestrates multiple quality tools and generates a unified report:
- Code style and quality (ruff)
- Test coverage (pytest-cov)
- Custom domain-specific patterns

The system operates in advisory mode by default - it reports issues but doesn't
block builds unless specifically configured to do so.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional


class QualityReporter:
    """Orchestrates quality tools and generates unified reports."""

    def __init__(self, project_root: Path = None):
        """Initialize quality reporter.

        Args:
            project_root: Root directory of the project. Defaults to script parent's parent.
        """
        if project_root is None:
            project_root = Path(__file__).parent.parent
        self.project_root = project_root
        self.results = {}

    def run_ruff_check(self) -> dict:
        """Run ruff linting and return results."""
        print("🔍 Running ruff quality checks...")

        try:
            # Run ruff with JSON output for machine-readable results
            result = subprocess.run(
                ["uv", "run", "ruff", "check", "--output-format=json", "src/"],
                capture_output=True,
                text=True,
                cwd=self.project_root,
            )

            violations = []
            if result.stdout.strip():
                violations = json.loads(result.stdout)

            # Categorize violations by type
            categories = {}
            for violation in violations:
                rule_code = violation.get("code", "UNKNOWN")
                category = self._categorize_ruff_rule(rule_code)
                if category not in categories:
                    categories[category] = []
                categories[category].append(violation)

            return {
                "tool": "ruff",
                "passed": len(violations) == 0,
                "total_violations": len(violations),
                "violations": violations,
                "categories": categories,
                "exit_code": result.returncode,
            }

        except Exception as e:
            return {"tool": "ruff", "passed": False, "error": f"Failed to run ruff: {e}", "exit_code": 1}

    def run_coverage_check(self) -> dict:
        """Check test coverage using existing coverage data."""
        print("📊 Running test coverage analysis...")

        try:
            # Use existing coverage data (don't run pytest - too slow for CI)
            coverage_file = self.project_root / "coverage.json"
            coverage_data = {}

            if not coverage_file.exists():
                return {
                    "tool": "coverage",
                    "passed": False,
                    "error": "No coverage.json found. Run 'pytest --cov' to generate coverage data.",
                    "exit_code": 1
                }

            with open(coverage_file) as f:
                coverage_data = json.load(f)

            # Extract key metrics
            summary = coverage_data.get("totals", {})
            coverage_percent = summary.get("percent_covered", 0)

            return {
                "tool": "coverage",
                "passed": coverage_percent >= 80,  # Our 80% threshold
                "coverage_percent": coverage_percent,
                "missing_lines": summary.get("missing_lines", 0),
                "covered_lines": summary.get("covered_lines", 0),
                "total_lines": summary.get("num_statements", 0),
                "files": coverage_data.get("files", {}),
                "exit_code": result.returncode,
            }

        except Exception as e:
            return {"tool": "coverage", "passed": False, "error": f"Failed to run coverage: {e}", "exit_code": 1}

    def run_custom_checks(self) -> dict:
        """Run custom domain-specific checks that ruff can't handle."""
        print("🔧 Running custom domain-specific checks...")

        violations = []

        # Check for shared utilities usage (similar to constitutional checker)
        for file_path in Path("src").rglob("*.py"):
            try:
                content = file_path.read_text(encoding="utf-8")

                # Check for raw requests usage (should use bolster.utils.web.session)
                if "import requests" in content and ("requests.get(" in content or "requests.post(" in content):
                    violations.append(
                        {
                            "file": str(file_path),
                            "line": self._find_line_number(content, "requests.get("),
                            "rule": "shared-utilities",
                            "message": "Use bolster.utils.web.session instead of raw requests",
                            "severity": "error",
                        }
                    )

                # Check for urlretrieve usage
                if "urllib.request.urlretrieve" in content:
                    violations.append(
                        {
                            "file": str(file_path),
                            "line": self._find_line_number(content, "urllib.request.urlretrieve"),
                            "rule": "shared-utilities",
                            "message": "Use download_file() from _base module instead of urlretrieve",
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

    def generate_report(self, output_format: str = "text") -> str:
        """Generate unified quality report.

        Args:
            output_format: Format for output - 'text', 'json', or 'github'

        Returns:
            Formatted quality report
        """
        # Run all quality checks
        self.results["ruff"] = self.run_ruff_check()
        self.results["coverage"] = self.run_coverage_check()
        self.results["custom"] = self.run_custom_checks()

        if output_format == "json":
            return json.dumps(self.results, indent=2)
        if output_format == "github":
            return self._format_github_output()
        return self._format_text_output()

    def _categorize_ruff_rule(self, rule_code: str) -> str:
        """Categorize ruff rules into meaningful groups."""
        if rule_code.startswith("D"):
            return "documentation"
        if rule_code.startswith("T20"):
            return "print_statements"
        if rule_code.startswith("F"):
            return "code_errors"
        if rule_code.startswith("E") or rule_code.startswith("W"):
            return "code_style"
        if rule_code.startswith("I"):
            return "import_organization"
        return "other"

    def _find_line_number(self, content: str, search_term: str) -> Optional[int]:
        """Find line number of a search term in content."""
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            if search_term in line:
                return i
        return None

    def _format_text_output(self) -> str:
        """Format results as human-readable text."""
        output = []
        output.append("🏗️  Bolster Quality Gate Report")
        output.append("=" * 50)

        total_issues = 0
        all_passed = True

        # Ruff results
        ruff = self.results.get("ruff", {})
        if ruff.get("passed", True):
            output.append("✅ Code Quality (ruff): PASSED")
        else:
            all_passed = False
            violations = ruff.get("total_violations", 0)
            total_issues += violations
            output.append(f"❌ Code Quality (ruff): {violations} violations found")

            # Show violations by category
            categories = ruff.get("categories", {})
            for category, issues in categories.items():
                output.append(f"   📂 {category}: {len(issues)} issues")
                for issue in issues[:3]:  # Show first 3 issues per category
                    file_path = issue.get("filename", "unknown")
                    line = issue.get("location", {}).get("row", "?")
                    message = issue.get("message", "Unknown issue")
                    output.append(f"      {file_path}:{line} - {message}")
                if len(issues) > 3:
                    output.append(f"      ... and {len(issues) - 3} more")

        # Coverage results
        coverage = self.results.get("coverage", {})
        coverage_percent = coverage.get("coverage_percent", 0)
        if coverage.get("passed", True):
            output.append(f"✅ Test Coverage: {coverage_percent:.1f}% (≥80% required)")
        else:
            all_passed = False
            output.append(f"❌ Test Coverage: {coverage_percent:.1f}% (below 80% threshold)")
            missing = coverage.get("missing_lines", 0)
            output.append(f"   📊 Missing coverage: {missing} lines")

        # Custom checks results
        custom = self.results.get("custom", {})
        if custom.get("passed", True):
            output.append("✅ Domain-Specific Rules: PASSED")
        else:
            all_passed = False
            violations = custom.get("total_violations", 0)
            total_issues += violations
            output.append(f"❌ Domain-Specific Rules: {violations} violations found")

            for violation in custom.get("violations", []):
                file_path = violation.get("file", "unknown")
                line = violation.get("line", "?")
                message = violation.get("message", "Unknown issue")
                output.append(f"   {file_path}:{line} - {message}")

        # Summary
        output.append("=" * 50)
        if all_passed:
            output.append("🎉 All quality checks PASSED!")
            output.append("Your code meets the project quality standards.")
        else:
            output.append(f"⚠️  Quality issues found: {total_issues} total violations")
            output.append("Review the issues above and address them to improve code quality.")
            output.append("(Note: This is running in advisory mode - builds are not blocked)")

        return "\n".join(output)

    def _format_github_output(self) -> str:
        """Format results for GitHub Actions output."""
        # This could be enhanced to use GitHub Actions annotations
        return self._format_text_output()


def main():
    """Main entry point for quality gate system."""
    import argparse

    parser = argparse.ArgumentParser(description="Bolster Quality Gate System")
    parser.add_argument("--format", choices=["text", "json", "github"], default="text", help="Output format")
    parser.add_argument(
        "--fail-on-issues", action="store_true", help="Exit with error code if quality issues found (blocking mode)"
    )
    parser.add_argument(
        "--coverage-threshold", type=int, default=80, help="Coverage threshold percentage (default: 80)"
    )

    args = parser.parse_args()

    reporter = QualityReporter()
    report = reporter.generate_report(args.format)
    print(report)

    # Determine exit code
    if args.fail_on_issues:
        # Check if any quality checks failed
        any_failed = any(not result.get("passed", True) for result in reporter.results.values())
        return 1 if any_failed else 0
    # Advisory mode - always return 0 (don't block builds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
