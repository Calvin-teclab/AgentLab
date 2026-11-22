(function (root) {
  const copy = value => JSON.parse(JSON.stringify(value));
  const fields = ['system_prompt', 'custom_tools', 'enabled_tools', 'manual_tools', 'max_steps'];
  const labels = { system_prompt: '系统提示词', enabled_tools: '启用工具', manual_tools: '人工工具', max_steps: '步数上限' };

  function scope(ctx) {
    return ctx.mode === 'lesson' ? ctx.currentLessonId : 'free/' + (ctx.activeBenchmarkId || '');
  }

  function configValues(request) {
    const values = {};
    for (const key of fields) {
      if (key !== 'custom_tools') {
        const value = request[key];
        values[labels[key]] = Array.isArray(value) ? value.join(', ') : value;
      }
    }
    function visit(path, value) {
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        for (const key of Object.keys(value).sort()) visit(path + '.' + key, value[key]);
      } else {
        values[path] = Array.isArray(value) ? JSON.stringify(value) : value;
      }
    }
    for (const tool of request.custom_tools) visit(tool.name, tool);
    return values;
  }

  function differences(base, next) {
    const a = configValues(base), b = configValues(next);
    return [...new Set([...Object.keys(a), ...Object.keys(b)])]
      .filter(key => a[key] !== b[key])
      .map(key => ({ key, before: a[key] ?? '未设置', after: b[key] ?? '未设置' }));
  }

  function stableJson(value) {
    return JSON.stringify(value, (_, v) => v && typeof v === 'object' && !Array.isArray(v)
      ? Object.fromEntries(Object.keys(v).sort().map(k => [k, v[k]])) : v);
  }

  function traceRows(events) {
    const rows = [];
    for (const { event, data, step } of events) {
      let text;
      if (event === 'tool_call' || event === 'tool_input_required') {
        text = (event === 'tool_input_required' ? '请求人工执行 ' : '调用 ') + data.tool + ' ' + stableJson(data.args ?? data.raw_args);
      } else if (event === 'tool_result') text = '返回 ' + data.tool + ' · ' + data.result;
      else if (event === 'final_answer') text = '回答 · ' + data.content;
      else if (event === 'max_steps') text = '达到步数上限';
      else if (event === 'error') text = '运行错误 · ' + data.error;
      else if (event === 'llm_response' && data.tool_calls?.length && data.content) text = '模型说明 · ' + data.content;
      else continue;
      rows.push({ step: step || 1, text });
    }
    return rows;
  }

  function finish(ctx) {
    const draft = ctx.runDraft;
    if (!draft || draft.scope !== scope(ctx) || ctx.batchRunning || ctx.pendingManualTool) return;
    const events = ctx.timeline.slice(ctx.runStartIndex);
    const last = events[events.length - 1];
    if (!['final_answer', 'max_steps', 'error'].includes(last?.event)) return;
    const model = events.find(e => e.event === 'llm_response')?.data;
    const record = {
      scope: draft.scope, request: draft.request, backend: draft.backend,
      model: model?.model || draft.request.model_override,
      provider: model?.provider || draft.request.provider,
      verdict: draft.request.benchmark_id && draft.request.benchmark_id === ctx.activeBenchmarkId ? ctx.runDiagnosis().benchmark : null,
      rows: traceRows(events), complete: last.event !== 'error' && !!model,
    };
    ctx.lastExperiment = record;
    if (draft.comparison) {
      ctx.comparisonRun = record;
      if (record.complete && ctx.firstUseTrial?.eligible && !ctx.firstUseTrial.ended) {
        ctx.firstUseTrial = { ...ctx.firstUseTrial, compared: true };
      }
      ctx.evidenceChoice = '';
      ctx.inspectorView = 'compare';
    }
    ctx.runDraft = null;
  }

  function replayRequest(ctx) {
    const base = ctx.baseline.request;
    const request = copy(base);
    const current = root.AgentLabSession.buildRunRequest(ctx, base.user_input);
    for (const field of fields) request[field] = copy(current[field]);
    // History overrides system_prompt on the server. Apply an intentional prompt edit
    // to that same system message while preserving all other initial messages.
    if (request.history[0]?.role === 'system') request.history[0].content = request.system_prompt;
    request.model_override = ctx.baseline.model;
    request.provider = ctx.baseline.provider;
    return request;
  }

  const methods = {
    compareAvailable() { return this.mode === 'free' || this.currentLessonId === 'lesson4'; },
    visibleBase() { return this.baseline?.scope === scope(this) ? this.baseline : null; },
    canPin() {
      return this.lastExperiment?.scope === scope(this) && this.lastExperiment.complete &&
        !this.isRunning && !this.batchRunning && !this.pendingManualTool;
    },
    pinBaseline() {
      if (!this.canPin()) return;
      this.baseline = copy(this.lastExperiment);
      this.comparisonRun = null;
      this.evidenceChoice = '';
      this.inspectorView = 'compare';
    },
    configChanges() {
      return this.visibleBase() ? differences(this.baseline.request, root.AgentLabSession.buildRunRequest(this, this.baseline.request.user_input)) : [];
    },
    async rerunComparison() {
      if (!this.visibleBase() || this.isRunning || this.batchRunning || this.pendingManualTool || this.configChanges().length > 1) return;
      const request = replayRequest(this);
      this.comparisonRun = null;
      this.resetSession();
      this.history = copy(request.history);
      this.inspectorView = 'compare';
      await root.AgentLabSession.send(this, request, this.baseline.backend);
    },
    comparedChanges() {
      return this.visibleBase() && this.comparisonRun ? differences(this.baseline.request, this.comparisonRun.request) : [];
    },
    comparisonRows() {
      if (!this.visibleBase()) return [];
      const a = this.baseline.rows, b = this.comparisonRun?.rows || [];
      return Array.from({ length: Math.max(a.length, b.length) }, (_, i) => ({
        index: i, a: a[i], b: b[i],
        different: !!this.comparisonRun && (a[i]?.text !== b[i]?.text || a[i]?.step !== b[i]?.step),
      }));
    },
    firstDifference() { return this.comparisonRows().findIndex(row => row.different); },
    evidenceCorrect() {
      return this.evidenceChoice !== '' && Number(this.evidenceChoice) === this.firstDifference();
    },
    recordEvidence() {
      if (!this.comparisonRun?.complete || this.comparisonRun.firstChoice !== undefined || this.evidenceChoice === '') return;
      this.comparisonRun = { ...this.comparisonRun, firstChoice: this.evidenceChoice };
      if (!this.evidenceCorrect()) return;
      // One local first-use observation per browser. No prompts or transcripts in the metric.
      const trial = this.firstUseTrial;
      if (trial?.eligible && !trial.ended && !trial.identified) {
        this.firstUseTrial = { ...trial, compared: true, identified: true };
      }
    },
  };

  root.AgentLabExperiments = { methods, scope, copy, finish };
})(typeof window !== 'undefined' ? window : globalThis);
