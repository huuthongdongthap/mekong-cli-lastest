"""Smoke tests: verify ak-init and mk-init Claude bridge files exist
and document the ak v2.4.0 contract (ownership.json, drift, exit 6, flags).
"""

from __future__ import annotations

from pathlib import Path


REQUIRED_KEYWORDS: tuple[str, ...] = (
    "ownership.json",
    "--dry-run",
    "--force",
    "--project-id",
    "--json",
    "ak new",
    "drift",
    "6",
)

AK_INIT_PATH: Path = Path.home() / ".claude" / "commands" / "ak-init.md"
MK_INIT_PATH: Path = Path.home() / ".claude" / "commands" / "mk-init.md"


class TestAkInitBridgeExists:
    def test_ak_init_bridge_exists(self) -> None:
        """User-global /ak:init bridge file exists."""
        assert AK_INIT_PATH.exists(), f"missing: {AK_INIT_PATH}"

    def test_mk_init_bridge_exists(self) -> None:
        """User-global /mk:init bridge file exists."""
        assert MK_INIT_PATH.exists(), f"missing: {MK_INIT_PATH}"

    def test_ak_init_contains_all_keywords(self) -> None:
        """ak-init.md covers every required ak v2.4.0 keyword."""
        content = AK_INIT_PATH.read_text(encoding="utf-8")
        missing = [kw for kw in REQUIRED_KEYWORDS if kw not in content]
        assert not missing, f"ak-init.md missing keywords: {missing}"

    def test_mk_init_contains_all_keywords(self) -> None:
        """mk-init.md covers every required ak v2.4.0 keyword."""
        content = MK_INIT_PATH.read_text(encoding="utf-8")
        missing = [kw for kw in REQUIRED_KEYWORDS if kw not in content]
        assert not missing, f"mk-init.md missing keywords: {missing}"

    def test_ak_init_does_not_delegate_to_stale_cli(self) -> None:
        """ak-init.md must route via $HOME/bin/ak init (not mekong/mk CLI)."""
        content = AK_INIT_PATH.read_text(encoding="utf-8")
        assert "$HOME/bin/ak init" in content, "ak-init.md must delegate to $HOME/bin/ak init"

    def test_mk_init_delegates_to_bin_ak(self) -> None:
        """mk-init.md must route via $HOME/bin/ak init (Mekong CLI bridge)."""
        content = MK_INIT_PATH.read_text(encoding="utf-8")
        assert "$HOME/bin/ak init" in content, "mk-init.md must delegate to $HOME/bin/ak init"
