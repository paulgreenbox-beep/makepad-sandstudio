import { createHash } from 'node:crypto';

export const REPOSITORY = 'paulgreenbox-beep/makepad-sandstudio';
export const ACTION_SHA = 'c05cfd74ad95c626cdf05c6685e62becc3bf7813';
export const CODEX_VERSION = '0.166.0';
export const digest = value => createHash('sha256').update(value).digest('hex');
export class Blocked extends Error {
  constructor(code) { super(code); this.code = code; }
}
const demand = (condition, code) => { if (!condition) throw new Blocked(code); };
export function authorize(event, context, permission, policy) {
  demand(event.action === 'labeled' && event.label?.name === 'codex-ready', 'WRONG_EVENT');
  demand(context.repository === REPOSITORY && event.repository?.full_name === REPOSITORY, 'WRONG_REPOSITORY');
  demand(!event.issue?.pull_request && event.issue?.state === 'open' && Number.isSafeInteger(event.issue.number), 'NOT_OPEN_ISSUE');
  demand(context.attempt === '1', 'REPLAY_DENIED');
  demand(event.sender?.type === 'User' && policy.authorized_user_ids.includes(event.sender.id), 'UNAUTHORIZED_SENDER');
  demand(event.sender.login === context.actor && context.actor === context.triggeringActor, 'ACTOR_MISMATCH');
  demand(['admin', 'maintain'].includes(permission), 'INSUFFICIENT_PERMISSION');
}
export function goalId(body) {
  demand(typeof body === 'string' && Buffer.byteLength(body) <= 32768, 'INVALID_ISSUE_BODY');
  const matches = [...body.matchAll(/^MSS-GOAL: (MSS-\d{3})\s*$/gm)];
  demand(matches.length === 1, 'GOAL_REFERENCE_REQUIRED');
  return matches[0][1];
}
export function validateGoal(goal, manifest, catalog, sklt, dependencies, policy) {
  demand(manifest.schema === 'mss-goal-index-v1' && catalog.schema === 'mss-check-catalog-v1', 'INVALID_REGISTRY');
  demand(goal?.schema === 'mss-goal-v1' && /^MSS-\d{3}$/.test(goal.id), 'INVALID_GOAL');
  demand(manifest.goals.filter(x => x.id === goal.id && x.path === `goals/${goal.id}.json`).length === 1, 'UNINDEXED_GOAL');
  demand(goal.status === 'TODO' && goal.branch === null && goal.pr_url === null, 'GOAL_ALREADY_OWNED');
  demand(Array.isArray(goal.module_ids) && goal.module_ids.length > 0 && goal.module_ids.every(x => sklt.includes(x)), 'INVALID_SKLT_BINDING');
  demand(Array.isArray(goal.acceptance) && goal.acceptance.length > 0 && goal.acceptance.every(x => typeof x === 'string' && x.length > 0), 'INVALID_ACCEPTANCE');
  demand(Array.isArray(goal.dependencies) && goal.dependencies.every(id => dependencies[id]?.status === 'VERIFIED'), 'UNSATISFIED_DEPENDENCY');
  const scope = policy.scopes?.[goal.id];
  demand(scope && Array.isArray(scope.paths) && scope.paths.length > 0 && Array.isArray(scope.checks), 'NO_REVIEWED_SCOPE');
  for (const p of scope.paths) validatePath(p.replace(/\/$/, '') + '/scope.txt');
  demand(scope.paths.every(p => /^[A-Za-z0-9_/-]+\/$/.test(p) && !p.includes('//')), 'INVALID_SCOPE');
  demand(Array.isArray(goal.required_checks) && goal.required_checks.length > 0, 'NO_REQUIRED_CHECKS');
  const ids = goal.required_checks.map(x => x.id);
  demand(ids.every(id => typeof id === 'string' && /^[A-Z][A-Z0-9_]{0,63}$/.test(id)), 'INVALID_CHECK_ID');
  demand(new Set(ids).size === ids.length && ids.every(id => scope.checks.includes(id)), 'CHECK_SCOPE_MISMATCH');
  const checks = ids.map(id => catalog.checks.find(x => x.id === id));
  demand(checks.every(x => x && Array.isArray(x.command) && x.command.length && x.command.every(a => typeof a === 'string')), 'MANUAL_CHECK_REQUIRED');
  demand(checks.every(x => policy.allowed_commands.some(c => JSON.stringify(c) === JSON.stringify(x.command))), 'UNAPPROVED_CHECK_COMMAND');
  return { scope, checks };
}
export function ready(policy, { keyPresent, runners, inventoryAvailable }) {
  demand(policy.enabled === true, 'DISABLED_BY_POLICY');
  demand(keyPresent === true, 'MISSING_OPENAI_API_KEY');
  demand(inventoryAvailable === true, 'RUNNER_INVENTORY_UNAVAILABLE');
  demand(Number.isSafeInteger(policy.worker_runner_id) && typeof policy.worker_name === 'string' && policy.worker_name.length > 0, 'RUNNER_NOT_CONFIGURED');
  const runner = runners.find(x => x.id === policy.worker_runner_id);
  demand(runner && runner.name === policy.worker_name && runner.os === 'windows' && runner.status === 'online' && !runner.busy && policy.worker_labels.every(l => runner.labels.some(x => x.name === l)), 'MISSING_TRUSTED_WORKER');
  const isolation = policy.isolation;
  demand(isolation?.approved === true && typeof isolation.evidence_ref === 'string' && isolation.evidence_ref.length > 0, 'NATIVE_ISOLATION_NOT_VERIFIED');
  demand(['config_sha256', 'requirements_sha256', 'broker_sha256'].every(k => /^[a-f0-9]{64}$/.test(isolation[k] ?? '')), 'MISSING_HOST_PINS');
}
export function validatePath(path) {
  demand(typeof path === 'string' && path.length <= 240 && /^[A-Za-z0-9_./-]+$/.test(path), 'UNSAFE_PATH');
  demand(!path.startsWith('/') && !path.includes('//') && !path.split('/').some(p => !p || p === '.' || p === '..' || /[. ]$/.test(p) || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(p)), 'UNSAFE_PATH');
  demand(!/^(?:\.git(?:hub)?|\.codex|goals|scripts\/codex-issue)(?:\/|$)/i.test(path) && !/^(?:AGENTS|SECURITY)\.md$/i.test(path) && !/\.(?:sklt|glif|glyf)(?:\.|$)/i.test(path), 'PROTECTED_PATH');
}
export function validateChanges(files, scope) {
  demand(files.length > 0 && files.length <= 64, 'EMPTY_OR_OVERSIZED_CHANGE');
  const seen = new Set(); let bytes = 0;
  for (const f of files) {
    validatePath(f.path);
    demand(!seen.has(f.path.toLowerCase()), 'CASE_COLLISION'); seen.add(f.path.toLowerCase());
    demand(scope.paths.some(p => f.path.startsWith(p)), 'OUT_OF_SCOPE');
    demand(f.mode === '100644' && typeof f.bytes === 'number' && f.bytes <= 1048576 && f.bytes >= 0, 'UNSAFE_FILE_MODE_OR_SIZE');
    bytes += f.bytes;
  }
  demand(bytes <= 8388608, 'CHANGE_TOO_LARGE');
}
export function checkReceipts(receipts, checks, source, binding) {
  demand(/^[a-f0-9]{40}$/.test(source), 'INVALID_SOURCE_SHA');
  demand(binding && /^MSS-\d{3}$/.test(binding.goal) && /^\d+$/.test(binding.attempt), 'INVALID_RECEIPT_BINDING');
  demand(Array.isArray(receipts) && receipts.length === checks.length, 'MISSING_RECEIPTS');
  return checks.map(check => {
    const matches = receipts.filter(r => r.check_id === check.id);
    demand(matches.length === 1, 'DUPLICATE_OR_MISSING_RECEIPT');
    const r = matches[0];
    demand(r.schema === 'mss-check-receipt-v1' && r.goal_id === binding.goal && r.attempt === binding.attempt && r.source_commit === source && typeof r.runner === 'string' && r.runner.length > 0 && Number.isFinite(Date.parse(r.started_at)) && Number.isFinite(Date.parse(r.ended_at)) && Date.parse(r.ended_at) >= Date.parse(r.started_at), 'INVALID_RECEIPT');
    demand(JSON.stringify(r.command) === JSON.stringify(check.command) && ['PASS','FAIL','BLOCKED','UNKNOWN','NOT_RUN'].includes(r.result), 'INVALID_CHECK_RESULT');
    demand(r.result !== 'PASS' || (r.exit_code === 0 && Array.isArray(r.evidence) && r.evidence.length > 0 && r.evidence.every(x => /^[a-f0-9]{64}$/.test(x.sha256 ?? '') && x.ref === `sha256:${x.sha256}`)), 'UNPROVEN_PASS');
    demand(r.result !== 'PASS' || !check.requires?.includes('test_summary') || (r.test_summary && Number.isInteger(r.test_summary.passed) && r.test_summary.passed >= 0 && r.test_summary.failed === 0 && r.test_summary.skipped === 0), 'MISSING_TEST_SUMMARY');
    return r;
  });
}
export function transition(goal, next, { source, branch, pr = null, receipts = [] }) {
  demand((goal.status === 'TODO' && next === 'IN_PROGRESS') || (goal.status === 'IN_PROGRESS' && ['IN_REVIEW','BLOCKED'].includes(next)), 'ILLEGAL_TRANSITION');
  demand(/^[a-f0-9]{40}$/.test(source) && /^codex\/issue-[1-9]\d*$/.test(branch), 'INVALID_TRANSITION_BINDING');
  demand(next !== 'IN_REVIEW' || (typeof pr === 'string' && /^https:\/\/github\.com\/paulgreenbox-beep\/makepad-sandstudio\/pull\/[1-9]\d*$/.test(pr)), 'MISSING_DRAFT_PR');
  demand(next !== 'IN_REVIEW' || (receipts.length === goal.required_checks.length && goal.required_checks.every(c => receipts.filter(r => r.check_id === c.id && r.goal_id === goal.id && r.source_commit === source && r.result === 'PASS' && typeof r.evidence_ref === 'string' && r.evidence_ref.startsWith('goals/events/')).length === 1)), 'UNVERIFIED_CHECKS');
  return { ...goal, status: next, source_commit: source, branch, pr_url: pr, owner_agent: 'codex-issue-worker', required_checks: goal.required_checks.map(c => ({ ...c, status: receipts.find(r => r.check_id === c.id)?.result ?? 'NOT_RUN', evidence_ref: receipts.find(r => r.check_id === c.id)?.evidence_ref ?? null })) };
}
