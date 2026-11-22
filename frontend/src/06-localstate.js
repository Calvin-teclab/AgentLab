(function (root) {
  function restore(ctx) {
    const queryBackend = new URLSearchParams(window.location.search).get('backend');
    const savedBackend = localStorage.getItem('agent_pg_backend');
    const runtimeBackend = window.AgentLabRuntimeConfig?.backendUrl;
    const savedModel = localStorage.getItem('agent_pg_model');
    const savedProvider = localStorage.getItem('agent_pg_provider');
    const savedTools = localStorage.getItem('agent_pg_custom_tools');
    const savedManualTools = localStorage.getItem('agent_pg_manual_tools');
    const savedMemory = localStorage.getItem('agent_pg_memory');
    const savedMemoryInject = localStorage.getItem('agent_pg_memory_inject');

    if (queryBackend) ctx.backendUrl = queryBackend;
    else if (runtimeBackend) ctx.backendUrl = runtimeBackend;
    else if (savedBackend) ctx.backendUrl = savedBackend;
    if (savedModel) ctx.modelOverride = savedModel;
    if (savedProvider) ctx.provider = savedProvider;
    if (savedTools) {
      try { ctx.customTools = JSON.parse(savedTools); } catch (e) { ctx.customTools = []; }
    }
    if (savedManualTools) {
      try { ctx.manualTools = JSON.parse(savedManualTools); } catch (e) { ctx.manualTools = []; }
    }
    if (savedMemory) {
      try { ctx.memory = JSON.parse(savedMemory); } catch (e) { ctx.memory = []; }
    }
    // 注入开关是全局偏好,跨会话保留;关卡进入时 enterLesson 会按 preset 覆盖它。
    if (savedMemoryInject != null) ctx.memoryInject = savedMemoryInject === 'true';

    try {
      const h = localStorage.getItem('agent_pg_history');
      const tl = localStorage.getItem('agent_pg_timeline');
      const td = localStorage.getItem('agent_pg_tokendata');
      if (h) ctx.history = JSON.parse(h);
      if (tl) {
        ctx.timeline = JSON.parse(tl).map((e, i, a) => ({
          ...e,
          _open: i === a.length - 1,
          _id: (typeof e._id === 'number') ? e._id : ctx._eventCounter++,
        }));
        const maxId = ctx.timeline.reduce((m, e) => Math.max(m, e._id || 0), 0);
        if (maxId >= ctx._eventCounter) ctx._eventCounter = maxId + 1;
      }
      if (td) ctx.tokenData = JSON.parse(td);
    } catch (e) {}

    try {
      const br = localStorage.getItem('agent_pg_batch_results');
      if (br) ctx.batchResults = JSON.parse(br);
    } catch (e) {
      ctx.batchResults = {};
    }

    try {
      const rh = localStorage.getItem('agent_pg_run_history');
      if (rh) ctx.runHistory = JSON.parse(rh);
    } catch (e) {
      ctx.runHistory = {};
    }

    for (const key of ['baseline', 'comparisonRun', 'nameEvidence', 'firstUseTrial']) {
      try { ctx[key] = JSON.parse(localStorage.getItem('agent_pg_' + key)) || null; } catch {}
    }
    ctx.evidenceChoice = ctx.comparisonRun?.firstChoice ?? '';
    const savedMode = localStorage.getItem('agent_pg_mode');
    const savedLesson = localStorage.getItem('agent_pg_lesson');
    if (!ctx.firstUseTrial) {
      const eligible = !savedMode && !savedLesson && !ctx.history.length;
      ctx.firstUseTrial = { eligible, compared: false, identified: false, ended: false };
      sessionStorage.setItem('agent_pg_first_visit', '1');
    } else if (!sessionStorage.getItem('agent_pg_first_visit')) {
      ctx.firstUseTrial.ended = true;
    }
    try { localStorage.setItem('agent_pg_firstUseTrial', JSON.stringify(ctx.firstUseTrial)); } catch {}
    try {
      const c = localStorage.getItem('agent_pg_completed');
      if (c) ctx.completedLessons = JSON.parse(c) || [];
    } catch (e) {}

    ctx.mode = savedMode || (savedLesson || !ctx.history.length ? 'lesson' : 'free');

    return { savedLesson };
  }

  function bindPersistence(ctx) {
    window.addEventListener('pagehide', () => {
      const editor = {
        mode: ctx.mode, lesson: ctx.currentLessonId, benchmark: ctx.activeBenchmarkId,
        prompt: ctx.systemPrompt, tools: ctx.enabledTools, custom: ctx.customTools,
        manual: ctx.manualTools, max: ctx.maxSteps, memoryInject: ctx.memoryInject,
        step: ctx.lessonStepIdx, complete: ctx.lessonComplete,
      };
      try { localStorage.setItem('agent_pg_editor', JSON.stringify(editor)); } catch {}
    });
    for (const key of ['baseline', 'comparisonRun', 'nameEvidence', 'firstUseTrial']) {
      ctx.$watch(key, value => {
        try { localStorage.setItem('agent_pg_' + key, JSON.stringify(value)); } catch {}
      });
    }
    ctx.$watch('backendUrl', v => localStorage.setItem('agent_pg_backend', v));
    ctx.$watch('modelOverride', v => localStorage.setItem('agent_pg_model', v));
    ctx.$watch('provider', v => localStorage.setItem('agent_pg_provider', v || ''));
    ctx.$watch('manualTools', v => {
      try { localStorage.setItem('agent_pg_manual_tools', JSON.stringify(v)); } catch (e) {}
    });
    ctx.$watch('customTools', v => {
      try { localStorage.setItem('agent_pg_custom_tools', JSON.stringify(v)); } catch (e) {}
    });
    // 记忆持久化:刻意独立于 history/timeline(那几个 key 会被 resetSession 删,记忆不会)。
    ctx.$watch('memory', v => {
      try { localStorage.setItem('agent_pg_memory', JSON.stringify(v)); } catch (e) {}
    });
    ctx.$watch('memoryInject', v => localStorage.setItem('agent_pg_memory_inject', v ? 'true' : 'false'));
    ctx.$watch('history', v => {
      try { localStorage.setItem('agent_pg_history', JSON.stringify(v)); } catch (e) {}
    });
    ctx.$watch('timeline', v => {
      try { localStorage.setItem('agent_pg_timeline', JSON.stringify(v)); } catch (e) {}
    });
    ctx.$watch('tokenData', v => {
      try { localStorage.setItem('agent_pg_tokendata', JSON.stringify(v)); } catch (e) {}
    });
    ctx.$watch('tokenData', () => {
      if (typeof ctx.updateChart === 'function') ctx.updateChart();
    });
  }

  function persistTokenData(ctx) {
    try {
      localStorage.setItem('agent_pg_tokendata', JSON.stringify(ctx.tokenData || []));
    } catch (e) {}
  }

  function finalizeRestore(ctx, savedLesson) {
    if (ctx.mode === 'lesson' && ctx.lessons.length) {
      const target = ctx.lessons.find(l => l.id === savedLesson) || ctx.lessons[0];
      if (!ctx.history.length) {
        const evidence = ctx.nameEvidence;
        ctx.enterLesson(target.id);
        if (target.id === 'lesson1') ctx.nameEvidence = evidence;
      } else {
        ctx.currentLessonId = target.id;
        const preset = target.preset_config;
        ctx.systemPrompt = preset.system_prompt;
        ctx.enabledTools = preset.enabled_tools.slice();
        ctx.maxSteps = preset.max_steps;
        ctx.memoryInject = !!preset.memory_inject;
      }
    }
    let editor;
    try { editor = JSON.parse(localStorage.getItem('agent_pg_editor')); } catch {}
    if (!editor || editor.mode !== ctx.mode || (ctx.mode === 'lesson' && editor.lesson !== ctx.currentLessonId)) return;
    ctx.systemPrompt = editor.prompt;
    ctx.enabledTools = editor.tools;
    ctx.customTools = editor.custom;
    ctx.manualTools = editor.manual;
    ctx.maxSteps = editor.max;
    ctx.memoryInject = editor.memoryInject;
    ctx.activeBenchmarkId = editor.benchmark;
    ctx.lessonStepIdx = editor.step;
    ctx.lessonComplete = editor.complete;
  }

  root.AgentLabLocalState = {
    restore,
    bindPersistence,
    finalizeRestore,
    persistTokenData,
  };
})(typeof window !== 'undefined' ? window : globalThis);
