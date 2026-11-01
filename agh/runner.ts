/** Actual upstream Kernel scheduling, with only three current-application stages, including the unchanged autonomous Agent. */
import { Kernel, MemoryStorage, presetDefaults, createWorkspaceInvocationPort,
  canonicalJson, sha256Hex, scanAll, FS_DENIED } from '@agnes/core';
import { Type } from '@sinclair/typebox';
import { spawn } from 'node:child_process';
import { realpath, mkdir, writeFile, appendFile, stat, readFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { randomUUID } from 'node:crypto';

const PIN = '4bc36bc4c4441206388a53bece17379c1d7be14d';
const SERVED = process.env.PAIR_AKI_MODEL;
if (!SERVED) throw Error("PAIR_AKI_MODEL_required");
const names = ['admit_case', 'execute_assessment', 'verify_assessment'];
const descriptions = [
 '核验选定病例时点、当前API与两个已登记医学模型身份，不执行医学模型。',
 '身份核验成功后，将原始自然语言任务交给当前自主Agent；由其决定预测、检索或补证并等待真实终态。',
 '重新读取真实运行记录，核验输入、模型身份、二值结果与引用；失败和部分结果保持原终态。'
];
const root = await realpath(process.env.PAIR_AKI_PROJECT_ROOT || process.cwd());
if (!process.env.PAIR_AKI_STATE_ROOT) throw Error('state_root_required');
const stateRoot = resolve(process.env.PAIR_AKI_STATE_ROOT);
if (stateRoot === root || stateRoot.startsWith(root + '/')) throw Error('state_must_be_outside_source');
await mkdir(stateRoot, {recursive: true, mode: 0o700});
const runId = randomUUID();
const output = join(stateRoot, runId);
await mkdir(output, {mode: 0o700});
if (!process.env.PAIR_AKI_REQUEST) throw Error('request_file_required');
const goalRequest = JSON.parse(await readFile(process.env.PAIR_AKI_REQUEST, 'utf8'));
const caseRef = goalRequest.case_ref;
process.env.PAIR_AKI_RUN_DIR = output;
const url = process.env.PAIR_AKI_MODEL_URL || 'http://127.0.0.1:8000/v1';
if (!/^http:\/\/127\.0\.0\.1:[0-9]+\/v1$/.test(url)) throw Error('loopback_llm_required');
const deadline = AbortSignal.timeout(420_000);
const previous: Record<string, any> = {};
const rawReceipts: Record<string, string> = {};
const providerReceipts: any[] = [];
let toolFailure = false;
const costRows: any[] = [];
const hash = (value: unknown) => sha256Hex(canonicalJson(value));
const persist = async (name: string, value: unknown) => writeFile(join(output, name), JSON.stringify(value, null, 2) + '\n', {mode: 0o600});
const trace = async (value: unknown) => appendFile(join(output, 'tool-trace.jsonl'), JSON.stringify(value) + '\n', {mode: 0o600});

async function request(path: string, body?: unknown, signal = deadline) {
  const response = await fetch(url + path, {method: body ? 'POST' : 'GET', redirect: 'error',
    headers: {'Content-Type': 'application/json', ...(process.env.PAIR_AKI_MODEL_API_KEY ? {Authorization: 'Bearer '+process.env.PAIR_AKI_MODEL_API_KEY} : {})}, body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.any([signal, AbortSignal.timeout(70_000)])});
  if (!response.ok) throw Error('provider_http_' + response.status);
  const bytes = await response.text();
  if (Buffer.byteLength(bytes) > 2_000_000) throw Error('provider_response_too_large');
  return JSON.parse(bytes);
}

async function identity() {
 return {served_model: SERVED, wire_model: SERVED, identity_policy: 'configured-model-id-and-response-match'};
}

function bridge(tool: string, signal: AbortSignal): Promise<any> {
  const input = {tool, case_ref: caseRef, previous: rawReceipts};
  return new Promise((accept, reject) => {
    const child = spawn(process.env.PAIR_AKI_PYTHON || 'python3', ['-m', 'pair_aki.compat.bridge'], {
      cwd: root, env: {...process.env, PYTHONPATH: root, PYTHONDONTWRITEBYTECODE: '1'},
      stdio: ['pipe', 'pipe', 'pipe'], shell: false,
      signal: AbortSignal.any([signal, AbortSignal.timeout(280_000)]), killSignal: 'SIGTERM'});
    let stdout = '', stderr = '', rejected = false;
    child.stdout.on('data', chunk => {
      stdout += chunk.toString();
      if (Buffer.byteLength(stdout) > 262144) { rejected = true; child.kill('SIGTERM'); reject(Error('bridge_output_budget')); }
    });
    child.stderr.on('data', chunk => { stderr = (stderr + chunk.toString()).slice(-1000); });
    child.on('error', reject);
    child.on('close', code => {
      if (rejected) return;
      if (code !== 0) return reject(Error('bridge_failed:' + stderr.trim()));
      try {
        const result = JSON.parse(stdout);
        if (result.tool !== tool) throw Error('bridge_result_identity');
        accept({receipt: result, rawText: stdout});
      } catch (error) { reject(error); }
    });
    child.stdin.end(JSON.stringify(input));
  });
}

const provider = {
  models: () => [{id: SERVED, name: SERVED, api: 'openai-completions', route: 'local-qwen',
    baseUrl: url, reasoning: false, input: ['text'], cost: {input: 0, output: 0, cacheRead: 0, cacheWrite: 0},
    contextWindow: 16384, maxTokens: 768, toolCallFormats: ['inline_json'], thinkingReplay: 'drop', contract_id: null}],
  async *infer(req: any, opts: any): AsyncGenerator<any> {
    if (toolFailure) throw Error('tool_failed_no_automatic_replay');
    const serving = await identity();
    const remainingTools = names.filter(name => !previous[name]);
    const allowedActions = remainingTools.length ? remainingTools : ['finish'];
    const system = '你是参赛作品的受控运行调度器。按真实反馈执行身份核验、当前自主Agent任务、结果复核三个阶段。' +
      '严格依赖顺序admit_case、execute_assessment、verify_assessment。已完成阶段不可重复，全部核验后才能finish。' +
      '医学任务由现有自主Agent按原始goal决定，不改变原任务，不伪造结果。';
    const content = JSON.stringify({task: goalRequest.goal, case_ref: caseRef,
      completed_tools: Object.entries(previous).map(([name, receipt]) => ({name, status: 'complete',
        input_sha256: receipt.input_sha256, output_sha256: receipt.output_sha256})),
      remaining_tools_in_dependency_order: remainingTools, allowed_actions: allowedActions, kernel_request: req});
    if (Buffer.byteLength(content) > 48_000) throw Error('provider_context_budget');
    const payload = {model: SERVED, temperature: 0, max_tokens: 768, stream: false,
      chat_template_kwargs: {enable_thinking: false},
      messages: [{role: 'system', content: system}, {role: 'user', content}],
      response_format: {type: 'json_schema', json_schema: {name: 'competition_action', strict: true,
        schema: {type: 'object', properties: {tool: {type: 'string', enum: allowedActions},
          reason: {type: 'string', minLength: 1, maxLength: 240}}, required: ['tool', 'reason'], additionalProperties: false}}}};
    yield {type: 'sent', stamp: {contract_id: req.contractId, parser_version: 'pair-aki-inline-json-v1',
      prompt_prefix_hash: hash(system), tool_schema_hash: hash(req.tools), derived_hash: req.derivedHash,
      sent_hash: hash(payload), model: {route: req.route, id: req.model},
      transforms: [{event: 'inline-json-action', ext: 'pair-aki-compat'}]}};
    const started = Date.now();
    const raw = await request('/chat/completions', payload, opts.signal);
    const choice = raw.choices?.[0];
    if (raw.model !== SERVED || choice?.finish_reason !== 'stop') throw Error('provider_incomplete_or_wrong_model');
    const action = JSON.parse(choice.message.content);
    if (!action || Object.keys(action).sort().join(',') !== 'reason,tool' ||
        !allowedActions.includes(action.tool) || typeof action.reason !== 'string') throw Error('provider_action_schema');
    const receipt = {at: new Date().toISOString(), serving, derived_hash: req.derivedHash, sent_hash: hash(payload),
      raw_action: action, response_sha256: hash(raw), response: raw, elapsed_ms: Date.now() - started};
    providerReceipts.push(receipt);
    await persist('provider-receipts.json', providerReceipts);
    if (action.tool === 'finish') {
      if (previous.verify_assessment?.output?.status !== 'verified') throw Error('provider_premature_finish');
      yield {type: 'text_delta', delta: '三个受控工具已完成；请以已核验的工具输出与证据引用为准。'};
    } else {
      yield {type: 'toolcall_end', call: {toolUseId: '', name: action.tool, args: {}, ordinal: 0}, via: 'inline_json'};
    }
    yield {type: 'usage', tokens: {input: raw.usage?.prompt_tokens || 0, output: raw.usage?.completion_tokens || 0,
      cacheRead: 0, cacheWrite: 0}, credits: 0, creditSource: 'estimated'};
    yield {type: 'done', reason: action.tool === 'finish' ? 'stop' : 'toolUse'};
  },
};

const denied = async () => { throw Object.assign(Error('capability_disabled'), {code: FS_DENIED}); };
const policy = {workspaceRoot: root, rules: [{effect: 'allow', path: root, source: 'workspace', hard: false}],
  networkAllow: [], digest: hash({root, profile: 'no-general-tools-v1'})};
// No file content surface is exposed. Root stat is real; every other path is refused.
const fsOps = {read: denied, write: denied, list: denied, stat: async (path: string) => {
  if (resolve(root, path) !== root) return denied();
  const value = await stat(root);
  return {kind: 'dir', size: value.size, mtimeMs: value.mtimeMs};
}};
const actor = {id: 'pair-aki', org: 'local', role: 'owner', deptPath: [], attrs: {}};
const sandbox: any = {forWorkspace: async () => sandbox, exec: denied, confine: denied,
  fsPolicy: () => policy, enforcement: () => ({level: 'partial', scope: ['file']})};
const approval: any = {ask: async () => 'rejected', resume: async () => null};
const checkpoint: any = {snapshot: denied, rewind: denied, list: async () => []};
const seams: any = {sandbox, approval, checkpoint,
  ledger: {record: async (row: any) => {costRows.push(row);}, projected: async () => ({credits: 0, creditSource: 'estimated'})},
  verifier: {verify: async () => ({verdict: previous.verify_assessment?.output?.status === 'verified' ? 'pass' : 'fail',
    reasons: previous.verify_assessment ? [] : ['No verified tool output']})},
  repair: {decide: async () => 'park'},
  artifacts: {put: denied, get: denied, submitJob: denied, poll: denied, cancel: denied},
  principals: {resolve: async () => actor, authorize: async (who: any, _action: any, target: any) => ({
    decisionId: 'current-v2-allowlist', effect: who.id === actor.id && names.includes(target.id) ? 'allow' : 'deny',
    reason: 'Only three registered current-application stages are admitted'})},
  platform: {shell: () => 'posix', fs: () => ({caseSensitive: true, pathSep: '/'}), terminal: () => ({color: false}),
    capability: () => ({level: 'unavailable', scope: [], reason: 'No generic platform tools'})},
  harness: {propose: async () => 'rejected'}};
const workspaceInvocation = createWorkspaceInvocationPort(() => ({source: {root, fs: fsOps, ready: async () => ({confine: denied}),
  hookSnapshot: async () => ({workspaceDigest: policy.digest, policyRevision: 'closed-v1', hooks: []}),
  hookSandbox: sandbox, approval, checkpoint}, release: () => {}}));
const preset = presetDefaults();
preset.name = 'pair-aki-closed';
preset.model.route.primary = 'local-qwen';
preset.model.id.primary = SERVED;
preset.model.contextWindow = {primary: 16384};
preset.model.maxTokens = 768;
preset.model.retry.maxAttempts = 1;
preset.model.timeoutMs = 75_000;
preset.budget.maxSteps = 7;
preset.compaction.enabled = false;
preset.tools.timeoutMs = 285_000;
preset.tools.outputMaxBytes = 262144;
preset.telemetry.invariants = 'strict';
const kernel = Kernel.create({storage: new MemoryStorage(), seams, provider: provider as any,
  contract: {contract_id: null, parser_version: 'pair-aki-inline-json-v1'}, preset, fsOps: fsOps as any,
  netFetch: denied, agnesVersion: PIN});
for (const [i, name] of names.entries()) kernel.tools.add({name, description: descriptions[i]!,
  parameters: Type.Object({}, {additionalProperties: false}), meta: {
    isReadOnly: true, isDestructive: false, isConcurrencySafe: false, isOpenWorld: false,
    replay: 'never', costHint: undefined, deferLoading: undefined, requiresApproval: 'never'},
  execute: async (_args: unknown, ctx: any) => {
    await trace({at: new Date().toISOString(), event: 'tool_start', tool: name,
      predecessor_output_hashes: Object.values(previous).map(x => x.output_sha256)});
    try {
      const {receipt, rawText} = await bridge(name, ctx.signal || deadline);
      previous[name] = receipt;
      rawReceipts[name] = rawText;
      await trace({at: new Date().toISOString(), event: 'tool_result', status: 'complete', ...receipt,
        raw_receipt_json: rawText});
      return {content: [{type: 'text', text: JSON.stringify(receipt)}]};
    } catch (error) {
      toolFailure = true;
      await trace({at: new Date().toISOString(), event: 'tool_result', status: 'failed', tool: name,
        error: error instanceof Error ? error.message : 'unknown'});
      throw error;
    }
  }}, {source: 'pair-aki-compat', trust: 'trusted'});

let session: Awaited<ReturnType<typeof kernel.session>> | undefined;
let outcome: any;
try {
  session = await kernel.session(runId, {actor, cwd: root, writerRunId: runId,
    resolvedProfileHash: hash({profile: 'closed-current-v2'}), workspaceInvocation});
  if (process.env.PAIR_AKI_PREFLIGHT === '1') {
    await persist('preflight.json', {upstream_commit: PIN, registered_tools: kernel.tools.size,
      session_opened: true, inference_called: false});
    console.log(JSON.stringify({status: 'preflight_ok', output, registered_tools: kernel.tools.size}));
  } else {
  await session.enqueue('next-turn', {actor, content: [{type: 'text', text:
    `请按原始任务完成当前应用的准入、实际执行与核验：${goalRequest.goal}`} ]});
  outcome = await session.run({until: 'turn-end', signal: deadline});
  const ledger = await scanAll((query: any) => session.scan(query), {});
  await persist('kernel-ledger.json', ledger);
  const calls = ledger.filter((row: any) => row.type === 'tool/call');
  const results = ledger.filter((row: any) => row.type === 'tool/result');
  const complete = outcome.reason === 'completed' && names.every(name => previous[name]) && previous.verify_assessment.output.status === 'verified' &&
    calls.length === 3 && results.length === 3 && results.every((row: any) => row.data.isError === false);
  await persist('run-receipt.json', {run_id: runId, upstream_commit: PIN, source_kind: previous.admit_case?.output?.source_kind, request_sha256: hash(goalRequest), outcome,
    completed: complete, step_tools: Object.keys(previous), ledger_sha256: hash(ledger),
    model_calls: providerReceipts.length, medical_models: previous.admit_case?.output?.capabilities?.medical_models,
    file_identity_source: 'Configured endpoint identity; see receipts', estimated_billing_only: true, cost_rows: costRows, inner_run_id: previous.execute_assessment?.output?.inner_run_id, application_status: previous.verify_assessment?.output?.application_status});
  console.log(JSON.stringify({run_id: runId, completed: complete, outcome, output, steps: Object.keys(previous),
    medical_models: previous.admit_case?.output?.capabilities?.medical_models}));
  if (!complete) process.exitCode = 2;
  }
} catch (error) {
  await persist('failure.json', {error: error instanceof Error ? error.message : String(error)});
  if (session) {
    try { await persist('kernel-ledger.json', await scanAll((query: any) => session.scan(query), {})); }
    catch (ledgerError) { await persist('ledger-export-failure.json', {error: String(ledgerError)}); }
  }
  console.error(JSON.stringify({run_id: runId, status: 'failed', output,
    error: error instanceof Error ? error.message : String(error)}));
  process.exitCode = 1;
} finally { await kernel.close(); }
