# Pull Request

## Description

Brief description of the changes in this PR.

## Type of Change

<!-- Select the type of change this PR introduces -->

- \[ \] 🐛 Bug fix (non-breaking change which fixes an issue)
- \[ \] ✨ New feature (non-breaking change which adds functionality)
- \[ \] 💥 Breaking change (fix or feature that would cause existing functionality to change)
- \[ \] 📚 Documentation update
- \[ \] 🔧 Maintenance (dependency updates, CI, etc.)
- \[ \] 🧪 Tests only

## Version Impact

<!-- This will be auto-detected, but you can override by adding a label -->

Expected version bump: **Auto-detected based on changes**

To override automatic detection, add one of these labels:

- `version:major` - For breaking changes (1.0.0 → 2.0.0)
- `version:minor` - For new features (1.0.0 → 1.1.0)
- `version:patch` - For bug fixes (1.0.0 → 1.0.1)
- `version:skip` - Skip release (docs/CI only changes)

## Testing

- \[ \] Tests pass locally (`uv run pytest tests/ -v`)
- \[ \] Linting passes (`uv run pre-commit run --all-files`)
- \[ \] New functionality has tests
- \[ \] Documentation updated (if applicable)

## Data Source Checklist

<!-- For new data source modules only -->

- \[ \] Module follows existing patterns (check similar modules)
- \[ \] Uses shared utilities from `_base.py`
- \[ \] Uses `web.session` for HTTP requests (not raw `requests.get()`)
- \[ \] Type hints on public functions
- \[ \] Docstrings with Args/Returns/Example sections
- \[ \] Real data tests with `scope="class"` fixtures
- \[ \] CLI command added and working
- \[ \] README coverage table updated
- \[ \] Includes 2-3 example insights from the data

## Breaking Changes

<!-- If this is a breaking change, describe what breaks and how to migrate -->

N/A

## Additional Notes

<!-- Any additional information that reviewers should know -->

______________________________________________________________________

**Note**: When this PR is merged to `main`, it will automatically trigger a release if it contains meaningful changes. Version bump will be determined by conventional commits and PR labels.
