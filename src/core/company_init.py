# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Company Init Wizard — /company init backend.

Mekong company-config init — NOT AgentKit ``ak init``. Generates 12 config
files for a new solo agentic company into ``.mekong/``.
For AgentKit ownership initialization, use ``ak init`` (or ``/ak:init``).

5-question wizard that generates 12 config files for a new solo agentic company.
Supports both CLI (interactive) and API (dict input) modes.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from src.core.mcu_gate import MCUGate

logger = logging.getLogger(__name__)

# Type aliases
Scenario = Literal["local_first", "hybrid", "api_only", "apple_silicon"]
BudgetTier = Literal["zero", "minimal", "hybrid", "unlimited"]
Language = Literal["vi", "en", "both"]
ProductType = Literal["saas", "digital", "api_service", "consulting"]

PRODUCT_MAP = {"1": "saas", "2": "digital", "3": "api_service", "4": "consulting"}
SCENARIO_MAP = {"1": "local_first", "2": "hybrid", "3": "api_only", "4": "apple_silicon"}
BUDGET_MAP = {"1": "zero", "2": "minimal", "3": "hybrid", "4": "unlimited"}
LANGUAGE_MAP = {"1": "vi", "2": "en", "3": "both"}

TIER_MCU_SEED = {"starter": 100, "growth": 500, "premium": 2000}

COST_ESTIMATES = {
    "local_first": "~$27/mo (Ollama only + minimal API)",
    "hybrid": "~$52-65/mo",
    "api_only": "~$145/mo",
    "apple_silicon": "~$35/mo (Metal acceleration)",
}


@dataclass
class CompanyConfig:
    """Wizard output — all 5 answers."""

    company_name: str
    product_type: ProductType
    scenario: Scenario
    budget_tier: BudgetTier
    primary_language: Language


def _resolve_model(scenario: str, role: str, tier: str) -> str:
    """Pick model for an agent role based on scenario."""
    local_available = scenario in ("local_first", "hybrid", "apple_silicon")

    routing: dict[str, dict[str, str]] = {
        "cto": {
            "complex": "claude-opus-4-6" if scenario != "local_first" else "ollama:deepseek-coder-v2:33b",
            "standard": "claude-sonnet-4-6",
            "simple": "claude-haiku-4-5",
        },
        "cmo": {"any": "gemini-2.0-flash"},
        "coo": {"any": "ollama:llama3.2:3b" if local_available else "claude-haiku-4-5"},
        "cfo": {"any": "ollama:qwen2.5:7b" if local_available else "gemini-2.0-flash"},
        "cs": {"any": "claude-haiku-4-5"},
        "sales": {"any": "claude-haiku-4-5"},
        "editor": {"any": "gemini-2.0-flash"},
        "data": {"any": "ollama:qwen2.5:7b" if local_available else "gemini-2.0-flash"},
    }
    return routing.get(role, {"any": "gemini-2.0-flash"})


# Agent prompt templates keyed by role
AGENT_PROMPTS: dict[str, str] = {
    "cto": (
        "You are the CTO of {company_name}.\n"
        "Language: {lang}\n"
        "Focus: Architecture, code quality, security, performance.\n"
        "Never create code with placeholders or TODOs.\n"
        "Always write tests for new functionality.\n"
        "Apply Jidoka: stop immediately if touching schema/auth/billing."
    ),
    "cmo": (
        "You are the CMO of {company_name}.\n"
        "Language: {lang}\n"
        "Focus: Marketing copy, brand voice, campaigns, SEO.\n"
        "Every piece of content must have a clear CTA.\n"
        "Tone: professional but approachable.\n"
        "Always write in the language specified by the task."
    ),
    "coo": (
        "You are the COO of {company_name}.\n"
        "Language: {lang}\n"
        "Focus: Operations, workflows, infra setup, process optimization.\n"
        "Apply Toyota TPS: minimize waste, standardize processes.\n"
        "Every operation must be idempotent and have rollback plan."
    ),
    "cfo": (
        "You are the CFO of {company_name}.\n"
        "Language: {lang}\n"
        "Focus: Revenue tracking, cost analysis, MCU billing reconciliation.\n"
        "Never share financial data with external APIs.\n"
        "Always include margin calculations in reports."
    ),
    "cs": (
        "You are the Customer Success Manager of {company_name}.\n"
        "Language: {lang}\n"
        "Focus: Customer support, retention, satisfaction.\n"
        "Response tone: empathetic, solution-focused, fast.\n"
        "Escalate to CTO if issue is technical. Escalate to CFO if billing dispute."
    ),
    "sales": (
        "You are the Sales Agent of {company_name}.\n"
        "Language: {lang}\n"
        "Focus: Lead nurturing, upsell, conversion.\n"
        "Never make promises that can't be delivered.\n"
        "Personalize every outreach based on usage data."
    ),
    "editor": (
        "You are the Content Editor of {company_name}.\n"
        "Language: {lang}\n"
        "Focus: Long-form writing, documentation, blog posts, newsletters.\n"
        "Maintain consistent voice across all content.\n"
        "Minimum 300 words for blog posts, 150 words for newsletters."
    ),
    "data": (
        "You are the Data Analyst of {company_name}.\n"
        "Language: {lang}\n"
        "Focus: Metrics, reporting, business intelligence.\n"
        "Always cite data sources. Never fabricate numbers.\n"
        "Every report ends with 3 actionable recommendations.\n"
        "Run locally — do not send raw data to external APIs."
    ),
}

AGENT_ROLES = list(AGENT_PROMPTS.keys())

# Thresholds for output scrubbing
_SCRUB_MAX_RENDERED_BYTES = 2048  # 2 KB per rendered prompt
_SCRUB_JSON_KEY_THRESHOLD = 5  # warn when raw JSON has >5 keys at top level

# Regex patterns to detect leaked secrets in rendered prompt text
_SECRET_PATTERNS = [
    re.compile(r"\bapi[_\s-]?key\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\bauthorization\s*[:=]\s*bearer\s+\S+", re.IGNORECASE),
    re.compile(r"\bbearer\s+[a-zA-Z0-9_\-]{20,}\b"),
    re.compile(r"\bsk-[a-zA-Z0-9]{20,}\b"),
    re.compile(r"\b(?:password|passwd|pwd|secret|token)\s*[:=]\s*\S+", re.IGNORECASE),
]


def _get_llm_api_key() -> str | None:
    """Return the first available LLM API key from the environment.

    Checks ANTHROPIC_API_KEY first, then LLM_API_KEY.
    Returns None if neither is set.
    """
    return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("LLM_API_KEY")


def _get_llm_base_url() -> str:
    """Return LLM base URL from env, with a sensible default for Anthropic."""
    return os.environ.get("LLM_BASE_URL", "https://api.anthropic.com/v1")


def _get_llm_model() -> str:
    """Return the LLM model identifier from env, with a default."""
    return os.environ.get("LLM_MODEL", "claude-sonnet-4-6-20250514")


def scrub_secrets(rendered: str, context: str = "") -> None:
    """Raise ValueError if *rendered* appears to contain leaked secrets.

    Checks for API keys, bearer tokens, common credential patterns, and
    suspiciously dense JSON blocks.  Called before any rendered prompt is
    accepted.

    Args:
        rendered: The rendered prompt text to inspect.
        context: Optional caller label for error messages (e.g. role name).

    Raises:
        ValueError: With a description of the detected secret pattern.
    """
    label = f"[{context}] " if context else ""

    # Size guard
    if len(rendered.encode("utf-8")) > _SCRUB_MAX_RENDERED_BYTES:
        raise ValueError(
            f"{label}Rendered prompt exceeds {_SCRUB_MAX_RENDERED_BYTES} bytes "
            f"({len(rendered.encode('utf-8'))} bytes)"
        )

    # Secret pattern scan
    for pattern in _SECRET_PATTERNS:
        match = pattern.search(rendered)
        if match:
            # Redact the actual secret value in the error message
            secret_snippet = match.group(0)
            redacted = re.sub(r"\S{8,}", "***REDACTED***", secret_snippet)
            raise ValueError(
                f"{label}Possible secret leak detected — pattern: {pattern.pattern!r}. "
                f"Matched text: {redacted}"
            )

    # Markdown-fenced blocks that look like they contain secrets
    for fence in re.finditer(
        r"```(?:json|yaml|env|config|toml)?\s*\n(.*?)\n```", rendered, re.DOTALL
    ):
        body = fence.group(1)
        # Count look like key-value pairs
        kv_count = len(re.findall(r"^\s*[\w\-]+\s*[:=]", body, re.MULTILINE))
        if kv_count > _SCRUB_JSON_KEY_THRESHOLD:
            # Check for secret keywords inside the block
            if any(
                re.search(p, body, re.IGNORECASE)
                for p in [r"api[_\s-]?key", r"secret", r"token", r"password", r"sk-"]
            ):
                raise ValueError(
                    f"{label}Markdown fenced block appears to contain secrets "
                    f"({kv_count} key-value pairs)"
                )


def render_agent_prompts_llm(
    config: CompanyConfig,
    templates: dict[str, str],
    api_key: str,
) -> dict[str, str]:
    """Call an LLM to personalise agent prompts for a specific company context.

    For each of the 8 agent roles, sends a rendering request to the configured
    LLM endpoint.  The LLM receives the original template and must produce a
    personalised version that preserves the template's structural directives
    (focus areas, rules, escalation paths) while adapting language, tone, and
    examples to the company's product type, scenario, and primary language.

    Args:
        config: Validated CompanyConfig with company details.
        templates: Dict mapping role name to its template string (with
                   ``{company_name}`` and ``{lang}`` placeholders already
                   resolved, or still raw — the LLM handles both).
        api_key: API key for the LLM provider (Anthropic or compatible).

    Returns:
        Dict mapping role -> rendered prompt string.

    Raises:
        ValueError: If any rendered prompt exceeds the size limit or appears
                    to contain leaked secrets.
        RuntimeError: If the LLM call fails for a role (individual failures
                      are raised — caller decides on partial success).
    """
    import urllib.error
    import urllib.request

    base_url = _get_llm_base_url()
    model = _get_llm_model()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    rendered: dict[str, str] = {}

    for role in AGENT_ROLES:
        template = templates.get(role, "")
        render_prompt = (
            f"Personalize this agent system prompt for the company "
            f"'{config.company_name}' operating in the "
            f"{config.product_type} industry, using the "
            f"{config.scenario} deployment scenario, "
            f"for {config.primary_language} speakers.\n\n"
            f"Role: {role}\n\n"
            f"Template:\n---\n{template}\n---\n\n"
            f"Instructions:\n"
            f"1. Preserve ALL structural directives (focus areas, rules, "
            f"escalation paths, format requirements).\n"
            f"2. Adapt tone/examples to the company context above.\n"
            f"3. Stay under 2 KB total.\n"
            f"4. Output ONLY the prompt - no explanations, no markdown fences."
        )

        payload = json.dumps(
            {
                "model": model,
                "max_tokens": 1024,
                "temperature": 0.4,
                "messages": [{"role": "user", "content": render_prompt}],
            }
        ).encode("utf-8")

        url = f"{base_url}/chat/completions"
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"LLM rendering failed for role '{role}': HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise RuntimeError(
                f"LLM rendering failed for role '{role}': {exc}"
            ) from exc

        content = data["choices"][0]["message"]["content"]

        # Size guard
        if len(content.encode("utf-8")) > _SCRUB_MAX_RENDERED_BYTES:
            raise ValueError(
                f"[{role}] Rendered prompt exceeds {_SCRUB_MAX_RENDERED_BYTES} bytes "
                f"({len(content.encode('utf-8'))} bytes)"
            )

        # Secret scan
        for pattern in _SECRET_PATTERNS:
            if pattern.search(content):
                raise ValueError(
                    f"[{role}] Possible secret leak after LLM render: "
                    f"pattern {pattern.pattern!r} matched"
                )

        rendered[role] = content
        logger.debug("Rendered prompt for role '%s' (%d bytes)", role, len(content))

    return rendered


def validate_config(config: CompanyConfig) -> list[str]:
    """Validate wizard answers. Returns list of error messages."""
    errors: list[str] = []
    if not config.company_name or not config.company_name.strip():
        errors.append("company_name is required")
    if config.product_type not in ("saas", "digital", "api_service", "consulting"):
        errors.append(f"Invalid product_type: {config.product_type}")
    if config.scenario not in ("local_first", "hybrid", "api_only", "apple_silicon"):
        errors.append(f"Invalid scenario: {config.scenario}")
    if config.budget_tier not in ("zero", "minimal", "hybrid", "unlimited"):
        errors.append(f"Invalid budget_tier: {config.budget_tier}")
    if config.primary_language not in ("vi", "en", "both"):
        errors.append(f"Invalid primary_language: {config.primary_language}")
    return errors


def generate_config_files(
    config: CompanyConfig,
    base_dir: str | Path = ".",
    mcu_gate: MCUGate | None = None,
    llm_render: bool | None = None,
) -> dict[str, str]:
    """Generate all 12 config files from wizard answers.

    Args:
        config: Validated CompanyConfig from wizard.
        base_dir: Project root directory.
        mcu_gate: Optional MCUGate for seeding balance (uses file fallback if None).
        llm_render: Force LLM rendering.  True — always use LLM.  False — never use
                    LLM.  None (default) — auto-detect from environment
                    (ANTHROPIC_API_KEY or LLM_API_KEY).

    Returns:
        Dict mapping relative file paths to their content.

    Raises:
        ValueError: If LLM rendering produces oversized or secret-containing output.
        RuntimeError: If the LLM call fails while rendering agent prompts.
    """
    errors = validate_config(config)
    if errors:
        raise ValueError(f"Invalid config: {'; '.join(errors)}")

    # --- LLM vs static prompt resolution ---
    if llm_render is True:
        use_llm = True
    elif llm_render is False:
        use_llm = False
    else:
        # Auto-detect from environment
        use_llm = bool(_get_llm_api_key())

    now = datetime.now(timezone.utc).isoformat()
    files: dict[str, str] = {}

    # File 1: .mekong/company.json
    company_json = {
        "company_name": config.company_name,
        "product_type": config.product_type,
        "scenario": config.scenario,
        "budget_tier": config.budget_tier,
        "primary_language": config.primary_language,
        "created_at": now,
        "version": "1.0",
    }
    files[".mekong/company.json"] = json.dumps(company_json, indent=2, ensure_ascii=False)

    # File 2: .openclaw/config.json
    openclaw_config = {
        "routing_rules": {},
        "fallback_chain": {
            "claude-opus-4-6": ["claude-sonnet-4-6", "gemini-2.0-flash"],
            "claude-sonnet-4-6": ["claude-haiku-4-5", "gemini-2.0-flash"],
            "ollama:llama3.2:3b": ["claude-haiku-4-5"],
        },
        "cost_override": {"budget_tier": config.budget_tier},
    }
    # Build per-role routing
    for role in AGENT_ROLES:
        openclaw_config["routing_rules"][role] = _resolve_model(
            config.scenario, role, ""
        )
    files[".openclaw/config.json"] = json.dumps(openclaw_config, indent=2, ensure_ascii=False)

    # Files 3-10: .mekong/agents/{role}.md
    if use_llm:
        api_key = _get_llm_api_key()
        resolved_templates: dict[str, str] = {}
        # Pre-fill placeholders so the LLM sees the concrete values
        for role in AGENT_ROLES:
            resolved_templates[role] = AGENT_PROMPTS[role].format(
                company_name=config.company_name,
                lang=config.primary_language,
            )
        rendered = render_agent_prompts_llm(config, resolved_templates, api_key)
        for role in AGENT_ROLES:
            files[f".mekong/agents/{role}.md"] = rendered[role]
    else:
        # Static template path (zero behavior change when no API key is set)
        lang = config.primary_language
        for role in AGENT_ROLES:
            template = AGENT_PROMPTS[role]
            content = template.format(company_name=config.company_name, lang=lang)
            files[f".mekong/agents/{role}.md"] = content

    # File 11: company section for CLAUDE.md
    claude_section = (
        f"# {config.company_name} — AgencyOS Configuration\n\n"
        f"## Company\n"
        f"- Name: {config.company_name}\n"
        f"- Product: {config.product_type}\n"
        f"- Language: {config.primary_language}\n"
        f"- LLM Scenario: {config.scenario}\n\n"
        f"## Active Agents\n"
        f"CTO · CMO · COO · CFO · CS · Sales · Editor · Data\n\n"
        f"## Rules\n"
        f"- All tasks route through hybrid_router\n"
        f"- MCU must be deducted for every agent execution\n"
        f"- Memory auto-saved after every successful task\n"
        f"- Jidoka: stop on schema/auth/billing changes\n"
    )
    files[".mekong/claude_company_section.md"] = claude_section

    # File 12: .mekong/mcu_balance.json
    mcu_balance = {
        "balance": TIER_MCU_SEED["starter"],
        "locked": 0,
        "lifetime_used": 0,
        "tier": "starter",
        "last_updated": now,
    }
    files[".mekong/mcu_balance.json"] = json.dumps(mcu_balance, indent=2)

    return files


def write_config_files(
    files: dict[str, str], base_dir: str | Path = "."
) -> list[str]:
    """Write generated config files to disk.

    Returns list of written file paths.
    """
    base = Path(base_dir)
    written: list[str] = []

    for rel_path, content in files.items():
        full_path = base / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        written.append(str(rel_path))
        logger.info("Written: %s", rel_path)

    return written


def seed_mcu_balance(
    tenant_id: str,
    tier: str = "starter",
    mcu_gate: MCUGate | None = None,
) -> int:
    """Seed initial MCU balance for a new tenant.

    Returns the amount seeded.
    """
    amount = TIER_MCU_SEED.get(tier, 100)

    if mcu_gate:
        mcu_gate.seed_balance(tenant_id, amount, reason=f"company_init_{tier}")

    return amount


def init_company(
    config: CompanyConfig,
    base_dir: str | Path = ".",
    mcu_gate: MCUGate | None = None,
    tenant_id: str = "default",
) -> dict:
    """Full init pipeline: validate -> generate -> write -> seed MCU.

    Returns summary dict with all created files and MCU status.
    """
    # Check if already initialized
    base = Path(base_dir)
    company_file = base / ".mekong" / "company.json"
    if company_file.exists():
        existing = json.loads(company_file.read_text(encoding="utf-8"))
        raise FileExistsError(
            f"Company already setup: {existing.get('company_name', 'unknown')}. "
            f"Use --reset to reconfigure."
        )

    # Generate and write
    files = generate_config_files(config, base_dir, mcu_gate)
    written = write_config_files(files, base_dir)

    # Seed MCU
    mcu_seeded = seed_mcu_balance(tenant_id, "starter", mcu_gate)

    cost_est = COST_ESTIMATES.get(config.scenario, "unknown")

    return {
        "company_name": config.company_name,
        "scenario": config.scenario,
        "budget_tier": config.budget_tier,
        "primary_language": config.primary_language,
        "files_created": len(written),
        "files": written,
        "mcu_seeded": mcu_seeded,
        "cost_estimate": cost_est,
    }
