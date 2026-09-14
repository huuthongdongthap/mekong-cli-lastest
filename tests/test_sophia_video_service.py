# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Unit tests for Sophia AI Video Factory Service (Funnel 3).

Tests:
- Catalog queries (avatars, voices, templates) with filtering
- Input validation and injection defenses (sanitize_script, validate_identifier, validate_job_id)
- MCU cost estimation logic and template multipliers
- Video rendering execution with dry-run and offline fallback
- Design DNA styling integration via load_approved
- Job state persistence and retrieval
- Multi-tenant isolation and listing
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.services.sophia_video_service import (
    AspectRatio,
    JobStatus,
    SophiaVideoService,
    VideoRenderRequest,
    sanitize_script,
    validate_identifier,
    validate_job_id,
)


@pytest.fixture
def temp_storage(tmp_path: Path) -> Path:
    storage = tmp_path / "sophia_storage"
    storage.mkdir(parents=True, exist_ok=True)
    return storage


@pytest.fixture
def service(temp_storage: Path) -> SophiaVideoService:
    return SophiaVideoService(storage_dir=temp_storage, enable_billing=False)


# ---------------------------------------------------------------------------
# Test Catalog & Queries
# ---------------------------------------------------------------------------

class TestSophiaCatalog:
    """Verify avatar, voice, and template catalogs."""

    def test_list_avatars_all(self, service: SophiaVideoService) -> None:
        avatars = service.list_avatars()
        assert len(avatars) >= 4
        ids = [a.id for a in avatars]
        assert "sophia-anchor-vi-01" in ids
        assert "sophia-presenter-vi-02" in ids
        assert "avatar-female-business-01" in ids

    def test_list_avatars_filter_gender(self, service: SophiaVideoService) -> None:
        females = service.list_avatars(gender="female")
        assert len(females) >= 2
        assert all(a.gender == "female" for a in females)

        males = service.list_avatars(gender="male")
        assert len(males) >= 2
        assert all(a.gender == "male" for a in males)

    def test_list_voices_all(self, service: SophiaVideoService) -> None:
        voices = service.list_voices()
        assert len(voices) >= 4
        ids = [v.id for v in voices]
        assert "elevenlabs-vi-hoang-01" in ids
        assert "elevenlabs-vi-mai-02" in ids

    def test_list_voices_filter_language(self, service: SophiaVideoService) -> None:
        vi_voices = service.list_voices(language="vi")
        assert len(vi_voices) >= 2
        assert all("vi" in v.language.lower() for v in vi_voices)

        en_voices = service.list_voices(language="en")
        assert len(en_voices) >= 2
        assert all("en" in v.language.lower() for v in en_voices)

    def test_list_templates(self, service: SophiaVideoService) -> None:
        templates = service.list_templates()
        assert len(templates) >= 4
        ids = [t.id for t in templates]
        assert "news_anchor" in ids
        assert "faceless_explainer" in ids
        assert "product_showcase" in ids
        assert "youtube_deepdive" in ids


# ---------------------------------------------------------------------------
# Test Input Validation & Injection Defenses
# ---------------------------------------------------------------------------

class TestSophiaValidation:
    """Verify strict sanitization and security guards."""

    def test_validate_identifier_success(self) -> None:
        assert validate_identifier("valid_name-123") == "valid_name-123"
        assert validate_identifier("tenant.demo") == "tenant.demo"

    def test_validate_identifier_rejects_flags_and_injection(self) -> None:
        unsafe = ["--flag", "-v", "; rm -rf", "name&echo", "a`id`b", "name|whoami"]
        for val in unsafe:
            with pytest.raises(ValueError):
                validate_identifier(val)

    def test_validate_job_id_success(self) -> None:
        assert validate_job_id("sophia-demo-video-12345678") == "sophia-demo-video-12345678"

    def test_validate_job_id_rejects_malformed(self) -> None:
        invalid = ["job-123", "sophia-short", "sophia;whoami", "../etc/passwd"]
        for val in invalid:
            with pytest.raises(ValueError):
                validate_job_id(val)

    def test_sanitize_script_success(self) -> None:
        valid_script = "Chào mừng bạn đến với kênh AI Video Factory của Mekong CLI."
        assert sanitize_script(valid_script) == valid_script

    def test_sanitize_script_too_short(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            sanitize_script("Hi")

    def test_sanitize_script_forbidden_characters(self) -> None:
        unsafe = [
            "Video script with dangerous character ; rm -rf /",
            "Video script with backticks `reboot` here",
            "Video script with shell variable $PATH injection",
        ]
        for val in unsafe:
            with pytest.raises(ValueError, match="Forbidden character"):
                sanitize_script(val)


# ---------------------------------------------------------------------------
# Test Cost Estimation
# ---------------------------------------------------------------------------

class TestSophiaCostEstimation:
    """Verify MCU calculation and billing blocks."""

    def test_estimate_cost_standard(self, service: SophiaVideoService) -> None:
        cost = service.estimate_cost(duration_seconds=25, template="news_anchor")
        assert cost["estimated_mcu"] == 50
        assert cost["billing_blocks"] == 1

        cost_60s = service.estimate_cost(duration_seconds=60, template="news_anchor")
        assert cost_60s["estimated_mcu"] == 100
        assert cost_60s["billing_blocks"] == 2

    def test_estimate_cost_deepdive_multiplier(self, service: SophiaVideoService) -> None:
        cost = service.estimate_cost(duration_seconds=60, template="youtube_deepdive")
        # 100 * 1.5 = 150 MCU
        assert cost["estimated_mcu"] == 150

    def test_estimate_cost_rejects_negative_or_zero(self, service: SophiaVideoService) -> None:
        with pytest.raises(ValueError):
            service.estimate_cost(0)
        with pytest.raises(ValueError):
            service.estimate_cost(-15)


# ---------------------------------------------------------------------------
# Test Video Rendering & Persistence
# ---------------------------------------------------------------------------

class TestSophiaRendering:
    """Verify render execution, state transitions, and file persistence."""

    def test_render_video_dry_run(self, service: SophiaVideoService) -> None:
        req = VideoRenderRequest(
            title="Introduction to Vietnam Business AI",
            script="Chào mừng các bạn đã quay trở lại với Mekong CLI. Hôm nay chúng ta sẽ tìm hiểu về tự động hoá thuế.",
            aspect_ratio=AspectRatio.VERTICAL_9_16,
            template="news_anchor",
            tenant_id="tenant-test",
            dry_run=True,
        )

        result = service.render_video(req)
        assert result.status == JobStatus.COMPLETED
        assert result.progress == 100
        assert result.job_id.startswith("sophia-")
        assert result.duration_seconds > 0
        assert result.credits_used >= 50
        assert result.local_artifact_path is not None
        assert Path(result.local_artifact_path).exists()

        # Check that job was persisted to disk
        fetched = service.get_job_status(result.job_id)
        assert fetched.job_id == result.job_id
        assert fetched.title == req.title
        assert fetched.status == JobStatus.COMPLETED

    def test_render_with_design_dna(self, service: SophiaVideoService) -> None:
        mock_dna = MagicMock()
        mock_dna.identity = "Mekong Brand"
        mock_dna.color_anchor = "#0052CC"
        mock_dna.typography = "Inter, sans-serif"
        mock_dna.type_pairing = "Inter / Roboto"
        mock_dna.surface_treatment = "glassmorphism"
        mock_dna.density = MagicMock(value="compact")

        with patch("src.design_intelligence.design_memory.load_approved", return_value=mock_dna):
            req = VideoRenderRequest(
                title="Branded Video Promo",
                script="Trải nghiệm công nghệ AI Video Factory với phong cách nhận diện thương hiệu tự động.",
                design_dna_name="mekong-brand-dna",
                dry_run=True,
            )
            result = service.render_video(req)
            assert result.design_dna_applied == "mekong-brand-dna"
            assert result.metadata["dna_styling"]["color_anchor"] == "#0052CC"

    def test_get_job_status_not_found(self, service: SophiaVideoService) -> None:
        with pytest.raises(FileNotFoundError):
            service.get_job_status("sophia-non-existent-12345678")

    def test_list_jobs_for_tenant(self, service: SophiaVideoService) -> None:
        # Render 2 jobs for tenant A, 1 for tenant B
        for i in range(2):
            service.render_video(
                VideoRenderRequest(
                    title=f"Tenant A Video {i}",
                    script="Nội dung kịch bản cho tenant A kiểm thử chức năng danh sách video.",
                    tenant_id="tenant-a",
                    dry_run=True,
                )
            )
        service.render_video(
            VideoRenderRequest(
                title="Tenant B Video 0",
                script="Nội dung kịch bản cho tenant B kiểm thử chức năng danh sách video.",
                tenant_id="tenant-b",
                dry_run=True,
            )
        )

        jobs_a = service.list_jobs(tenant_id="tenant-a")
        assert len(jobs_a) == 2
        assert all(j.metadata["tenant_id"] == "tenant-a" for j in jobs_a)

        jobs_b = service.list_jobs(tenant_id="tenant-b")
        assert len(jobs_b) == 1

        all_jobs = service.list_jobs(tenant_id="all")
        assert len(all_jobs) == 3
