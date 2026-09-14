"""
Core test conftest — undo root conftest session-level mocks.

tests/conftest.py runs `patch(...).start()` at module level for the whole
pytest session, permanently replacing real classes with MagicMock:

    src.core.scheduler.Scheduler          -> MagicMock()
    src.core.orchestrator.RecipeOrchestrator -> MagicMock()
    src.core.memory_canonical.MemoryStore -> MagicMock()

That is correct for gateway tests (they import the real FastAPI app and
need the orchestrator stubbed so mission creation does not spin up a real
agent loop). It is wrong for the core unit tests, which construct the real
classes directly and assert on real attributes (job_count, dispatcher,
_data, OrchestrationStatus values).

Restoration runs at MODULE level here (not in a fixture) because the core
test modules do `from src.core.scheduler import Scheduler` at their top
(line 11 of test_scheduler.py), which binds the name at collection time.
A session fixture would run too late — after the test module already captured
the MagicMock. pytest collects conftest.py before the test modules in its
directory, so module-level restoration here runs first and the test modules
import the real class.

Restoration re-binds the real class onto the package attribute that
patch() mutated. patch() mutates the attribute on the *package* object
(src.core.orchestrator.__init__), not on the defining module
(src.core.orchestrator.runner), which was never patched. Importing the
defining module returns the real class; re-binding it onto the package makes
`from src.core.X import Y` in tests get the real implementation again.
"""

from __future__ import annotations

import importlib

# (package_attr, defining_module, class_name)
_RESTORE_TARGETS = (
    ("src.core.scheduler", "src.core.scheduler", "Scheduler"),
    ("src.core.orchestrator", "src.core.orchestrator.runner", "RecipeOrchestrator"),
    ("src.core.orchestrator", "src.core.orchestrator.models", "OrchestrationResult"),
    ("src.core.orchestrator", "src.core.orchestrator.models", "OrchestrationStatus"),
    ("src.core.memory_canonical", "src.core.memory_canonical", "MemoryStore"),
)

# Plain modules whose module-level names (functions, not classes) were
# patched by root conftest and must be re-executed from source. root
# conftest patches src.core.event_bus.get_event_bus -> MagicMock for the
# whole session; core tests that build a real CrashDetector need the real
# bus. crash_detector imported get_event_bus by name at import time, so
# reload event_bus first (re-creating the real function), then reload
# crash_detector (re-importing the real function from it).
for _mod_name in (
    "src.core.event_bus",
    "src.core.crash_detector",
):
    importlib.reload(importlib.import_module(_mod_name))

for _package_attr, _defining_module, _class_name in _RESTORE_TARGETS:
    if _package_attr == _defining_module:
        # patch() targeted the defining module itself (src.core.scheduler is a
        # plain module, not a package). importlib.import_module returns the
        # cached module whose attribute is already the mock, so reload the
        # module from source to re-create the real class.
        importlib.reload(importlib.import_module(_package_attr))
    else:
        # patch() targeted a package __init__ (src.core.orchestrator); the
        # defining submodule was never patched, so importing it returns the
        # real class. Re-bind it onto the package attribute.
        _pkg = importlib.import_module(_package_attr)
        _real_cls = getattr(importlib.import_module(_defining_module), _class_name)
        setattr(_pkg, _class_name, _real_cls)