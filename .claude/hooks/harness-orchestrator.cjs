#!/usr/bin/env node
/**
 * Harness Orchestrator Hook
 *
 * Fires: SubagentStop
 * Purpose: Advance default-code-harness finite state machine.
 * Contract: fail-open, never block, never prompt.
 *
 * Flow (fixed order, no branching):
 *   advise -> plan -> cook -> review
 *
 * Guard:
 * - Block /ak:bootstrap from advise phase.
 */
const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const STATE_PATH = path.join(REPO_ROOT, '.mekong', '.harness-state.json');
const ORDER = ['advise', 'plan', 'cook', 'review'];
const BLOCKED_COMMANDS_IN_ADVISE = ['/ak:bootstrap'];

function readState() {
  try {
    if (!fs.existsSync(STATE_PATH)) return null;
    const raw = fs.readFileSync(STATE_PATH, 'utf8').trim();
    if (!raw) return null;
    return JSON.parse(raw);
  } catch (_) {
    return null;
  }
}

function writeState(state) {
  state.updated_at = new Date().toISOString();
  fs.writeFileSync(STATE_PATH, JSON.stringify(state, null, 2));
}

function mark(state, phase, status, extra = {}) {
  const current = state.phases[phase] || {};
  state.phases[phase] = { ...current, status, ...extra };
  state.current_phase = phase;
  state.status = status;
}

function parseStdin() {
  const raw = fs.readFileSync(0, 'utf-8').trim();
  if (!raw) return {};
  try { return JSON.parse(raw); } catch (_) { return {}; }
}

function containsBlockedCommand(input) {
  if (!input || typeof input !== 'string') return false;
  return BLOCKED_COMMANDS_IN_ADVISE.some(cmd => input.includes(cmd));
}

function bootstrapStartedAt(state) {
  const record = state.phases && state.phases[state.current_phase];
  if (!record) return;
  if (record.status === 'running' && !record.phase_started_at) {
    record.phase_started_at = new Date().toISOString();
  }
}

function advance(state) {
  const current = state.current_phase || 'advise';
  const idx = ORDER.indexOf(current);
  if (idx < 0) return;

  const now = new Date().toISOString();
  mark(state, current, 'completed', {
    phase_completed_at: now,
    output: state.phases[current] ? (state.phases[current].output || null) : null,
  });

  const next = ORDER[idx + 1] || null;
  if (!next) return;
  mark(state, next, 'running', { phase_started_at: now });
}

function main() {
  try {
    const payload = parseStdin();
    const state = readState();
    if (!state || !state.phases) process.exit(0);

    bootstrapStartedAt(state);

    if (state.current_phase === 'advise' && containsBlockedCommand(payload.command || payload.input || '')) {
      console.log('Harness guard: /ak:bootstrap is blocked during advise phase.');
      process.exit(0);
    }

    advance(state);
    writeState(state);
  } catch (_) {
    process.exit(0);
  }
}

main();
