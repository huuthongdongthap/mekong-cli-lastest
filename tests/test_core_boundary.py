# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Core/adapter boundary gate — static analysis only (ast.parse, no imports).

Architecture rule: ``src/core/`` is provider-neutral. Vendor SDKs
(``anthropic``, ``openai``) must NEVER be imported from core — provider
access goes through ``llm_router_adapter`` wrapping ``llm_client``.

Generic HTTP libraries (``requests``/``httpx``) are permitted only in the
documented allowlist below; every entry is an HTTP client module talking to
an internal gateway or external service, not a provider SDK. Adding a new
HTTP-lib importer to core requires a documented entry here.

Also pins the Buzz seam: ``runtime_adapter.py`` may reference buzz ONLY via
a lazy import inside ``run_from_payload`` — never at module level.

Adapters/import-neutrality gate (SUPER COMMAND #5, Task 1):
``src/core/`` must stay provider-neutral at the seam level — the core
spine (runtime_adapter, governance, protocols, capability, planner,
agent_registry, agent_base, mission_tracer, billing_adapter, agi_loop)
must not import adapter implementations (``src.core.adapters.*``,
buzz adapters, exec_runtime cloudflare/docker, payment_x402). Provider
access happens through ``llm_router_adapter`` / ``src.providers.llm``
lazy seams documented in the allowlist below.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = REPO_ROOT / "src" / "core"

VENDOR_SDKS = frozenset({"anthropic", "openai"})
HTTP_LIBS = frozenset({"requests", "httpx"})

# Sanctioned adapter-implementation import sites in the core spine
# (repo-root-relative path -> reason). Every entry is a *lazy* import
# (inside function/method body) that the runtime makes when actually
# wiring an adapter, not a module-level binding that would pull an
# adapter implementation into the import graph of ``src.core``.
#
# Verified 2026-08-29 at 7c5f64093 (SUPER COMMAND #5 Task 1, E1).
# Adding a new adapter-impl import to the core spine requires a
# documented entry here — otherwise the boundary test fails loud.
ADAPTER_IMPORT_ALLOWLIST: dict[str, str] = {
    "src/core/runtime_adapter.py": (
        "lazy `from src.core.buzz_adapter import BuzzAdapter` inside "
        "`run_from_payload` — sanctioned buzz seam (buzz is optional core, "
        "no-op default preserves backward compatibility)"
    ),
    "src/core/planner.py": (
        "lazy `from src.providers.llm.client import get_client` inside "
        "`_plan_with_llm` (line 378) + TYPE_CHECKING-only `LLMClient` "
        "import (line 17) — `src.providers.llm.client` is the canonical "
        "multi-provider LLM client (622 lines); planner calls it lazily so "
        "rule-based planning does not require an LLM provider to be installed"
    ),
    "src/core/agi_loop.py": (
        "lazy `from src.providers.llm.client import get_client` inside "
        "the self-improvement assessment step (line 303) — same canonical "
        "provider client; only invoked when an LLM is actually available"
    ),
}

# Provider-implementation modules that must NEVER be pulled into the
# import graph of ``src.core`` (verified by the runtime import-neutrality
# test below). These sit outside the core spine; the core spine talks to
# them only through lazy seams documented in ADAPTER_IMPORT_ALLOWLIST.
PROVIDER_MODULES_BLOCKED = frozenset({
    "src.core.adapters.llm.client",
    "src.core.adapters.payment_x402",
    "src.core.buzz_adapter",
    "src.core.buzz_runtime_adapter",
    "src.core.exec_runtime.cloudflare",
    "src.core.exec_runtime.docker",
    "src.core.mcp_server",
    "src.providers.llm.client",
})

# Adapter-implementation prefixes the core spine must not bind at
# module level. Resolved against the repo root so both absolute
# (``src.core.adapters...``) and relative (``.adapters...``) forms match
# the same site; this catches a future relative-leak before it ships.
ADAPTER_IMPL_PREFIXES: tuple[str, ...] = (
    "src.core.adapters.",
    "src.core.buzz_adapter",
    "src.core.buzz_runtime_adapter",
    "src.core.exec_runtime.cloudflare",
    "src.core.exec_runtime.docker",
    "src.core.exec_runtime.",
    "payment_x402",
)

# Canonical core-spine modules (SUPER COMMAND #5 Task 1).
# The test below walks this list — not the whole src/core/ tree — so a
# future move of, say, gateway code into src/core/ does not silently
# widen the boundary check.
CORE_SPINE_FILES: tuple[str, ...] = (
    "src/core/runtime_adapter.py",
    "src/core/governance.py",
    "src/core/protocols.py",
    "src/core/capability.py",
    "src/core/planner.py",
    "src/core/agent_registry.py",
    "src/core/agent_base.py",
    "src/core/mission_tracer.py",
    "src/core/billing_adapter.py",
    "src/core/agi_loop.py",
)

# Documented allowlist for generic HTTP libs in src/core/ (repo-root-relative
# path -> reason). Verified by grep on 2026-08-26 at d6138541a + E1 changes.
HTTP_LIB_ALLOWLIST: dict[str, str] = {
    "src/core/plugin_marketplace.py": "httpx client for the plugin marketplace API",
    "src/core/gateway/gateway_main.py": "httpx used by the in-process gateway app",
    "src/core/activation_sync.py": "requests client syncing activation state with the gateway",
    "src/core/agi_loop.py": "lazy requests import posting Telegram updates from the self-improvement loop",
    "src/core/executor.py": "lazy requests import executing API recipe steps (SSRF-guarded)",
    "src/core/gateway_api.py": "requests client for the public AgencyOS gateway API",
    "src/core/gateway_client/__init__.py": "requests-based gateway client package",
    "src/core/health_reporter.py": "requests client reporting health to the gateway",
    "src/core/image_generator.py": "requests client calling the DashScope/Qwen image endpoint",
    "src/core/memory_client.py": "requests client for the NeuralMemory service",
    "src/core/providers.py": "lazy httpx import probing the LiteLLM provider health endpoint",
    "src/core/raas_audit_logger.py": "requests client flushing audit records to the gateway",
    "src/core/raas_auth/__init__.py": "requests-based RaaS auth client package",
    "src/core/raas_auth/auth_gateway_mixin.py": "requests-based RaaS auth gateway mixin",
    "src/core/rate_limit_client.py": "requests client for the rate-limit service",
    "src/core/swarm.py": "requests client used by the swarm registry for remote agents",
    "src/core/telegram_client.py": "requests client for the Telegram Bot API",
    "src/core/telemetry_reporter.py": "lazy requests import flushing telemetry to the gateway",
}


def _core_python_files() -> list[Path]:
    return sorted(p for p in CORE_DIR.rglob("*.py"))


def _top_module(node: ast.Import | ast.ImportFrom) -> str | None:
    if isinstance(node, ast.Import):
        return node.names[0].name.split(".")[0]
    return (node.module or "").split(".")[0] or None


def _full_module(node: ast.Import | ast.ImportFrom) -> str:
    if isinstance(node, ast.Import):
        return node.names[0].name
    return node.module or ""


def _collect_imports(tree: ast.AST) -> list[tuple[int, str]]:
    """All (lineno, top-level module) pairs for Import/ImportFrom nodes."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = _top_module(node)
            if module:
                out.append((node.lineno, module))
    return out


def _parse_all_core_files() -> dict[Path, ast.Module]:
    trees: dict[Path, ast.Module] = {}
    assert CORE_DIR.is_dir(), f"core directory missing: {CORE_DIR}"
    for path in _core_python_files():
        try:
            trees[path] = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            pytest.fail(f"src/core file does not parse: {path} ({exc})")
    assert trees, "no python files found under src/core/"
    return trees


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


class TestVendorSdkBoundary:
    def test_no_vendor_sdk_imports_anywhere_in_core(self):
        violations: list[str] = []
        for path, tree in _parse_all_core_files().items():
            for lineno, module in _collect_imports(tree):
                if module in VENDOR_SDKS:
                    violations.append(f"{_rel(path)}:{lineno} imports '{module}'")
        assert not violations, (
            "src/core/ must stay provider-neutral — vendor SDK imports found:\n  "
            + "\n  ".join(violations)
            + "\nRoute provider access through llm_router_adapter/llm_client instead."
        )


class TestHttpLibAllowlist:
    def test_http_lib_imports_only_in_documented_allowlist(self):
        violations: list[str] = []
        for path, tree in _parse_all_core_files().items():
            rel = _rel(path)
            if rel in HTTP_LIB_ALLOWLIST:
                continue
            for lineno, module in _collect_imports(tree):
                if module in HTTP_LIBS:
                    violations.append(f"{rel}:{lineno} imports '{module}'")
        assert not violations, (
            "HTTP-lib import outside the documented allowlist:\n  "
            + "\n  ".join(violations)
            + "\nAdd a documented allowlist entry only if the module is a "
            "legitimate HTTP client; otherwise route through an adapter."
        )

    def test_allowlist_entries_exist_and_still_import_http_libs(self):
        trees = _parse_all_core_files()
        by_rel = {_rel(path): tree for path, tree in trees.items()}
        stale: list[str] = []
        for rel in HTTP_LIB_ALLOWLIST:
            tree = by_rel.get(rel)
            if tree is None:
                stale.append(f"{rel} (file no longer exists)")
                continue
            modules = {module for _, module in _collect_imports(tree)}
            if not modules & HTTP_LIBS:
                stale.append(f"{rel} (no longer imports requests/httpx)")
        assert not stale, (
            "Stale allowlist entries — remove them from this test:\n  "
            + "\n  ".join(stale)
        )


def _function_span(func: ast.FunctionDef | None) -> tuple[int, int] | None:
    """Return (start, end) line range of a function/method, inclusive."""
    if func is None or func.end_lineno is None:
        return None
    return (func.lineno, func.end_lineno)


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    """Find a function or method named `name` anywhere in the module tree."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == name:
                    return child
        elif isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _spine_trees() -> dict[Path, ast.Module]:
    """Parse every core-spine file (subset of _parse_all_core_files)."""
    trees: dict[Path, ast.Module] = {}
    for rel in CORE_SPINE_FILES:
        path = REPO_ROOT / rel
        assert path.is_file(), f"core spine file missing: {rel}"
        trees[path] = ast.parse(
            path.read_text(encoding="utf-8"), filename=str(path)
        )
    assert trees, "no core spine files found"
    return trees


def _resolve_spine_import(node: ast.Import | ast.ImportFrom) -> list[tuple[int, str]]:
    """Resolve an import node against the repo root.

    Relative imports (``from .parser import X`` inside src/core/) are
    rewritten to their absolute form (``src.core.parser``) so prefix
    checks cannot be dodged by importing relatively.
    """
    out: list[tuple[int, str]] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            out.append((node.lineno, alias.name))
        return out
    module = node.module or ""
    if node.level > 0:
        module = f"src.core.{module}" if module else "src.core"
    if node.module is None:
        # ``from . import adapters`` — bind the package itself.
        for alias in node.names:
            out.append((node.lineno, f"{module}.{alias.name}"))
    else:
        out.append((node.lineno, module))
    return out


class TestAdapterImportNeutrality:
    """Core spine must not import adapter implementations.

    Adapter access is allowed ONLY via the documented lazy seams in
    ADAPTER_IMPORT_ALLOWLIST; binding an adapter implementation at
    module level (or importing one outside the sanctioned site) is a
    boundary violation and fails loud.
    """

    def test_no_adapter_impl_imports_outside_allowlist(self):
        violations: list[str] = []
        for path, tree in _spine_trees().items():
            rel = _rel(path)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                for lineno, module in _resolve_spine_import(node):
                    if module.startswith(ADAPTER_IMPL_PREFIXES):
                        if rel in ADAPTER_IMPORT_ALLOWLIST:
                            continue
                        violations.append(
                            f"{rel}:{lineno} imports '{module}'"
                        )
        assert not violations, (
            "Core spine must not import adapter implementations — "
            "provider-neutral core, adapter access only via documented "
            "lazy seams:\n  " + "\n  ".join(violations)
            + "\nIf this import is intentional, add a documented entry "
            "to ADAPTER_IMPORT_ALLOWLIST (mirror HTTP_LIB_ALLOWLIST style)."
        )

    def test_allowlisted_spine_seams_are_lazy_not_module_level(self):
        """Every allowlisted site must be a lazy (in-function) import."""
        violations: list[str] = []
        for path, tree in _spine_trees().items():
            rel = _rel(path)
            if rel not in ADAPTER_IMPORT_ALLOWLIST:
                continue
            module_level = [
                node
                for node in tree.body
                if isinstance(node, (ast.Import, ast.ImportFrom))
                and any(
                    module.startswith(ADAPTER_IMPL_PREFIXES)
                    for _, module in _resolve_spine_import(node)
                )
            ]
            if module_level:
                violations.append(
                    f"{rel} binds an adapter impl at module level "
                    f"(line {module_level[0].lineno}) — allowlisted seams "
                    "must be lazy imports inside a function/method body"
                )
        assert not violations, (
            "Allowlisted adapter seams must stay lazy:\n  "
            + "\n  ".join(violations)
        )

    def test_buzz_imports_confined_to_run_from_payload(self):
        """buzz imports in the whole spine, not just runtime_adapter."""
        violations: list[str] = []
        for path, tree in _spine_trees().items():
            rel = _rel(path)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                for lineno, module in _resolve_spine_import(node):
                    if not module.startswith(("src.core.buzz_adapter", "src.core.buzz_runtime_adapter")):
                        continue
                    if rel == "src/core/runtime_adapter.py" and rel in ADAPTER_IMPORT_ALLOWLIST:
                        # TestBuzzSeam pins the single sanctioned buzz
                        # site: lazy import inside run_from_payload.
                        continue
                    violations.append(f"{rel}:{lineno} imports '{module}'")
        assert not violations, (
            "buzz adapter imports outside the sanctioned run_from_payload "
            "seam:\n  " + "\n  ".join(violations)
        )


class TestImportNeutrality:
    """Runtime proof that importing src.core pulls no provider modules.

    Task 1 acceptance: ``python -c "import src.core"`` must not pull in
    any provider module. Runs in a pristine subprocess so the ambient
    test session's import graph cannot mask a violation.
    """

    def test_import_core_does_not_pull_provider_modules(self):
        code = textwrap.dedent(
            """
            import sys
            import src.core
            for name in {blocked!r}:
                assert name not in sys.modules, (
                    f"import src.core pulled provider module: {{name}}"
                )
            """
        ).format(blocked=sorted(PROVIDER_MODULES_BLOCKED))
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"import src.core pulled provider modules:\n{result.stdout}\n{result.stderr}"
        )

    def test_import_all_spine_modules_stays_provider_neutral(self):
        """Import every spine module explicitly; still no provider pull."""
        code = textwrap.dedent(
            """
            import sys
            import src.core
            for mod in {spine!r}:
                __import__(mod)
            for name in {blocked!r}:
                assert name not in sys.modules, (
                    f"importing core spine pulled provider module: {{name}}"
                )
            """
        ).format(
            spine=[
                rel.replace("/", ".").removesuffix(".py")
                for rel in CORE_SPINE_FILES
            ],
            blocked=sorted(PROVIDER_MODULES_BLOCKED),
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"core spine import pulled provider modules:\n{result.stdout}\n{result.stderr}"
        )


class TestBuzzSeam:
    def test_buzz_import_is_lazy_inside_run_from_payload_only(self):
        path = CORE_DIR / "runtime_adapter.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        module_level = [
            node
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            and _full_module(node).startswith("src.core.buzz")
        ]
        assert not module_level, (
            "buzz_adapter must not be imported at module level in runtime_adapter.py"
        )

        func = _find_function(tree, "run_from_payload")
        assert func is not None, "run_from_payload missing from runtime_adapter.py"

        lazy = [
            node
            for node in ast.walk(func)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            and _full_module(node).startswith("src.core.buzz")
        ]
        assert lazy, (
            "run_from_payload must lazily import buzz_adapter inside the function body"
        )

    def test_no_buzz_reference_outside_run_from_payload(self):
        path = CORE_DIR / "runtime_adapter.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        sanctioned = _find_function(tree, "run_from_payload")
        assert sanctioned is not None

        leaks: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)) and _full_module(
                node
            ).startswith("src.core.buzz"):
                if any(node.lineno >= n.lineno and node.end_lineno <= n.end_lineno
                       for n in [sanctioned] if n.end_lineno):
                    continue
                owner = "<module>"
                for top in tree.body:
                    if (
                        isinstance(top, (ast.ClassDef, ast.FunctionDef))
                        and top.lineno <= node.lineno
                        and (top.end_lineno or 0) >= node.lineno
                    ):
                        owner = f"{type(top).__name__}:{top.name}"
                        break
                leaks.append(f"{owner} line {node.lineno}")
        assert not leaks, (
            "buzz import found outside run_from_payload:\n  " + "\n  ".join(leaks)
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
