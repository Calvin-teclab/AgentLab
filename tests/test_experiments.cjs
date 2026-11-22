const test = require('node:test');
const assert = require('node:assert/strict');

for (const file of ['00-diagnosis', 'experiments', 'memory-evidence', '07-session']) {
  require('../frontend/src/' + file + '.js');
}

const benchmark = { id: 'average', result_check: 'score_mean', expected_tool_order: true,
  expected_tools: ['list_dir', 'read_file', 'calculator'] };
const input = { event: 'user_input', data: { enabled_tools: benchmark.expected_tools, score_reference: {mean: 82.6} } };
const calls = benchmark.expected_tools.map(tool => ({ event: 'tool_call', data: {tool} }));
const answer = n => ({ event: 'final_answer', data: { mean_claims: [n] } });
function judge(events, active = benchmark) {
  return AgentLabDiagnosis.run({timeline: events, activeBenchmark: () => active, enabledTools: [], truncate: String}).benchmark;
}

test('isolates the current turn and scores the answer independently of the path', () => {
  const wrong = judge([input, ...calls, answer(99)]);
  assert.equal(wrong.ok, false);
  assert.equal(wrong.path, '通过');
  assert.equal(wrong.outcome.status, '未通过');
  const short = judge([input, ...calls, answer(99), input, ...calls.slice(1), answer(82.6)]);
  assert.equal(short.outcome.status, '通过');
  assert.equal(short.path, '未通过');
  assert.equal(judge([input, ...calls, answer(82.6)]).ok, true);
  assert.equal(judge([{event:'user_input',data:{}}, ...calls, answer(82.6)]).ok, false);
});

test('requires a current matching write and all four labelled statistics', () => {
  const active = {...benchmark, result_check:'score_report'};
  const expected = {mean:82.6, total:413, min:68, max:92};
  const start = {event:'user_input', data:{...input.data, score_reference:expected}};
  const claims = Object.fromEntries(Object.entries(expected).map(([k,v]) => [k,[v]]));
  const final = {event:'final_answer', data:{report_evidence:{digest:'new',claims}}};
  const write = {event:'tool_result',data:{report_write_digest:'new'}};
  assert.equal(judge([start,...calls,final], active).ok, false);
  assert.equal(judge([start,...calls,{event:'tool_result',data:{report_write_digest:'old'}},final], active).ok, false);
  assert.equal(judge([start,...calls,write,final], active).ok, true);
  claims.min = [92];
  assert.equal(judge([start,...calls,write,final], active).outcome.status, '未通过');
});

test('comparison pins the original request, detects schema changes and ignores generated IDs', () => {
  const ctx = {...AgentLabExperiments.methods, mode:'lesson',currentLessonId:'lesson4',backendUrl:'original',
    customTools:[{name:'consult_weather',description:'weather',parameters:{type:'object'}}],
    enabledTools:['consult_weather'], manualTools:[], modelOverride:'', provider:'ark',
    systemPrompt:'original prompt',history:[],memory:[],maxSteps:4,runStartIndex:0,
    timeline:[{event:'llm_response',data:{model:'actual',provider:'ark'}},
      {event:'tool_call',step:1,data:{tool:'consult_weather',args:{city:'北京'},tool_call_id:'random'}},
      {event:'final_answer',step:2,data:{content:'带伞'}}]};
  const request = AgentLabExperiments.copy(AgentLabSession.buildRunRequest(ctx,'明天北京要带伞吗？'));
  ctx.runDraft = {request,scope:'lesson4',backend:'original'};
  AgentLabExperiments.finish(ctx);
  ctx.pinBaseline();
  ctx.customTools[0].description = '何时查天气';
  ctx.provider = 'other';
  ctx.history = [{role:'user',content:'later'}];
  assert.deepEqual(ctx.configChanges().map(x=>x.key), ['consult_weather.description']);
  ctx.maxSteps++;
  assert.equal(ctx.configChanges().length,2);
  ctx.runDraft = {request,scope:'lesson4',comparison:true};
  ctx.timeline[1].data.tool_call_id = 'other-id';
  AgentLabExperiments.finish(ctx);
  assert.equal(ctx.firstDifference(),-1);
  ctx.comparisonRun.rows[1].text = '回答 · 明天下雨';
  assert.equal(ctx.firstDifference(),1);
  assert.equal(ctx.baseline.model,'actual');
  assert.deepEqual(ctx.baseline.request.history,[]);
});

test('lesson evidence keeps model inputs across reset, even if both answers guess the name', () => {
  const ctx = {};
  const q = {role:'user',content:'我叫什么？'};
  const before = [{role:'system',content:'提示'}, {role:'user',content:'我叫张三'}, q];
  AgentLabMemoryEvidence.observe(ctx,before);
  before.push({role:'assistant',content:'张三'});
  assert.equal(ctx.nameEvidence.before.length,3);
  AgentLabMemoryEvidence.observe(ctx,[q]);
  assert.equal(ctx.nameEvidence.after,null);
  ctx.nameEvidence.cleared = true;
  AgentLabMemoryEvidence.observe(ctx,[{role:'system',content:'提示'},q]);
  assert.equal(ctx.nameEvidence.after.length,2);
  assert.equal(ctx.nameEvidence.after.some(m=>m.content.includes('张三')),false);
});

test('batch waits for manual returns and releases a cleared or stopped case', async () => {
  require('../frontend/src/03-scenario.js');
  globalThis.confirm = () => true;
  globalThis.localStorage = { setItem() {}, removeItem() {} };
  try {
    for (const action of ['continue', 'clear', 'stop']) {
      const ctx = {
        benchmarkCases: [benchmark], batchRunning: false, maxSteps: 5,
        resetSession() { AgentLabSession.resetSession(this); },
        updateChart() {}, totalTokens() { return 0; },
        async send() {
          this.timeline = [input, ...calls];
          this.pendingManualTool = {tool_call_id:'1'};
        },
        runDiagnosis() {
          return AgentLabDiagnosis.run({...this, activeBenchmark: () => benchmark});
        },
      };
      const batch = AgentLabScenario.runAllBenchmarks(ctx);
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(typeof ctx.batchResume, 'function');
      assert.deepEqual(ctx.batchResults, {});
      if (action === 'continue') {
        ctx.timeline.push(answer(82.6));
        ctx.pendingManualTool = null;
        ctx.batchResume();
      } else if (action === 'clear') ctx.resetSession();
      else AgentLabScenario.stopBatchRun(ctx);
      await batch;
      assert.equal(ctx.batchRunning, false);
      if (action === 'continue') assert.equal(ctx.batchResults.average.ok, true);
      if (action === 'clear') assert.equal(ctx.batchResults.average.incomplete, true);
      if (action === 'stop') assert.deepEqual(ctx.batchResults, {});
    }
  } finally {
    delete globalThis.confirm;
    delete globalThis.localStorage;
  }
});

test('restored answers cannot turn a second guess into a first-use success', () => {
  const ctx = {...AgentLabExperiments.methods, comparisonRun:{complete:true}, evidenceChoice:'1',
    firstDifference:()=>0, firstUseTrial:{eligible:true, compared:true, identified:false}};
  ctx.recordEvidence();
  assert.equal(ctx.comparisonRun.firstChoice, '1');
  const restored = {...ctx, comparisonRun: JSON.parse(JSON.stringify(ctx.comparisonRun)), evidenceChoice:'0'};
  restored.recordEvidence();
  assert.equal(restored.firstUseTrial.identified, false);
  restored.comparisonRun = {complete:true};
  restored.recordEvidence();
  assert.equal(restored.firstUseTrial.identified, true);
});
