// Offline validation with an already installed YAML 1.2 parser. No downloads.
import fs from 'node:fs';
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url);
if (!process.argv[2]) throw new Error('Supply an installed yaml module or module exporting .yaml');
const loaded=require(process.argv[2]);
const yaml=loaded.yaml??loaded;
const document=yaml.parseDocument(fs.readFileSync(new URL('../../.github/workflows/codex-issue.yml',import.meta.url),'utf8'),{strict:true,uniqueKeys:true});
assert.deepEqual(document.errors,[]);
const workflow=document.toJS();
assert.deepEqual(workflow.on,{issues:{types:['labeled']}});
assert.deepEqual(workflow.permissions,{});
assert.match(workflow.concurrency.group,/github.event.issue.number/);
assert.equal(workflow.concurrency['cancel-in-progress'],false);
assert.deepEqual(Object.keys(workflow.jobs),['prepare','implement','publish']);
for(const job of Object.values(workflow.jobs)) {
  assert.deepEqual(job['runs-on'].slice(0,3),['self-hosted','Windows','X64']);
  assert.ok(Number.isInteger(job['timeout-minutes']) && job['timeout-minutes']<=45);
  assert.ok(!job.container && !job.services);
  for(const step of job.steps) if(step.uses) assert.match(step.uses,/@[a-f0-9]{40}$/);
}
assert.equal(workflow.jobs.prepare.permissions.contents,'write');
assert.deepEqual(workflow.jobs.implement.permissions,{contents:'read',issues:'read'});
assert.deepEqual(workflow.jobs.publish.permissions,{contents:'write','pull-requests':'write',issues:'write'});
assert.equal(workflow.jobs.implement.environment,'mss-codex-owner-approved');
const action=workflow.jobs.implement.steps.find(s=>s.id==='codex');
assert.equal(action.with['permission-profile'],'mss-issue');
assert.equal(action.with['codex-version'],'0.166.0');
assert.equal(action.with['safety-strategy'],'unsafe');
assert.ok(action.with['prompt-file'] && !action.with.prompt && !action.with.sandbox);
assert.equal(action.with['openai-api-key'],'${{ secrets.OPENAI_API_KEY }}');
assert.ok(!Object.values(workflow.jobs).some(j=>JSON.stringify(j.env??{}).includes('OPENAI_API_KEY')));
assert.ok(!JSON.stringify(workflow.jobs.publish).includes('OPENAI_API_KEY'));
console.log('PASS: YAML syntax and offline workflow security contracts (not a GitHub engine run)');
