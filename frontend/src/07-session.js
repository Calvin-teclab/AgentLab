(function (root) {
  function buildRunRequest(ctx, input) {
    return {
      user_input: input,
      system_prompt: ctx.systemPrompt,
      enabled_tools: ctx.enabledTools,
      custom_tools: ctx.customTools,
      manual_tools: ctx.manualTools,
      max_steps: ctx.maxSteps,
      history: ctx.history,
      provider: ctx.provider || null,
      model_override: ctx.modelOverride.trim() || null,
    };
  }

  function buildContinueRequest(ctx, toolCall, result) {
    return {
      tool_call_id: toolCall.tool_call_id,
      tool_result: result,
      enabled_tools: ctx.enabledTools,
      custom_tools: ctx.customTools,
      manual_tools: ctx.manualTools,
      max_steps: ctx.maxSteps,
      history: ctx.history,
      provider: ctx.provider || null,
      model_override: ctx.modelOverride.trim() || null,
    };
  }

  async function send(ctx) {
    const input = ctx.userInput.trim();
    if (!input || ctx.isRunning || ctx.pendingManualTool) return;

    const preRunHistoryLen = ctx.history.length;
    ctx.isRunning = true;
    ctx.currentStep = 0;
    ctx.userInput = '';
    ctx.pendingManualTool = null;
    ctx.manualToolResult = '';
    ctx.pendingToolRollbackHistoryLen = preRunHistoryLen;
    ctx.abortController = new AbortController();

    try {
      const resp = await fetch(ctx.backendUrl + '/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildRunRequest(ctx, input)),
        signal: ctx.abortController.signal,
      });

      await ctx.consumeEventStream(resp);
    } catch (e) {
      if (e.name === 'AbortError') {
        ctx.history = ctx.history.slice(0, preRunHistoryLen);
        ctx.pendingManualTool = null;
        ctx.manualToolResult = '';
        ctx.pendingToolRollbackHistoryLen = null;
      } else {
        ctx.timeline.push({ event: 'error', data: { error: String(e) }, _open: true });
      }
    } finally {
      ctx.isRunning = false;
      ctx.abortController = null;
      ctx.scrollChatBottom();
      if (ctx.activeBenchmarkId && !ctx.batchRunning) {
        pushRunHistory(ctx, ctx.activeBenchmarkId);
      }
    }
  }

  function pushRunHistory(ctx, caseId) {
    const isTerminal = ctx.timeline.some(e => ['final_answer', 'max_steps', 'error'].includes(e.event));
    if (!isTerminal) return;
    const diag = ctx.runDiagnosis();
    const entry = {
      ok: !!diag.benchmark?.ok,
      tools: diag.tools,
      tokens: ctx.totalTokens(),
      timestamp: new Date().toISOString(),
      assertions_failed: (diag.assertions || [])
        .filter(a => !a.ok && a.severity === 'hard')
        .map(a => a.name),
    };
    if (!ctx.runHistory[caseId]) ctx.runHistory[caseId] = [];
    ctx.runHistory[caseId].push(entry);
    while (ctx.runHistory[caseId].length > 5) ctx.runHistory[caseId].shift();
    try { localStorage.setItem('agent_pg_run_history', JSON.stringify(ctx.runHistory)); } catch (e) {}
  }

  async function submitManualToolResult(ctx) {
    if (!ctx.pendingManualTool || ctx.isRunning || !ctx.manualToolResult.trim()) return;

    ctx.isRunning = true;
    ctx.abortController = new AbortController();
    const toolCall = ctx.pendingManualTool;
    const result = ctx.manualToolResult;
    const preContinueHistoryLen = ctx.history.length;
    ctx.pendingManualTool = null;
    ctx.manualToolResult = '';

    try {
      const resp = await fetch(ctx.backendUrl + '/api/continue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildContinueRequest(ctx, toolCall, result)),
        signal: ctx.abortController.signal,
      });
      await ctx.consumeEventStream(resp);
    } catch (e) {
      ctx.history = ctx.history.slice(0, preContinueHistoryLen);
      ctx.pendingManualTool = toolCall;
      ctx.manualToolResult = result;
      if (e.name !== 'AbortError') {
        ctx.timeline.push({ event: 'error', data: { error: String(e) }, _open: true });
      }
    } finally {
      ctx.isRunning = false;
      ctx.abortController = null;
      ctx.scrollChatBottom();
      if (ctx.activeBenchmarkId && !ctx.batchRunning) {
        pushRunHistory(ctx, ctx.activeBenchmarkId);
      }
    }
  }

  function discardPendingToolCall(ctx) {
    if (ctx.pendingToolRollbackHistoryLen !== null) {
      ctx.history = ctx.history.slice(0, ctx.pendingToolRollbackHistoryLen);
    }
    ctx.pendingManualTool = null;
    ctx.manualToolResult = '';
    ctx.pendingToolRollbackHistoryLen = null;
  }

  function cancelRun(ctx) {
    if (ctx.abortController) ctx.abortController.abort();
  }

  function resetSession(ctx) {
    ctx.history = [];
    ctx.timeline = [];
    ctx.tokenData = [];
    ctx.currentStep = 0;
    ctx.pendingManualTool = null;
    ctx.manualToolResult = '';
    ctx.pendingToolRollbackHistoryLen = null;
    ctx.updateChart();
    localStorage.removeItem('agent_pg_history');
    localStorage.removeItem('agent_pg_timeline');
    localStorage.removeItem('agent_pg_tokendata');
  }

  function applySystemPromptPreset(ctx, preset) {
    if (!preset) return;
    if (ctx.systemPrompt === preset.prompt) return;

    const isCurrentAPreset = ctx.systemPromptPresets.some(p => p.prompt === ctx.systemPrompt);
    if (!isCurrentAPreset) {
      const scenarioTitle = ctx.activeMassTemplate()?.title;
      const source = scenarioTitle
        ? `当前 system prompt 来自场景"${scenarioTitle}"`
        : '当前 system prompt 是你自定义的内容';
      const ok = window.confirm(`${source},点击"载入${preset.label}"会把它覆盖掉(场景的工具配置不会动,需要的话再点 pill 的 ✕)。\n\n确定继续?`);
      if (!ok) return;
    }

    ctx.systemPrompt = preset.prompt;
  }

  function scenarioStateFingerprint(ctx) {
    return JSON.stringify({
      systemPrompt: ctx.systemPrompt,
      customTools: ctx.customTools,
      enabledTools: ctx.enabledTools.slice().sort(),
      manualTools: ctx.manualTools.slice().sort(),
      maxSteps: ctx.maxSteps,
    });
  }

  function showNotification(ctx, { title, detail, undoSnapshot }) {
    if (ctx.notification?.timer) clearTimeout(ctx.notification.timer);
    ctx.notification = { title, detail, undoSnapshot, timer: null };
    ctx.notification.timer = setTimeout(() => { ctx.notification = null; }, 12000);
  }

  function dismissNotification(ctx) {
    if (ctx.notification?.timer) clearTimeout(ctx.notification.timer);
    ctx.notification = null;
  }

  function applyMassTemplate(ctx, tpl) {
    if (!tpl) return;
    const previousState = {
      systemPrompt: ctx.systemPrompt,
      customTools: JSON.parse(JSON.stringify(ctx.customTools)),
      enabledTools: ctx.enabledTools.slice(),
      manualTools: ctx.manualTools.slice(),
      maxSteps: ctx.maxSteps,
      userInput: ctx.userInput,
      activeMassTemplateId: ctx.activeMassTemplateId,
      activeBenchmarkId: ctx.activeBenchmarkId,
      inspectorView: ctx.inspectorView,
    };
    if (!ctx.activeMassTemplateId) {
      ctx.preScenarioSnapshot = previousState;
    }

    ctx.activeMassTemplateId = tpl.id;
    ctx.activeBenchmarkId = null;
    ctx.systemPrompt = tpl.system_prompt || ctx.systemPrompt;
    ctx.customTools = (tpl.custom_tools || []).map(t => JSON.parse(JSON.stringify(t)));
    ctx.enabledTools = (tpl.enabled_tools || []).slice();
    ctx.manualTools = (tpl.manual_tools || []).slice();
    ctx.maxSteps = Math.max(ctx.maxSteps, 8);
    resetSession(ctx);
    const firstPrompt = tpl.example_prompts?.[0];
    if (firstPrompt) ctx.userInput = firstPrompt;
    ctx.inspectorView = 'diagnosis';

    ctx.postScenarioFingerprint = scenarioStateFingerprint(ctx);

    const changed = [];
    if (tpl.system_prompt && tpl.system_prompt !== previousState.systemPrompt) changed.push('system prompt');
    if ((tpl.custom_tools?.length || 0) > 0) changed.push(`${tpl.custom_tools.length} mock 工具`);
    if ((tpl.enabled_tools?.length || 0) > 0) changed.push(`勾选工具 ${tpl.enabled_tools.length} 项`);
    if ((tpl.manual_tools?.length || 0) > 0) changed.push(`人工模式 ${tpl.manual_tools.length} 项`);
    showNotification(ctx, {
      title: `已加载场景: ${tpl.title}`,
      detail: changed.length ? `覆盖了 ${changed.join(' + ')}` : '配置已就绪',
      undoSnapshot: previousState,
    });
  }

  function undoMassTemplate(ctx) {
    const s = ctx.notification?.undoSnapshot;
    if (!s) return;
    ctx.systemPrompt = s.systemPrompt;
    ctx.customTools = JSON.parse(JSON.stringify(s.customTools));
    ctx.enabledTools = s.enabledTools.slice();
    ctx.manualTools = s.manualTools.slice();
    ctx.maxSteps = s.maxSteps;
    ctx.userInput = s.userInput;
    ctx.activeMassTemplateId = s.activeMassTemplateId;
    ctx.activeBenchmarkId = s.activeBenchmarkId;
    ctx.inspectorView = s.inspectorView;
    ctx.preScenarioSnapshot = null;
    ctx.postScenarioFingerprint = null;
    dismissNotification(ctx);
  }

  function clearMassScenario(ctx) {
    ctx.scenarioMenuOpen = false;
    const snap = ctx.preScenarioSnapshot;
    if (!snap) {
      ctx.activeMassTemplateId = null;
      return;
    }
    const touched = ctx.postScenarioFingerprint && scenarioStateFingerprint(ctx) !== ctx.postScenarioFingerprint;
    if (touched) {
      const ok = window.confirm(
        '你在场景加载之后改过配置。\n\n确定 = 回滚到加载场景前的状态(会丢掉你的修改)\n取消 = 仅取消场景标记,保留你当前的配置'
      );
      if (!ok) {
        ctx.activeMassTemplateId = null;
        ctx.preScenarioSnapshot = null;
        ctx.postScenarioFingerprint = null;
        return;
      }
    }
    ctx.systemPrompt = snap.systemPrompt;
    ctx.customTools = JSON.parse(JSON.stringify(snap.customTools));
    ctx.enabledTools = snap.enabledTools.slice();
    ctx.manualTools = snap.manualTools.slice();
    ctx.maxSteps = snap.maxSteps;
    ctx.userInput = snap.userInput;
    ctx.activeMassTemplateId = null;
    ctx.activeBenchmarkId = snap.activeBenchmarkId;
    ctx.inspectorView = snap.inspectorView;
    ctx.preScenarioSnapshot = null;
    ctx.postScenarioFingerprint = null;
    dismissNotification(ctx);
  }

  root.AgentLabSession = {
    send,
    pushRunHistory,
    submitManualToolResult,
    discardPendingToolCall,
    cancelRun,
    resetSession,
    applySystemPromptPreset,
    applyMassTemplate,
    scenarioStateFingerprint,
    showNotification,
    dismissNotification,
    undoMassTemplate,
    clearMassScenario,
  };
})(typeof window !== 'undefined' ? window : globalThis);
