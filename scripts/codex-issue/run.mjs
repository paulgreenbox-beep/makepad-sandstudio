// Trusted controller code. Never load this script from the agent's working tree.
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { REPOSITORY, Blocked, authorize, goalId, validateGoal, ready, validatePath, validateChanges, checkReceipts, transition, digest } from './policy.mjs';

const trusted = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const out = path.resolve(process.env.MSS_OUT ?? path.join(trusted, '.mss-dispatch'));
const work = path.resolve(process.env.MSS_WORK ?? path.join(trusted, '..', 'work'));
const read = p => JSON.parse(fs.readFileSync(p, 'utf8'));
const local = p => read(path.join(trusted, p));
const policy = local('.github/codex-issue-policy.json');
const runId = process.env.GITHUB_RUN_ID;
const issueNumber = Number(process.env.MSS_ISSUE_NUMBER);
const sha = x => /^[0-9a-f]{40}$/.test(x ?? '');
const demand = (c, m) => { if (!c) throw new Blocked(m); };
const save = (name, value) => { fs.mkdirSync(out, { recursive: true }); fs.writeFileSync(path.join(out, name), JSON.stringify(value, null, 2) + '\n'); };
const output = (key, value) => {
  demand(/^[a-z_]+$/.test(key) && /^[A-Za-z0-9_./-]*$/.test(String(value)), 'INVALID_OUTPUT');
  if (process.env.GITHUB_OUTPUT) fs.appendFileSync(process.env.GITHUB_OUTPUT, `${key}=${value}\n`);
};
function git(cwd, args, extraEnv = {}) {
  const r = spawnSync('git', ['-c','core.hooksPath=NUL','-c','core.fsmonitor=false', ...args], { cwd, shell: false, encoding: 'utf8', maxBuffer: 24 * 1024 * 1024, env: { ...process.env, ...extraEnv } });
  if (r.status !== 0) throw new Blocked('GIT_FAILED_NO_AUTOMATIC_RETRY');
  return r.stdout.trimEnd();
}
async function api(endpoint, method = 'GET', body, token = process.env.GH_TOKEN, missing = false) {
  demand(typeof token === 'string' && token.length > 0, 'MISSING_CONTROLLER_TOKEN');
  const mutation = method !== 'GET';
  let response;
  try {
    response = await fetch(`https://api.github.com/repos/${REPOSITORY}/${endpoint}`, { method, headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(30000) });
  } catch { throw new Blocked(mutation ? 'OUTCOME_UNKNOWN_NO_AUTOMATIC_RETRY' : 'GITHUB_READ_FAILED'); }
  if (!mutation && missing && response.status===404) return null;
  if (!response.ok) throw new Blocked(mutation && response.status >= 500 ? 'OUTCOME_UNKNOWN_NO_AUTOMATIC_RETRY' : `GITHUB_${mutation ? 'WRITE' : 'READ'}_REJECTED`);
  if (response.status === 204) return null;
  try { return await response.json(); }
  catch { throw new Blocked(mutation ? 'OUTCOME_UNKNOWN_NO_AUTOMATIC_RETRY' : 'GITHUB_READ_FAILED'); }
}
async function metadataCommit(parent, changes, message) {
  demand(sha(parent), 'INVALID_PARENT');
  const commit = await api(`git/commits/${parent}`);
  const tree = await api('git/trees', 'POST', { base_tree: commit.tree.sha, tree: changes.map(x => ({ path: x.path, mode: '100644', type: 'blob', content: JSON.stringify(x.value, null, 2) + '\n' })) });
  return api('git/commits', 'POST', { message, tree: tree.sha, parents: [parent] });
}
async function advance(branch, expected, next) {
  demand(/^codex\/issue-[1-9]\d*$/.test(branch), 'INVALID_BRANCH');
  const ref = await api(`git/ref/heads/${branch}`);
  demand(ref.object.sha === expected, 'BRANCH_MOVED');
  // No force, retry, or fallback to main.
  await api(`git/refs/heads/${branch}`, 'PATCH', { sha: next, force: false });
}
async function comment(number, status, reason, pr = '') {
  demand(Number.isSafeInteger(number) && /^[A-Z_]+$/.test(reason), 'INVALID_REPORT');
  await api(`issues/${number}/comments`, 'POST', { body: `MSS Codex: **${status}** (${reason}).${pr ? ` Draft PR: ${pr}.` : ''}\nRun: https://github.com/${REPOSITORY}/actions/runs/${runId}\nNo automatic retry, merge or VERIFIED transition.` });
}
function skltIds() {
  return fs.readdirSync(trusted).filter(p => /^MSS_/.test(p)).flatMap(dir => fs.readdirSync(path.join(trusted, dir)).filter(p => p.endsWith('.sklt')).map(p => fs.readFileSync(path.join(trusted, dir, p), 'utf8').match(/^\s*object_id:\s*(\S+)/m)?.[1])).filter(Boolean);
}
function dependenciesFor(goal) {
  demand(Array.isArray(goal.dependencies) && goal.dependencies.every(id=>/^MSS-\d{3}$/.test(id)),'INVALID_DEPENDENCY_ID');
  return Object.fromEntries(goal.dependencies.map(id=>[id,local(`goals/${id}.json`)]));
}
async function prepare() {
  const event = read(process.env.GITHUB_EVENT_PATH);
  let authorized = false;
  try {
    demand(process.env.GITHUB_EVENT_NAME === 'issues', 'WRONG_EVENT');
    // Do the cheap sender checks before querying permissions or runner inventory.
    demand(event.sender?.type === 'User' && policy.authorized_user_ids.includes(event.sender.id), 'UNAUTHORIZED_SENDER');
    const permission = await api(`collaborators/${encodeURIComponent(event.sender.login)}/permission`);
    authorize(event, { repository: process.env.GITHUB_REPOSITORY, attempt: process.env.GITHUB_RUN_ATTEMPT, actor: process.env.GITHUB_ACTOR, triggeringActor: process.env.GITHUB_TRIGGERING_ACTOR }, permission.permission, policy);
    authorized = true;
    demand(/^\d+$/.test(runId), 'INVALID_RUN_ID');
    const issue = await api(`issues/${event.issue.number}`);
    demand(issue.state === 'open' && issue.labels.some(x => x.name === 'codex-ready') && issue.body === event.issue.body, 'ISSUE_CHANGED');
    demand(!issue.assignees.length, 'ISSUE_ASSIGNED');
    const id = goalId(issue.body);
    const manifest = local('goals/manifest.json');
    demand(manifest.goals.some(x => x.id === id && x.path === `goals/${id}.json`), 'GOAL_NOT_FOUND');
    const goal = local(`goals/${id}.json`);
    const dependencies = dependenciesFor(goal);
    const {scope, checks} = validateGoal(goal, manifest, local('goals/checks/catalog.json'), skltIds(), dependencies, policy);
    demand(process.env.MSS_CODEX_ENABLE === 'true', 'DISABLED_BY_OWNER');
    let runners = []; let inventoryAvailable = false;
    if (process.env.RUNNER_READ_TOKEN) {
      const inventory = await api('actions/runners?per_page=100', 'GET', undefined, process.env.RUNNER_READ_TOKEN);
      runners = inventory.runners; inventoryAvailable = inventory.total_count <= 100;
    }
    ready(policy, { keyPresent: process.env.MSS_KEY_PRESENT === 'true', runners, inventoryAvailable });
    const branch = `codex/issue-${issue.number}`;
    const base = process.env.GITHUB_SHA;
    demand(sha(base), 'INVALID_BASE');
    demand((await api('git/ref/heads/main')).object.sha===base,'MAIN_MOVED');
    demand(!(await api(`git/ref/heads/${branch}`,'GET',undefined,process.env.GH_TOKEN,true)) && !(await api(`git/ref/heads/codex/claims/${id}`,'GET',undefined,process.env.GH_TOKEN,true)),'EXISTING_CLAIM_OR_BRANCH');
    const baseCommit = await api(`git/commits/${base}`);
    const claim = await api('git/commits', 'POST', { message: `MSS claim ${id} issue ${issue.number} run ${runId} body ${digest(issue.body)}`, tree: baseCommit.tree.sha, parents: [base] });
    // Atomic create-only GOAL claim also fences two different Issues for one GOAL.
    await api('git/refs', 'POST', { ref: `refs/heads/codex/claims/${id}`, sha: claim.sha });
    const claimRead = await api(`git/ref/heads/codex/claims/${id}`);
    demand(claimRead.object.sha === claim.sha, 'CLAIM_NOT_OWNED');
    const started = transition(goal, 'IN_PROGRESS', { source: base, branch });
    const progress = await metadataCommit(base, [{path:`goals/${id}.json`,value:started}], `Start ${id} for Issue #${issue.number}`);
    await api('git/refs', 'POST', { ref:`refs/heads/${branch}`,sha:progress.sha });
    await api(`issues/${issue.number}/assignees`, 'POST', { assignees: [event.sender.login] });
    const plan = {schema:'mss-dispatch-plan-v1',goal:id,issue:issue.number,run:runId,base,progress:progress.sha,branch,claim:claim.sha,issue_hash:digest(issue.body),policy_hash:digest(JSON.stringify(policy)),scope,checks};
    save('plan.json', plan);
    await comment(issue.number,'IN_PROGRESS','CLAIM_CONFIRMED');
    output('ready','true'); output('progress_sha',progress.sha); output('goal',id);
  } catch (error) {
    const code = error instanceof Blocked ? error.code : 'INVALID_PROJECT_CONFIGURATION';
    // A potentially applied write stops the controller; it must not issue more writes.
    if (code.includes('OUTCOME_UNKNOWN') || code.includes('WRITE_REJECTED') || code === 'CLAIM_NOT_OWNED') throw error;
    output('ready','false');
    if (authorized) await comment(event.issue.number,'BLOCKED',code);
    if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, `MSS dispatcher: ${authorized ? 'BLOCKED' : 'DENIED'} (${code}). No model run.\n`);
    process.exitCode=1;
  }
}
function plan() {
  const p = read(path.join(out,'plan.json'));
  demand(p.schema === 'mss-dispatch-plan-v1' && p.run === runId && p.policy_hash === digest(JSON.stringify(policy)) && sha(p.base) && sha(p.progress) && p.branch === `codex/issue-${p.issue}` && /^MSS-\d{3}$/.test(p.goal), 'INVALID_PLAN');
  demand(p.base === process.env.GITHUB_SHA && p.base === git(trusted,['rev-parse','HEAD']), 'WRONG_TRUSTED_BASE');
  const goal=local(`goals/${p.goal}.json`);
  const dependencies=dependenciesFor(goal);
  const admitted=validateGoal(goal,local('goals/manifest.json'),local('goals/checks/catalog.json'),skltIds(),dependencies,policy);
  demand(JSON.stringify(p.scope)===JSON.stringify(admitted.scope) && JSON.stringify(p.checks)===JSON.stringify(admitted.checks), 'TAMPERED_SCOPE_OR_CHECKS');
  return p;
}
async function owned(p) {
  const event=read(process.env.GITHUB_EVENT_PATH);
  demand(event.issue.number===p.issue && digest(event.issue.body??'')===p.issue_hash,'WRONG_ISSUE_BINDING');
  const issue=await api(`issues/${p.issue}`);
  demand(issue.state==='open' && issue.labels.some(x=>x.name==='codex-ready') && digest(issue.body??'')===p.issue_hash && issue.assignees.length===1 && issue.assignees[0].login===event.sender.login,'ISSUE_CHANGED_OR_OWNER_LOST');
  const claim=await api(`git/ref/heads/codex/claims/${p.goal}`);
  demand(claim.object.sha===p.claim,'CLAIM_NOT_OWNED');
  const claimCommit=await api(`git/commits/${p.claim}`);
  demand(claimCommit.message===`MSS claim ${p.goal} issue ${p.issue} run ${p.run} body ${p.issue_hash}` && claimCommit.parents.length===1 && claimCommit.parents[0].sha===p.base,'INVALID_CLAIM');
  const progress=await api(`git/commits/${p.progress}`);
  demand(progress.parents.length===1 && progress.parents[0].sha===p.base,'INVALID_PROGRESS_HISTORY');
  demand((await api('git/ref/heads/main')).object.sha===p.base && (await api(`git/ref/heads/${p.branch}`)).object.sha===p.progress,'SOURCE_OR_BRANCH_MOVED');
  const compared=await api(`compare/${p.base}...${p.progress}`);
  demand(compared.total_commits===1 && compared.files?.length===1 && compared.files[0].filename===`goals/${p.goal}.json` && compared.files[0].status==='modified','UNSAFE_PROGRESS_TREE');
  const expected=transition(local(`goals/${p.goal}.json`),'IN_PROGRESS',{source:p.base,branch:p.branch});
  const goalFile=await api(`contents/goals/${p.goal}.json?ref=${p.progress}`);
  demand(JSON.stringify(JSON.parse(Buffer.from(goalFile.content,'base64').toString('utf8')))===JSON.stringify(expected),'INVALID_PROGRESS_GOAL');
}
function pinFile(file, hash) {
  demand(fs.lstatSync(file).isFile() && !fs.lstatSync(file).isSymbolicLink() && digest(fs.readFileSync(file)) === hash, 'HOST_PIN_MISMATCH');
}
async function workerPrepare() {
  const p = plan();
  await owned(p);
  demand(process.platform === 'win32' && process.env.RUNNER_ENVIRONMENT === 'self-hosted', 'NOT_NATIVE_WINDOWS_RUNNER');
  demand(process.env.RUNNER_NAME === policy.worker_name,'WRONG_WORKER_IDENTITY');
  demand(policy.codex_home==='C:\\ProgramData\\MSS-Codex\\codex-home','UNREVIEWED_CODEX_HOME');
  const privilege=spawnSync('pwsh',['-NoProfile','-NonInteractive','-Command','([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)'],{encoding:'utf8',shell:false});
  demand(privilege.status===0 && privilege.stdout.trim()==='False','PRIVILEGED_OR_UNKNOWN_WORKER');
  demand(git(work,['rev-parse','HEAD']) === p.progress, 'WRONG_CHECKOUT');
  pinFile(path.join(policy.codex_home,'config.toml'),policy.isolation.config_sha256);
  const requirements=spawnSync('pwsh',['-NoProfile','-NonInteractive','-Command',"$key=[Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine,[Microsoft.Win32.RegistryView]::Registry64).OpenSubKey('SOFTWARE\\Policies\\OpenAI\\Codex'); $override=if($key){$key.GetValue('RequirementsPath')}; if($override){$override}else{Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'OpenAI\\Codex\\requirements.toml'}"],{encoding:'utf8',shell:false});
  demand(requirements.status===0 && requirements.stdout.trim().toLowerCase()===policy.managed_requirements.toLowerCase(),'UNREVIEWED_REQUIREMENTS_PATH');
  pinFile(policy.managed_requirements,policy.isolation.requirements_sha256);
  pinFile(policy.check_broker,policy.isolation.broker_sha256);
  const issue = await api(`issues/${p.issue}`);
  demand(issue.state === 'open' && digest(issue.body ?? '') === p.issue_hash, 'ISSUE_CHANGED');
  const instructions = fs.readFileSync(path.join(trusted,'.github/prompts/codex-issue.md'),'utf8');
  fs.writeFileSync(path.join(out,'prompt.txt'), instructions + '\nUNTRUSTED_TASK_DATA_JSON:\n' + JSON.stringify({goal:p.goal,issue:p.issue,title:issue.title,body:issue.body,allowed_paths:p.scope.paths,checks:p.checks.map(c=>({id:c.id,command:c.command}))}));
}
function changedFiles(base, head) {
  const names = git(work,['diff','--name-only','--no-renames','-z',base,head]).split('\0').filter(Boolean);
  return names.map(name => {
    const entry = git(work,['ls-tree',head,'--',name]).split(/\s+/);
    demand(entry[0] === '100644', 'DELETIONS_OR_SPECIAL_FILES_DENIED');
    return {path:name,mode:entry[0],bytes:Number(git(work,['cat-file','-s',entry[2]]))};
  });
}
async function collect() {
  const p = plan();
  let source = p.progress; let receipts = []; let state = 'BLOCKED'; let reason = 'CODEX_FAILED_OR_UNKNOWN';
  if (process.env.MSS_CODEX_OUTCOME === 'success') {
    // No agent-provided command, output, branch or status is trusted here.
    demand(git(work,['rev-parse','HEAD']) === p.progress, 'AGENT_CHANGED_GIT_HISTORY');
    const names = git(work,['status','--porcelain=v1','-z','--untracked-files=all']).split('\0').filter(Boolean).map(x=>x.slice(3));
    const files = names.map(name => {
      validatePath(name.replaceAll('\\','/'));
      const full = path.resolve(work,name);
      demand(full.startsWith(work + path.sep), 'UNSAFE_WORKTREE_PATH');
      demand(fs.realpathSync(full).toLowerCase().startsWith(fs.realpathSync(work).toLowerCase()+path.sep),'EXTERNAL_REPARSE_TARGET');
      let current=work;
      for(const component of path.relative(work,full).split(path.sep)) {
        current=path.join(current,component);
        demand(!fs.lstatSync(current).isSymbolicLink(),'REPARSE_POINT_DENIED');
      }
      const stat = fs.lstatSync(full);
      demand(stat.isFile() && !stat.isSymbolicLink(), 'UNSAFE_WORKTREE_FILE');
      return {path:name.replaceAll('\\','/'),mode:'100644',bytes:stat.size};
    });
    validateChanges(files,p.scope);
    git(work,['add','--',...files.map(f=>f.path)]);
    git(work,['-c','user.name=MSS Codex Worker','-c','user.email=mss-codex@users.noreply.github.com','commit','-m',`Implement ${p.goal} for Issue #${p.issue}`]);
    source = git(work,['rev-parse','HEAD']);
    validateChanges(changedFiles(p.progress,source),p.scope);
    // Host-owned, hash-pinned broker: exact argv arrays, native OS restrictions,
    // bounded evidence store, no API/GitHub credentials. Never a shell string.
    pinFile(policy.check_broker,policy.isolation.broker_sha256);
    const r = spawnSync(policy.check_broker, [], { cwd:work,shell:false,encoding:'utf8',input:JSON.stringify({schema:'mss-native-check-request-v1',goal:p.goal,attempt:p.run,source_commit:source,workspace:work,checkout_mode:'fresh-exact-commit',checks:p.checks}),timeout:900000,maxBuffer:1048576,env:{SystemRoot:process.env.SystemRoot,PATH:process.env.PATH,TEMP:process.env.TEMP} });
    if (r.status === 0 && !r.error) {
      receipts = checkReceipts(JSON.parse(r.stdout),p.checks,source,{goal:p.goal,attempt:p.run});
      demand(git(work,['status','--porcelain=v1','--untracked-files=no']) === '', 'CHECKS_MUTATED_SOURCE');
      state = receipts.every(r=>r.result === 'PASS') ? 'IN_REVIEW' : 'BLOCKED'; reason = state === 'IN_REVIEW' ? 'CHECKS_PASSED' : 'CHECKS_NOT_PASSED';
    } else reason = 'CHECK_BROKER_FAILED_OR_UNKNOWN';
  }
  const result = {schema:'mss-worker-result-v1',run:p.run,goal:p.goal,source_commit:source,state,reason,receipts};
  save('result.json',result);
  if (source !== p.progress) {
    git(work,['branch','mss-worker',source]);
    git(work,['bundle','create',path.join(out,'worker.bundle'),`mss-worker`, `^${p.progress}`]);
  }
}
async function publish() {
  const p=plan();
  await owned(p);
  let result={schema:'mss-worker-result-v1',run:p.run,goal:p.goal,source_commit:p.progress,state:'BLOCKED',reason:'WORKER_DID_NOT_COMPLETE',receipts:[]};
  if (fs.existsSync(path.join(out,'result.json'))) result=read(path.join(out,'result.json'));
  demand(result.schema==='mss-worker-result-v1' && result.run===p.run && result.goal===p.goal && sha(result.source_commit), 'INVALID_WORKER_RESULT');
  let source=p.progress;
  if (result.source_commit!==p.progress) {
    const bundle=path.join(out,'worker.bundle');
    demand(fs.lstatSync(bundle).isFile() && fs.statSync(bundle).size<=20971520,'INVALID_BUNDLE');
    // Import objects only. Never check out or execute generated files on control.
    git(trusted,['fetch','--no-tags',bundle,'refs/heads/mss-worker']);
    source=git(trusted,['rev-parse','FETCH_HEAD']);
    demand(source===result.source_commit && git(trusted,['rev-list','--count',`${p.progress}..${source}`])==='1' && git(trusted,['rev-parse',`${source}^`])===p.progress,'INVALID_WORKER_HISTORY');
    const names=git(trusted,['diff','--name-only','--no-renames','-z',p.progress,source]).split('\0').filter(Boolean);
    const files=names.map(name=>{const entry=git(trusted,['ls-tree',source,'--',name]).split(/\s+/);return {path:name,mode:entry[0],bytes:entry[2]?Number(git(trusted,['cat-file','-s',entry[2]])):-1};});
    validateChanges(files,p.scope);
    const ref=await api(`git/ref/heads/${p.branch}`); demand(ref.object.sha===p.progress,'BRANCH_MOVED');
    const basic=Buffer.from(`x-access-token:${process.env.GH_TOKEN}`).toString('base64');
    git(trusted,['push','origin',`${source}:refs/heads/${p.branch}`],{GIT_CONFIG_COUNT:'1',GIT_CONFIG_KEY_0:'http.https://github.com/.extraheader',GIT_CONFIG_VALUE_0:`AUTHORIZATION: basic ${basic}`});
  }
  const receipts=result.receipts.length ? checkReceipts(result.receipts,p.checks,source,{goal:p.goal,attempt:p.run}) : [];
  const complete=result.state==='IN_REVIEW' && receipts.length===p.checks.length && receipts.every(r=>r.result==='PASS');
  // Publication uses fixed text, never raw model output or arbitrary broker logs.
  const pr=await api('pulls','POST',{head:p.branch,base:'main',draft:true,title:`MSS ${p.goal}: Issue #${p.issue}`,body:`Issue: https://github.com/${REPOSITORY}/issues/${p.issue}\n\nState: ${complete?'IN_REVIEW':'BLOCKED'}. Tested source: ${source}.\nChecks: ${receipts.map(r=>`${r.check_id}=${r.result}`).join(', ')||'NOT_RUN (worker failed or unavailable)'}.\nEvidence: goals/events/ in this branch. Toolkit parity: NOT_VERIFIED.\nNo automatic merge or VERIFIED transition. Run: https://github.com/${REPOSITORY}/actions/runs/${p.run}`});
  const goal=JSON.parse(git(trusted,['show',`${p.progress}:goals/${p.goal}.json`]));
  const safeReceipts=receipts.map(r=>({schema:r.schema,goal_id:p.goal,check_id:r.check_id,attempt:p.run,source_commit:source,runner:`approved-worker-${policy.worker_runner_id}`,command:r.command,started_at:r.started_at,ended_at:r.ended_at,result:r.result,exit_code:Number.isInteger(r.exit_code)?r.exit_code:null,test_summary:r.test_summary?{passed:r.test_summary.passed,failed:r.test_summary.failed,skipped:r.test_summary.skipped}:null,evidence:(r.evidence??[]).filter(e=>/^[a-f0-9]{64}$/.test(e.sha256??'') && e.ref===`sha256:${e.sha256}`).map(e=>({ref:e.ref,sha256:e.sha256})),evidence_ref:`goals/events/${p.goal}-${p.run}-${r.check_id}.json`}));
  const next=transition(goal,complete?'IN_REVIEW':'BLOCKED',{source,branch:p.branch,pr:pr.html_url,receipts:safeReceipts});
  const records=safeReceipts.map(r=>({path:r.evidence_ref,value:r}));
  records.push({path:`goals/events/${p.goal}-${p.run}-dispatch.json`,value:{schema:'mss-dispatch-receipt-v1',goal_id:p.goal,attempt:p.run,source_commit:source,result:complete?'IN_REVIEW':'BLOCKED',reason:complete?'CHECKS_PASSED':'WORKER_OR_CHECKS_NOT_VERIFIED',pr_url:pr.html_url,run_url:`https://github.com/${REPOSITORY}/actions/runs/${p.run}`}});
  const metadata=await metadataCommit(source,[{path:`goals/${p.goal}.json`,value:next},...records],`Record ${p.goal} ${next.status} with source ${source}`);
  await advance(p.branch,source,metadata.sha);
  await comment(p.issue,next.status,complete?'DRAFT_PR_READY':'WORKER_OR_CHECKS_BLOCKED',pr.html_url);
  if(!complete) process.exitCode=1;
}

const stages={prepare,'worker-prepare':workerPrepare,collect,publish};
try { demand(Boolean(stages[process.argv[2]]),'INVALID_STAGE'); await stages[process.argv[2]](); }
catch(error) {
  // Do not print arbitrary error messages, subprocess output, model output or secrets.
  const code=error instanceof Blocked ? error.code : 'UNEXPECTED_FAILURE_NO_AUTOMATIC_RETRY';
  console.error(`MSS dispatcher: BLOCKED (${code}). Inspect the run and owned refs; do not retry uncertain writes.`);
  process.exitCode=1;
}
