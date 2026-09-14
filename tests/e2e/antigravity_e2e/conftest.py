import pytest
import os
from pathlib import Path

@pytest.fixture(scope="session", autouse=True)
def mock_api_keys():
    # Set mock ANTHROPIC_API_KEY if not present, to prevent fallback in E2E tests
    if not os.environ.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = "mock_api_key_for_testing"

@pytest.fixture(scope="session")
def antigravity_bin():
    # Use environment variable or fallback to python mock CLI shim
    default_shim = str(Path(__file__).parents[1] / "mock_antigravity.py")
    bin_path = os.getenv("ANTIGRAVITY_BIN", f"python3 {default_shim}")
    return bin_path


def _resolve_db_path() -> Path:
    custom = os.getenv("ANTIGRAVITY_DB")
    if custom:
        return Path(custom).resolve()
    git_ref = Path(".git")
    if git_ref.is_file():
        try:
            content = git_ref.read_text().strip()
            if content.startswith("gitdir:"):
                raw_target = content.split(":", 1)[1].strip()
                target = Path(raw_target).resolve()
                if target.is_dir() and ".git" in target.parts:
                    return target / "antigravity" / "session.db"
        except Exception:
            pass
        return (Path.cwd() / ".antigravity" / "session.db").resolve()
    return (Path.cwd() / ".git" / "antigravity" / "session.db").resolve()


@pytest.fixture(scope="function")
def clean_db():
    db_path = _resolve_db_path()
    if db_path.exists():
        try:
            db_path.unlink()
        except Exception:
            pass
    for ext in ["-wal", "-shm"]:
        p = Path(str(db_path) + ext)
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
                
    yield db_path
    
    if db_path.exists():
        try:
            db_path.unlink()
        except Exception:
            pass
    for ext in ["-wal", "-shm"]:
        p = Path(str(db_path) + ext)
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
