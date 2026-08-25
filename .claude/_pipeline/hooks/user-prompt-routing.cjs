#!/usr/bin/env node
/**
 * UserPromptSubmit hook — analyzes prompts with model router
 * and injects routing decisions (Flash vs Pro) into prompt context.
 *
 * Fires: Before each user prompt is submitted
 * Purpose: Run model router on every prompt, inject tier recommendation
 * KV Cache-safe: Output goes to dynamic suffix (via additionalContext),
 *               not static prefix.
 *
 * Exit Codes:
 *   0 - Always (fail-open, non-blocking)
 */
'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const modelRouter = require('./lib/model-router.cjs');
const { isHookEnabled } = require('./lib/ck-config-utils.cjs');
const { getFailureCount } = require('./lib/flash-failure-store.cjs');
const usageTracker = require('./lib/usage-cost-tracker.cjs');

if (!isHookEnabled('user-prompt-routing')) {
  process.exit(0);
}

const ROUTING_LOG = path.join(os.tmpdir(), modelRouter.ROUTING_LOG_FILENAME);

/**
 * Persist routing decision to temp log (JSON Lines format, append-only).
 * Atomic append avoids race conditions from concurrent hook invocations.
 *
 * @param {Object} decision - Routing decision from shouldEscalate()
 */
function persistRoutingDecision(decision) {
  try {
    const entry = JSON.stringify({
      timestamp: Date.now(),
      tier: decision.tier,
      score: decision.score,
      source: decision.source,
      signals: decision.signals.map(s => s.label),
      reason: decision.reason
    }) + '\n';

    fs.appendFileSync(ROUTING_LOG, entry, 'utf8');
  } catch { /* best-effort */ }
}

/**
 * Build the routing context section to inject into the prompt.
 *
 * @param {Object} decision - Routing decision
 * @param {Object|null} modelSuggestion - Suggested model from suggestModel()
 * @returns {string} Markdown section
 */
function buildRoutingContext(decision, modelSuggestion) {
  const tierEmoji = decision.tier === 'pro' ? '🏗️' : '⚡';
  const tierName = decision.tier === 'pro' ? 'Pro (Architect)' : 'Flash (Executor)';
  const role = decision.tier === 'pro' ? 'architect' : 'executor';

  const lines = [
    '',
    `## Model Routing`,
    `- Assigned: ${tierEmoji} ${tierName}`,
    `- Role: ${role}`,
    `- Complexity: ${decision.score}${decision.signals.length > 0 ? ` (${decision.signals.map(s => s.label).join(', ')})` : ''}`,
    `- Strategy: ${decision.tier === 'pro' ? 'Pro handles architecture/design' : 'Flash handles execution'}`,
  ];

  // Inject China model suggestion when applicable
  if (modelSuggestion) {
    lines.push('');
    lines.push(`### 🧠 Alternative Model Suggestion`);
    lines.push(`- **Recommended:** \`${modelSuggestion.model}\` (${modelSuggestion.label})`);
    lines.push(`- **Why:** ${modelSuggestion.reason} (score: ${modelSuggestion.score})`);
    lines.push(`- **How:** Use \`/model ${modelSuggestion.model}\` to switch for this task`);
    lines.push(`- **Note:** Default Opus remains active. Use suggestion only for specialized tasks.`);
  }

  // Inject session cost summary if available (fail-open)
  try {
    const sessionId = process.env.CK_SESSION_ID || '';
    if (sessionId) {
      const costSummary = usageTracker.formatCostSummary(sessionId);
      if (costSummary) {
        lines.push(`- ${costSummary}`);
      }
    }
  } catch { /* cost tracking is best-effort */ }

  lines.push('');
  return lines.join('\n');
}

function main() {
  const stdin = fs.readFileSync(0, 'utf-8').trim();
  if (!stdin) { console.log(JSON.stringify({ continue: true })); process.exit(0); }

  const payload = JSON.parse(stdin);

  // Only process UserPromptSubmit events — other events (Stop, SubagentStop, etc.)
  // get wrong-schema JSON if we emit hookSpecificOutput for them.
  const eventName = payload.hook_event_name || '';
  if (eventName !== 'UserPromptSubmit') {
    console.log(JSON.stringify({ continue: true }));
    process.exit(0);
  }

  const prompt = String(payload.prompt || payload.user_prompt || '').trim();
  if (!prompt) { console.log(JSON.stringify({ continue: true })); process.exit(0); }

  // Run model router on the prompt — check failure store for cross-process history
  // Two-key lookup strategy:
  //   Primary: prompt text (first 80 chars) — matches the exact user task
  //   Fallback: CK_SESSION_ID — catches failures recorded by session-state.cjs
  //             which always writes under session_id, not prompt text.
  //             This ensures a subagent failure in the current session is
  //             detected on the next user prompt even when the prompt differs.
  const flashRetries = getFailureCount(prompt) || getFailureCount(process.env.CK_SESSION_ID || '');
  const decision = modelRouter.shouldEscalate(prompt, {
    flashRetries,
    hasCompilationErrors: false,
    hasTestFailures: false,
    fileCount: 0,
    flashConfidence: 100
  });

  // Log for metrics
  persistRoutingDecision(decision);

  // Check for China model suggestion (fallback only — when Opus fails)
  const modelSuggestion = modelRouter.suggestModel(prompt, {
    flashRetries,
    source: decision.source,
  });

  // Build and emit routing context
  const additionalContext = buildRoutingContext(decision, modelSuggestion);

  const output = {
    hookSpecificOutput: {
      hookEventName: 'UserPromptSubmit',
      additionalContext
    }
  };

  console.log(JSON.stringify(output));
  process.exit(0);
}

try { main(); } catch { process.exit(0); }
