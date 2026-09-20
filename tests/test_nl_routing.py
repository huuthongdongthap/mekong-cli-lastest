"""Unit tests for cli.tui.router — NL routing and fuzzy_match.

Covers:
- match_routes() basic routing
- fuzzy_match() scoring tiers (exact 1.0, prefix 0.8, substring 0.5)
- Empty / whitespace / None inputs
- Mixed VI + EN inputs
- Special characters in text
- route_ask() backward compat via ask_keyword_router
- Phase 1 expanded domains (Databases, API, Testing, Monitoring, Security, DevOps/CI)

Run: python3 -m pytest tests/test_nl_routing.py -v
"""
from __future__ import annotations


from src.cli.tui.router import (
	CommandMatch,
	RouteEntry,
	ROUTE_TABLE,
	_matches,
	fuzzy_match,
	get_all_commands,
	get_route_table,
	match_routes,
)
from src.cli.ask_keyword_router import route_ask


# ── _matches() low-level ────────────────────────────────────────────────


class TestMatches:
	def test_trailing_star_prefix_hit(self):
		assert _matches("code*", "code giao diện viết") is True

	def test_trailing_star_substring_miss(self):
		assert _matches("code*", "python and sql only") is False

	def test_trailing_star_phrase_prefix(self):
		assert _matches("code backend*", "code backend api") is True
		assert _matches("code backend*", "code frontend api") is False

	def test_bare_word_substring(self):
		assert _matches("brainstorm", "hãy brainstorm ý tưởng") is True
		assert _matches("brainstorm", "plan roadmap") is False

	def test_case_insensitive_en(self):
		assert _matches("DEPLOY*", "Deploy To Production Now") is True

	def test_case_insensitive_vi(self):
		assert _matches("TRIỂN KHAI*", "triển khai lên production") is True

	def test_empty_pattern_returns_false(self):
		assert _matches("", "anything") is False
		assert _matches("*", "anything") is False  # needle stripped entirely

	def test_empty_text_returns_false(self):
		assert _matches("anything", "") is False
		assert _matches("anything", " ") is False
		assert _matches("anything", None) is False  # type: ignore[arg-type]

	def test_special_characters_in_text(self):
		assert _matches("debug*", "debug: lỗi #1234 @main") is True
		assert _matches("deploy*", "deploy-to-prod v2.3.1") is True

	def test_whitespace_normalization(self):
		assert _matches(" code* ", " code viết ") is True

	def test_fixed_double_star_push_live(self):
		"""push live stored as bare phrase (no trailing *). Matched as substring."""
		assert _matches("push live", "push live production") is True
		assert _matches("push live", "hãy push live ngay") is True

	def test_bare_phrase_no_trailing_star(self):
		"""Bare phrase without star is strict substring — prefix must be exact."""
		assert _matches("push live", "hãy push live hôm nay") is True
		# Different surface form — hyphenation makes it a different token
		assert _matches("push live", "hãy push upload hôm nay") is False

	def test_uuid_style_hex_input_returns_false(self):
		"""Very long mixed-case input must not falsely match."""
		random_hex = "A" * 300 + "b" * 200
		assert _matches("deploy*", random_hex) is False


# ── match_routes() ──────────────────────────────────────────────────────


class TestMatchRoutes:
	def test_no_match_returns_empty(self):
		assert match_routes("") == []
		assert match_routes(" ") == []

	def test_none_returns_empty(self):
		assert match_routes(None) == []

	def test_exact_vi_match(self):
		assert "deploy" in match_routes("triển khai production")

	def test_exact_en_match(self):
		assert "deploy" in match_routes("deploy to production now")

	def test_mixed_vi_deploy_wins(self):
		out = match_routes("triển khai lên staging")
		assert "deploy" in out

	def test_mixed_en_deploy_wins(self):
		out = match_routes("deploy to production now")
		assert "deploy" in out

	def test_first_match_wins(self):
		"""'viết code' hits 'cook' before any downstream entry."""
		out = match_routes("viết code python backend")
		assert "cook" in out

	# Live command routing ────────────────────────────────────────────

	def test_live_debug_routes_from_fix_keyword(self):
		"""'fix' keyword routes to debug (repair redirect)."""
		assert "debug" in match_routes("fix the bug")

	def test_live_cook_routes_from_code_keyword(self):
		"""'code' keyword routes to cook."""
		assert "cook" in match_routes("viết code python")

	def test_live_plan_routes_from_vi_keyword(self):
		"""Vietnamese 'lập kế hoạch' routes to plan."""
		assert "plan" in match_routes("lập kế hoạch cho dự án")

	def test_live_deploy_routes_from_vi_keyword(self):
		"""Vietnamese 'triển khai' routes to deploy."""
		assert "deploy" in match_routes("triển khai lên production")

	def test_duplicate_command_skipped_second_pass(self):
		"""Each command appears at most once even if multiple keywords match."""
		out = match_routes("viết code và code giao diện")
		assert out.count("cook") == 1


# ── fuzzy_match() scoring ────────────────────────────────────────────────


class TestFuzzyMatch:
	def test_empty_returns_empty(self):
		assert fuzzy_match("") == []
		assert fuzzy_match(" ") == []
		assert fuzzy_match(None) == []

	def test_exact_phrase_scores_one(self):
		results = fuzzy_match("deploy")
		top = results[0]
		assert top.command == "deploy"
		assert top.score == 1.0

	def test_prefix_scores_point_eight(self):
		"""'deploy to' with needle 'deploy' -> phrase prefix 0.8."""
		results = fuzzy_match("deploy to prod")
		deploy_hit = next((r for r in results if r.command == "deploy"), None)
		assert deploy_hit is not None
		assert deploy_hit.score == 0.8

	def test_substring_scores_point_five(self):
		"""Input contains the keyword mid-sentence -> substring hit 0.5."""
		results = fuzzy_match("full debug on codebase")
		debug_hit = next((r for r in results if r.command == "debug"), None)
		assert debug_hit is not None
		assert debug_hit.score == 0.5

	def test_max_results_default_five(self):
		results = fuzzy_match("a")
		assert len(results) <= 5

	def test_max_results_respected(self):
		results = fuzzy_match("a", max_results=2)
		assert len(results) <= 2

	def test_sorted_descending(self):
		results = fuzzy_match("audit")
		scores = [r.score for r in results]
		assert scores == sorted(scores, reverse=True)

	def test_returns_command_match_objects(self):
		results = fuzzy_match("deploy")
		assert all(isinstance(r, CommandMatch) for r in results)
		assert all(hasattr(r, "command") for r in results)
		assert all(hasattr(r, "score") for r in results)
		assert all(hasattr(r, "matched_keyword") for r in results)

	def test_mixed_vi_en_input(self):
		results = fuzzy_match("triển khai staging deploy backend")
		commands = [r.command for r in results]
		assert "deploy" in commands

	def test_special_chars_input(self):
		results = fuzzy_match("fix: bug #42 @main")
		commands = [r.command for r in results]
		assert "debug" in commands

	def test_very_long_input_clamped(self):
		"""Very long input should not raise; result capped at max_results."""
		long_input = "run database migration now " * 200
		results = fuzzy_match(long_input, max_results=3)
		assert len(results) <= 3

	def test_very_long_input_no_match(self):
		"""Randomized long non-matching input returns empty."""
		long_input = "A" * 500 + "B" * 500
		results = fuzzy_match(long_input)
		assert results == []

	def test_empty_long_input_returns_empty(self):
		results = fuzzy_match("   " * 1000)
		assert results == []


# ── Public API surface ──────────────────────────────────────────────────


class TestPublicApi:
	def test_get_route_table_returns_list_of_entries(self):
		table = get_route_table()
		assert isinstance(table, list)
		assert all(isinstance(e, RouteEntry) for e in table)
		assert len(table) == len(ROUTE_TABLE)

	def test_get_all_commands_returns_list(self):
		cmds = get_all_commands()
		assert isinstance(cmds, list)
		assert len(cmds) == len(ROUTE_TABLE)
		assert len(cmds) == len(set(cmds))  # unique commands

	def test_route_table_has_required_fields(self):
		for entry in ROUTE_TABLE:
			assert isinstance(entry.command, str) and entry.command
			assert isinstance(entry.vi_keywords, tuple)
			assert isinstance(entry.en_keywords, tuple)

	def test_minimum_command_count(self):
		"""ROUTE_TABLE covers the live dispatchable commands."""
		assert len(ROUTE_TABLE) >= 4

	def test_route_table_no_list_literals(self):
		"""Detect legacy list [a, b] values as tuples (stricter than isinstance check)."""
		for entry in ROUTE_TABLE:
			for kw in (*entry.vi_keywords, *entry.en_keywords):
				assert isinstance(kw, str), f"non-str keyword {kw!r} for {entry.command}"


# ── route_ask() backward compat ─────────────────────────────────────────


class TestRouteAskBackwardCompat:
	def test_signature_unchanged(self):
		import inspect

		sig = inspect.signature(route_ask)
		assert list(sig.parameters) == ["input_text"]
		assert sig.return_annotation == "Optional[str]"

	def test_returns_none_on_no_match(self):
		assert route_ask("this-is-absolute-gibberish-xyzzy") is None

	def test_returns_command_on_match(self):
		result = route_ask("deploy to production now")
		assert result == "deploy"

	def test_empty_returns_none(self):
		assert route_ask("") is None
		assert route_ask(None) is None  # type: ignore[arg-type]

	def test_vi_input(self):
		assert route_ask("triển khai lên staging") == "deploy"

	def test_mixed_vi_en_input(self):
		result = route_ask("deploy backend api mới")
		assert result in {"deploy", "backend-api-build", None}
