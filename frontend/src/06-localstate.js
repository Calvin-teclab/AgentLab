(function (root) {
  function restore(ctx) {
    const queryBackend = new URLSearchParams(window.location.search).get('backend');
    const savedBackend = localStorage.getItem('agent_pg_backend');
    const runtimeBackend = window.AgentLabRuntimeConfig?.backendUrl;
    const savedModel = localStorage.getItem('agent_pg_model');
    const savedProvider = localStorage.getItem('agent_pg_provider');
    const savedTools = localStorage.getItem('agent_pg_custom_tools');
    const savedManualTools = localStorage.getItem('agent_pg_manual_tools');

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

    try {
      const c = localStorage.getItem('agent_pg_completed');
      if (c) ctx.completedLessons = JSON.parse(c) || [];
    } catch (e) {}

    const savedMode = localStorage.getItem('agent_pg_mode');
    const savedLesson = localStorage.getItem('agent_pg_lesson');
    const isReturning = !!(savedMode || ctx.history.length || savedLesson);
    ctx.mode = savedMode || (isReturning ? 'free' : 'lesson');

    return { savedLesson };
  }

  function bindPersistence(ctx) {
    ctx.$watch('backendUrl', v => localStorage.setItem('agent_pg_backend', v));
    ctx.$watch('modelOverride', v => localStorage.setItem('agent_pg_model', v));
    ctx.$watch('provider', v => localStorage.setItem('agent_pg_provider', v || ''));
    ctx.$watch('manualTools', v => {
      try { localStorage.setItem('agent_pg_manual_tools', JSON.stringify(v)); } catch (e) {}
    });
    ctx.$watch('customTools', v => {
      try { localStorage.setItem('agent_pg_custom_tools', JSON.stringify(v)); } catch (e) {}
    });
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
        ctx.enterLesson(target.id);
      } else {
        ctx.currentLessonId = target.id;
      }
    }
  }

  root.AgentLabLocalState = {
    restore,
    bindPersistence,
    finalizeRestore,
    persistTokenData,
  };
})(typeof window !== 'undefined' ? window : globalThis);
