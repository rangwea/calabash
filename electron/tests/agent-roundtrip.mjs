/** Real Cordis tool registration + Python stdio + strict build; no model provider. */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtemp, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
const root = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const upstream = resolve(process.env.CALABASH_HARNESS_SOURCE ?? join(root, 'build/harness', JSON.parse(await readFile(join(root, 'electron/harness.lock.json'), 'utf8')).commit));
const home = await mkdtemp(join(tmpdir(), 'calabash-dsh-agent-'));
const previous = { HOME: process.env.HOME, USERPROFILE: process.env.USERPROFILE, DSH_HOME: process.env.DSH_HOME, CALABASH_REPOSITORY: process.env.CALABASH_REPOSITORY, CALABASH_PYTHON: process.env.CALABASH_PYTHON };
// DSH_HOME must be redirected too: the host journal and workspace state live under it
// and the check must never touch the developer's real profile.
Object.assign(process.env, { HOME: home, USERPROFILE: home, DSH_HOME: home, CALABASH_REPOSITORY: root, CALABASH_PYTHON: join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python') });
const load = relative => import(pathToFileURL(join(upstream, relative)).href);
let ctx;
try {
  const { Context } = await load('vendor/cordis/lib/index.js');
  const { default: SystemPrompt } = await load('packages/core/system-prompt/lib/index.js');
  const { default: Tools } = await load('packages/core/tools/lib/index.js');
  const { Session } = await load('packages/core/session/lib/index.js');
  const { default: Projections } = await load('packages/session/session-projection/lib/index.js');
  const { default: Plugin } = await load('packages/client/calabash-workspace/lib/index.js');
  ctx = new Context();
  await ctx.plugin(SystemPrompt, { personaPrefix: 'Synthetic Calabash acceptance' });
  await ctx.plugin(Tools);
  await ctx.plugin(Projections);
  const Stats = await load('packages/session/session-stats/lib/index.js');
  await ctx.plugin(Stats);
  await ctx.plugin(Plugin);
  const events = [];
  ctx.on('session/event', (session, event) => events.push({ session: session.id, event }));
  const manualSession = Session.create('synthetic-session');
  const tool = ctx.tools.get('calabash_tool');
  assert.ok(tool, 'The actual DSH tool registry must expose Calabash');
  assert.equal(tool.presentCall({ operation: 'read_tool_file' }).title, '读取工具代码');
  const secret = 'synthetic-private-source';
  const shown = tool.presentResult({ operation: 'read_tool_file' }, { isError: false, content: [{ type: 'text', text: JSON.stringify({ lines: [{ text: secret }] }) }] });
  assert.ok(!JSON.stringify(shown).includes(secret), 'DSH UI presenter must not show source bodies');
  assert.ok(tool.presentResult({ operation: 'check_tool_build' }, { isError: false, content: [{ type: 'text', text: '{"state":"failed"}' }] }).content[0].text.includes('调整'));
  assert.ok(tool.presentResult({ operation: 'patch_tool_file' }, { isError: false, content: [{ type: 'text', text: '{"saved":false,"error":"tool_binding_conflict"}' }] }).content[0].text.includes('未完成'));
  assert.ok(!JSON.stringify(tool.presentResult({ operation: 'write_tool_file' }, { isError: true, content: [{ type: 'text', text: secret }] })).includes(secret));
  const files = JSON.parse(execFileSync(process.env.CALABASH_PYTHON, ['-c', 'import json; from tests.test_tool_bundles import fixture; print(json.dumps(fixture()))'], { cwd: root, env: process.env, encoding: 'utf8' }));
  let sequence = 0;
  const call = async (operation, args = {}) => JSON.parse(await tool.execute({ operation, ...args }, { agent: { session: manualSession }, callId: `test-${++sequence}` }));
  const instructions = await call('instructions'); assert.ok(instructions.skill.includes('Calabash'));
  assert.deepEqual(await call('list_tools'), []);
  const action = await call('read_action_api', { action_id: 'ai.text' });
  assert.equal(action.network, 'user_selected_model'); assert.ok(action.input_schema.properties.text);
  await assert.rejects(() => call('run_action', { project: 'demo', name: 'counter' }));
  for (const [path, content] of Object.entries(files)) {
    assert.equal((await call('write_tool_file', { project: 'demo', name: 'counter', path, content })).saved, true);
  }
  assert.equal(JSON.parse(await ctx.calabashWorkspace.state('synthetic-session')).name, 'counter');
  const checked = await call('check_tool_build', { project: 'demo', name: 'counter' });
  assert.equal(checked.state, 'passed', JSON.stringify(checked));
  assert.deepEqual(JSON.parse(await ctx.calabashWorkspace.list()), [], 'Agent saving must not publish');
  await assert.rejects(() => tool.execute({ operation: 'list_tools' }, { callId: 'unowned' }), /conversation/);
  const { default: LlmRuntime, LlmAdapter, createUserMessage } = await load('packages/llm/llm/lib/index.js');
  const { default: Sessions } = await load('packages/core/session/lib/index.js');
  const { default: Agents } = await load('packages/core/agent/lib/index.js');
  const Native = await load('packages/core/tool-executor-native/lib/index.js');
  const { default: Loop } = await load('packages/core/agent-loop/lib/index.js');
  await ctx.plugin(LlmRuntime); await ctx.plugin(Sessions);
  await ctx.plugin(Native); await ctx.plugin(Agents); await ctx.plugin(Loop, { agents: [] });
  const loopFiles = { ...files, 'tool.json': JSON.stringify({ ...JSON.parse(files['tool.json']), name: 'loop_counter' }) };
  const script = [{ operation: 'instructions' }, { operation: 'read_action_api', action_id: 'ai.text' }, { operation: 'read_tool_template', project: 'demo', name: 'loop_counter' },
    ...Object.entries(loopFiles).map(([path, content]) => ({ operation: 'write_tool_file', project: 'demo', name: 'loop_counter', path, content })),
    { operation: 'check_tool_build', project: 'demo', name: 'loop_counter' }];
  const scriptedCalls = script.length;
  class Model extends LlmAdapter {
    requests = [];
    async resolveModel(provider, id) { return { provider, id, name: id }; }
    async *stream(options) {
      this.requests.push(options);
      const args = script.shift();
      if (args) {
        const id = `loop-call-${this.requests.length}`, raw = JSON.stringify(args);
        yield { type: 'block-start', index: 0, blockType: 'tool-call' };
        yield { type: 'tool-call-delta', index: 0, id, name: 'calabash_tool', argumentsDelta: raw };
        yield { type: 'block-end', index: 0, block: { type: 'tool-call', id, name: 'calabash_tool', arguments: raw } };
        yield { type: 'finish', reason: { kind: 'tool-calls' } };
      } else {
        yield { type: 'block-start', index: 0, blockType: 'text' };
        yield { type: 'text-delta', index: 0, text: 'Draft ready. Open preview manually.' };
        yield { type: 'block-end', index: 0, block: { type: 'text', text: 'Draft ready. Open preview manually.' } };
        yield { type: 'finish', reason: { kind: 'stop' } };
      }
    }
  }
  const model = new Model(); ctx.llm.registerAdapter(['calabash-synthetic'], model);
  const agent = await ctx.agentLoop.create('loop-session', { provider: 'calabash-synthetic', model: 'synthetic' });
  const idle = new Promise((resolve, reject) => {
    const timer = setTimeout(() => { dispose(); reject(new Error('Synthetic Agent loop timed out')); }, 45000);
    const dispose = ctx.on('agent/status', ({ agent: subject, status }) => { if (subject === agent && status === 'idle') { clearTimeout(timer); dispose(); resolve(); } });
  });
  agent.followup(createUserMessage({ content: [{ type: 'text', text: '@ui:soft Create a synthetic counter office tool.' }], source: { kind: 'user' } }));
  await idle;
  const recorded = events.filter(item => item.session === 'loop-session').map(item => item.event);
  assert.equal(recorded.filter(event => event.type === 'tool/call').length, scriptedCalls);
  assert.equal(recorded.filter(event => event.type === 'tool/result').length, scriptedCalls);
  const stats = ctx.sessionProjections.snapshot(agent.session, ['sessionStats']).values.sessionStats;
  assert.equal(stats.steps, scriptedCalls + 1);
  assert.equal(stats.turns, 1);
  assert.ok(stats.toolMs >= 0 && stats.llmMs >= 0);
  const replayedStats = ctx.sessions.fork(agent.session, undefined, 'stats-replay');
  assert.deepEqual(ctx.sessionProjections.snapshot(replayedStats, ['sessionStats']).values.sessionStats, stats);
  assert.equal(model.requests.length, scriptedCalls + 1, 'The real loop must execute every scripted model tool call');
  assert.equal(JSON.parse(await ctx.calabashWorkspace.state('loop-session')).name, 'loop_counter');
  assert.deepEqual(JSON.parse(await ctx.calabashWorkspace.list()), []);
  const style = JSON.parse(await ctx.calabashWorkspace.agent('read_ui_preset', {}, 'loop-session', 'read-style', await ctx.calabashWorkspace.styleFor(agent.session)));
  assert.equal(style.id, 'soft');
  assert.equal(style.selected_by, 'mention');
  const meta = execFileSync(process.env.CALABASH_PYTHON, ['-c', "import json; from service.tools.work_drafts import snapshot; print(snapshot('demo','loop_counter')['files']['tool.json'])"], { cwd: root, env: process.env, encoding: 'utf8' });
  assert.equal(JSON.parse(meta).ui.preset, 'soft');
  const fork = ctx.sessions.fork(agent.session, undefined, 'style-replay');
  assert.equal(await ctx.calabashWorkspace.styleFor(fork), 'soft', 'A restored/forked session must reconstruct style from durable events');
  const nextIdle = new Promise((resolve, reject) => {
    const timer = setTimeout(() => { dispose(); reject(new Error('Follow-up timed out')); }, 15000);
    const dispose = ctx.on('agent/status', ({ agent: subject, status }) => { if (subject === agent && status === 'idle') { clearTimeout(timer); dispose(); resolve(); } });
  });
  agent.followup(createUserMessage({ content: [{ type: 'text', text: 'Fix the existing counter without changing its style.' }], source: { kind: 'user' } }));
  await nextIdle;
  assert.equal(await ctx.calabashWorkspace.styleFor(agent.session), null, 'A new user request must not inherit the previous @ selection');
  const inherited = JSON.parse(await ctx.calabashWorkspace.agent('read_ui_preset', {}, 'loop-session', 'inherit-style'));
  assert.equal(inherited.id, 'soft'); assert.equal(inherited.selected_by, 'snapshot');
  // Exercise the renderer's shipping chunk transfer through the real Host and stdio.
  const { inspectArchive, exportArchive } = await load('packages/client/calabash-workspace/lib/types/client/library-transfer.js');
  const library = async (operation, args) => ctx.calabashWorkspace.library(operation, JSON.stringify(args));
  const archiveBytes = execFileSync(process.env.CALABASH_PYTHON, ['-c', "import io,sys,json; from zipfile import ZipFile; from tests.test_tool_bundles import fixture; files=fixture('library_counter'); stream=io.BytesIO(); archive=ZipFile(stream,'w'); [archive.writestr(path,content) for path,content in files.items()]; archive.close(); sys.stdout.buffer.write(stream.getvalue())"], { cwd: root, env: process.env });
  const inspected = await inspectArchive(library, new File([archiveBytes], 'tool.zip'));
  assert.equal(inspected.manifest.name, 'library_counter'); assert.equal(inspected.revision, '');
  assert.deepEqual(JSON.parse(await ctx.calabashWorkspace.list()), [], 'Inspection does not install or run');
  await assert.rejects(() => library('import', { ticket: inspected.ticket, revision: '', confirmed: false }));
  await library('import', { ticket: inspected.ticket, revision: '', confirmed: true });
  const imported = JSON.parse(await ctx.calabashWorkspace.list()).find(value => value.name === 'library_counter');
  assert.ok(imported);
  const exported = await exportArchive(library, 'demo', 'library_counter');
  assert.ok(exported.blob.size > 0); assert.equal(exported.name, 'library_counter.zip');
  const reimport = await inspectArchive(library, new File([exported.blob], exported.name));
  assert.equal(reimport.revision, imported.revision);
  await library('discard', { ticket: reimport.ticket });
  await library('conversation', { project: 'demo', name: 'library_counter', session: 'library-chat' });
  assert.equal(JSON.parse(await library('conversation', { project: 'demo', name: 'library_counter', session: null })), 'library-chat');
  const chatInstructions = JSON.parse(await ctx.calabashWorkspace.agent('instructions', {}, 'library-chat', 'chat-context'));
  assert.deepEqual(chatInstructions.target, { project: 'demo', name: 'library_counter' });
  await assert.rejects(() => library('delete', { project: 'demo', name: 'library_counter', revision: imported.revision, confirmed: false }));
  await library('delete', { project: 'demo', name: 'library_counter', revision: imported.revision, confirmed: true });
  assert.deepEqual(JSON.parse(await ctx.calabashWorkspace.list()), []);
  console.log('PASS: shipping ZIP transfer → real Host/stdio → inspect → confirmed strict-build import → export → conversation binding → confirmed deletion');
  console.log('PASS: style projection replays from a fork and clears on a follow-up while the tool snapshot is preserved');
  console.log('PASS: DSH call/result correlation, native session statistics and replay; friendly result cards never interpolate source or errors');
  console.log('PASS: authoritative @ui:soft survives the complete Agent loop without a model-owned preset parameter');
  console.log('PASS: real DSH AgentLoop + synthetic model → bounded office discovery and authoring calls → draft + strict build, no real provider');
  console.log('PASS: DSH registry → bounded Agent call → stdio → real draft → strict build; no execution or publication');
} finally {
  await ctx?.fiber.dispose();
  for (const [name, value] of Object.entries(previous)) { if (value === undefined) delete process.env[name]; else process.env[name] = value; }
  await rm(home, { recursive: true, force: true });
}
