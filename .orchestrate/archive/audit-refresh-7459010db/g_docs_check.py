#!/usr/bin/env python3
"""G-DOCS mechanical gate: every repo path cited in the seven audit docs must exist at HEAD.

Extracts path-like tokens from docs/architecture/*.md and verifies each against
the working tree. Ignores URLs, line-number refs, and known non-path tokens.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOC_DIR = REPO / "docs" / "architecture"
DOCS = [
    "CURRENT_ARCHITECTURE.md",
    "DEPENDENCY_MAP.md",
    "DUPLICATION_MAP.md",
    "DEPRECATION_MAP.md",
    "AUTONOMY_GAPS.md",
    "MEKONG_CORE_CONTRACT.md",
    "ARCHITECTURE_ASSESSMENT.md",
]

# Tokens that look like paths but are not repo-relative file/dir references.
IGNORE_PREFIXES = ("http", "docs/architecture/", ".orchestrate/")
ALLOW_MISSING_DIRS = {"src", "tests", "engine", "factory"}  # bare package roots


def extract_paths(text: str) -> set[str]:
    # Match src/..., tests/..., engine/..., factory/... style repo paths.
    pattern = re.compile(
        r"\b((?:src|tests|engine|factory|integrations|recipes|workflows|observability|specs|dna|agents|sops|evals|cli)/[A-Za-z0-9_\-./]+)"
    )
    found = set()
    for m in pattern.finditer(text):
        p = m.group(1).rstrip(".,;:)`*'")
        p = re.sub(r":[0-9]+(-[0-9]+)?$", "", p)  # strip :line refs
        if p.startswith(IGNORE_PREFIXES):
            continue
        if any(ch in p for ch in ("<", ">", "|", " ", "{")):
            continue
        if p.endswith("_"):  # glob prefix like nowpayments_* or tests/test_*
            continue
        if p.endswith((".py", ".md", ".json", ".yaml", ".yml", ".sh", ".rb", ".js", ".legacy", "/")):
            found.add(p.rstrip("/"))
        elif "/" in p and "." not in Path(p).name:
            found.add(p)
    return found


def main() -> int:
    dangling: dict[str, list[str]] = {}
    total = 0
    for name in DOCS:
        path = DOC_DIR / name
        if not path.exists():
            print(f"MISSING DOC: {path}")
            return 2
        text = path.read_text()
        for p in sorted(extract_paths(text)):
            total += 1
            if p in ALLOW_MISSING_DIRS:
                continue
            if not (REPO / p).exists():
                dangling.setdefault(name, []).append(p)

    print(f"G-DOCS check: {total} cited paths across {len(DOCS)} docs")
    if dangling:
        print("DANGLING REFERENCES FOUND:")
        for doc, paths in dangling.items():
            for p in paths:
                print(f"  {doc}: {p}")
        return 1
    print("PASS: zero dangling references")
    return 0


if __name__ == "__main__":
    sys.exit(main())
