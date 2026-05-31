(function (root) {
  function activeBenchmark(ctx) {
    return (ctx.benchmarkCases || []).find(b => b.id === ctx.activeBenchmarkId) || null;
  }

  function activeMassTemplate(ctx) {
    return (ctx.massTemplates || []).find(t => t.id === ctx.activeMassTemplateId) || null;
  }

  function currentLesson(ctx) {
    return (ctx.lessons || []).find(l => l.id === ctx.currentLessonId) || null;
  }

  function lockedConfig(ctx) {
    return ctx.currentLesson()?.locked_config || {};
  }

  function lockedFlag(ctx, key) {
    if (ctx.mode !== 'lesson') return undefined;
    return lockedConfig(ctx)?.[key];
  }

  function toolEnableLocked(ctx) {
    return ctx.mode === 'lesson' && Array.isArray(lockedConfig(ctx)?.enabled_tools);
  }

  function tabVisible(ctx, tab) {
    if (ctx.mode !== 'lesson') return true;
    if (tab === 'tools') return lockedFlag(ctx, 'tool_panel_visible') !== false;
    if (tab === 'eval') return false;
    return true;
  }

  function lessonLockSummary(ctx) {
    if (ctx.mode !== 'lesson') return [];
    const c = lockedConfig(ctx) || {};
    const items = [];
    if (c.system_prompt_editable === false) items.push('System Prompt');
    if (Array.isArray(c.enabled_tools)) items.push('工具集合');
    if (c.custom_tools_visible === false) items.push('工具实验室');
    if (c.max_steps_visible === false) items.push('MAX_STEPS');
    return items;
  }

  function setMode(ctx, m) {
    if (m === ctx.mode) return;
    ctx.mode = m;
    localStorage.setItem('agent_pg_mode', m);
    if (m === 'lesson' && !ctx.currentLessonId && ctx.lessons.length) {
      enterLesson(ctx, ctx.lessons[0].id);
    } else if (m === 'lesson') {
      if (!tabVisible(ctx, ctx.leftTab)) ctx.leftTab = 'config';
    }
  }

  function enterLesson(ctx, id) {
    const lesson = (ctx.lessons || []).find(l => l.id === id);
    if (!lesson) return;
    ctx.currentLessonId = id;
    ctx.lessonStepIdx = 0;
    ctx.lessonComplete = false;
    ctx.showLessonExplanation = false;
    ctx.activeMassTemplateId = null;
    ctx.activeBenchmarkId = null;
    ctx.preScenarioSnapshot = null;
    ctx.postScenarioFingerprint = null;
    ctx.dismissNotification();
    localStorage.setItem('agent_pg_lesson', id);

    const p = lesson.preset_config || {};
    if (typeof p.system_prompt === 'string') ctx.systemPrompt = p.system_prompt;
    if (Array.isArray(p.enabled_tools)) ctx.enabledTools = p.enabled_tools.slice();
    if (Array.isArray(p.custom_tools)) ctx.customTools = p.custom_tools.slice();
    if (Array.isArray(p.manual_tools)) ctx.manualTools = p.manual_tools.slice();
    if (typeof p.max_steps === 'number') ctx.maxSteps = p.max_steps;

    if (!tabVisible(ctx, ctx.leftTab)) ctx.leftTab = 'config';
    ctx.resetSession();
  }

  function nextLessonStep(ctx) {
    const lesson = ctx.currentLesson();
    if (!lesson) return;
    if (ctx.lessonStepIdx < (lesson.task_steps?.length || 0) - 1) {
      ctx.lessonStepIdx += 1;
    } else {
      finishLesson(ctx);
    }
  }

  function finishLesson(ctx) {
    if (ctx.currentLessonId && !ctx.completedLessons.includes(ctx.currentLessonId)) {
      ctx.completedLessons.push(ctx.currentLessonId);
      try {
        localStorage.setItem('agent_pg_completed', JSON.stringify(ctx.completedLessons));
      } catch (e) {}
    }
    ctx.lessonComplete = true;
  }

  function resetLessonProgress(ctx) {
    if (!confirm('清空全部课程完成记录?(只影响本机进度,不删任何课程内容)')) return;
    ctx.completedLessons = [];
    try { localStorage.removeItem('agent_pg_completed'); } catch (e) {}
    ctx.lessonComplete = false;
  }

  function goToNextLesson(ctx) {
    const idx = (ctx.lessons || []).findIndex(l => l.id === ctx.currentLessonId);
    const next = (ctx.lessons || [])[idx + 1];
    if (next) {
      enterLesson(ctx, next.id);
    } else {
      setMode(ctx, 'free');
    }
  }

  function loadBenchmarkCase(ctx, b) {
    if (!b) return;
    ctx.leftTab = 'eval';
    ctx.activeBenchmarkId = ctx.activeBenchmarkId === b.id ? null : b.id;
    ctx.inspectorView = 'diagnosis';
  }

  function useBenchmarkInput(ctx, b) {
    if (!b) return;
    ctx.userInput = b.user_input;
  }

  async function runAllBenchmarks(ctx) {
    if (ctx.isRunning || ctx.batchRunning) return;
    if (!ctx.benchmarkCases.length) return;
    if (!confirm(`将依次跑 ${ctx.benchmarkCases.length} 条 benchmark cases。每条都会真实调用模型,产生 token 成本。继续?`)) return;

    ctx.batchRunning = true;
    ctx.batchResults = {};
    const savedMaxSteps = ctx.maxSteps;

    try {
      for (let i = 0; i < ctx.benchmarkCases.length; i++) {
        if (!ctx.batchRunning) break;
        ctx.batchCursor = i;
        const c = ctx.benchmarkCases[i];

        ctx.resetSession();
        ctx.activeBenchmarkId = c.id;
        ctx.userInput = c.user_input;
        ctx.maxSteps = c.max_steps || savedMaxSteps;

        const t0 = Date.now();
        try {
          await ctx.send();
        } catch (e) {
          console.warn('[batch] send threw:', e);
        }

        ctx.activeBenchmarkId = c.id;
        const diag = ctx.runDiagnosis();
        ctx.batchResults[c.id] = {
          case_id: c.id,
          title: c.title,
          ok: diag.benchmark?.ok || false,
          tools: diag.tools,
          signals: diag.signals,
          assertions: diag.assertions || [],
          tokens: ctx.totalTokens(),
          duration_ms: Date.now() - t0,
          timestamp: new Date().toISOString(),
        };
      }
    } finally {
      ctx.maxSteps = savedMaxSteps;
      ctx.batchRunning = false;
      ctx.batchCursor = -1;
      ctx.activeBenchmarkId = null;
      try { localStorage.setItem('agent_pg_batch_results', JSON.stringify(ctx.batchResults)); } catch(e) {}
    }
  }

  function stopBatchRun(ctx) {
    ctx.batchRunning = false;
    if (ctx.isRunning) ctx.cancelRun();
  }

  function batchSummary(ctx) {
    const ids = Object.keys(ctx.batchResults || {});
    if (!ids.length) return null;
    const passed = ids.filter(id => ctx.batchResults[id].ok).length;
    return { passed, total: ids.length };
  }

  root.AgentLabScenario = {
    activeBenchmark,
    activeMassTemplate,
    currentLesson,
    lockedConfig,
    lockedFlag,
    toolEnableLocked,
    tabVisible,
    lessonLockSummary,
    setMode,
    enterLesson,
    nextLessonStep,
    finishLesson,
    resetLessonProgress,
    goToNextLesson,
    loadBenchmarkCase,
    useBenchmarkInput,
    runAllBenchmarks,
    stopBatchRun,
    batchSummary,
  };
})(typeof window !== 'undefined' ? window : globalThis);
