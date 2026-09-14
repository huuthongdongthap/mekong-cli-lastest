# Step C Results — Fix agi_bridge.py start() fail-loud + consumer update

## Changes Applied
- **C1**: `return False` → `raise FileNotFoundError(...)` when entry script missing (line 35-36)
- **C2**: `except FileNotFoundError: return False` → `except FileNotFoundError: raise` + added `except OSError as exc: raise RuntimeError(...)` (lines 47-48)
- **C3**: Updated `src/commands/agi.py` consumer to catch `FileNotFoundError` and `RuntimeError` instead of checking boolean return (lines 25-31)

## Acceptance Criteria
```bash
python3 -c "
from src.agents.agi_bridge import AGIBridge
import tempfile
b = AGIBridge(mekong_dir=tempfile.mkdtemp())
try:
    b.start()
    print('FAIL: should have raised')
except FileNotFoundError as e:
    assert 'task-watcher.js' in str(e)
    print('C-OK')
"
# Output: C-OK ✓
```

## Ruff
```bash
python3 -m ruff check src/agents/agi_bridge.py src/commands/agi.py
# Output: All checks passed! ✓
```

## Related Tests
- `tests/test_command_fabric_adapters.py`: 5 failed — all pre-existing in baseline (lines 26-30). Zero new regressions.
- No direct unit tests for AGIBridge or agi.py commands in test suite.

## Deviation
None. Exact plan applied.
