# API Contracts: NISRA Migration and Population Projections

This directory contains the public API contracts for the two new data source modules.

## Files

- `migration_official_api.py` - Public API for official migration statistics module
- `population_projections_api.py` - Public API for population projections module
- `cli_commands.py` - Optional CLI command specifications

## Contract Purpose

These contracts define:

1. Function signatures (parameters and return types)
1. Expected behavior and side effects
1. Error conditions and exception types
1. Example usage patterns

## Implementation Notes

- All functions must use type annotations
- All public functions must have Google-style docstrings
- Validation functions must return bool or raise exceptions (never return False)
- All modules must use shared utilities from `_base.py` where applicable

## See Also

- [plan.md](../plan.md) - Full implementation plan with detailed contracts
- [data-model.md](../data-model.md) - Data entity schemas and validation rules
- [quickstart.md](../quickstart.md) - Usage examples
