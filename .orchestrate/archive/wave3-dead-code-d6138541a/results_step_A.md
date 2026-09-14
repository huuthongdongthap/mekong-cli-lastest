# Step A Results — Fix command_fabric/router.py import path

## Changes Applied
- **A1**: `from cli.tui.router import ...` → `from src.cli.tui.router import ...` (line 25)
- **A2**: Docstring comment `from cli.tui.router directly` → `from src.cli.tui.router directly` (line 33)

## Acceptance Criteria
```bash
python3 -c "from src.command_fabric.router import route_command, RouteTable; print('A-OK')"
# Output: A-OK ✓
```

## Ruff
```bash
python3 -m ruff check src/command_fabric/router.py
# Output: All checks passed! ✓
```

## Related Tests
- `tests/test_nl_routing.py`: 47 failed — all pre-existing in baseline (lines 156-202 of failed_tests_head_0878f966f.txt = 47 nl_routing failures). Zero new regressions.

## Deviation
None. Exact plan applied.
