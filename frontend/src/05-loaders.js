(function (root) {
  async function checkHealth(ctx) {
    try {
      const r = await fetch(ctx.backendUrl + '/api/health', { signal: AbortSignal.timeout(2000) });
      ctx.backendOnline = r.ok;
    } catch {
      ctx.backendOnline = false;
    }
  }

  async function launchBackend(ctx) {
    // 经前端服务器(serve.py)的本地接口拉起后端。浏览器自身无权启动进程,
    // 这里用「同源相对路径」命中 serve.py(前端端口),而不是 backendUrl(后端端口)。
    const r = await fetch('/__launch_backend', {
      method: 'POST',
      signal: AbortSignal.timeout(5000),
    });
    if (!r.ok) throw new Error('launch endpoint returned ' + r.status);
    return r.json();
  }

  async function loadTools(ctx) {
    try {
      const r = await fetch(ctx.backendUrl + '/api/tools');
      ctx.tools = await r.json();
      ctx.enabledTools = ctx.allTools().map(t => t.name);
    } catch (e) {
      console.warn('加载工具失败:', e);
    }
  }

  async function loadProviders(ctx) {
    try {
      const r = await fetch(ctx.backendUrl + '/api/providers');
      if (!r.ok) throw new Error('no providers endpoint');
      const data = await r.json();
      ctx.availableProviders = data.providers || [];
      const names = ctx.availableProviders.map(p => p.name);
      if (!ctx.provider || !names.includes(ctx.provider)) {
        ctx.provider = data.default || (names[0] || '');
      }
    } catch (e) {
      ctx.availableProviders = [{ name: 'ark', label: '火山方舟 (DeepSeek 等)', default_model: '' }];
      if (!ctx.provider) ctx.provider = 'ark';
    }
  }

  async function loadLessons(ctx) {
    try {
      const r = await fetch(ctx.backendUrl + '/api/lessons');
      const j = await r.json();
      ctx.lessons = (j.lessons || []).slice().sort((a, b) => a.order - b.order);
    } catch (e) {
      console.warn('加载关卡失败:', e);
      ctx.lessons = [];
    }
  }

  async function loadEvalAssets(ctx) {
    try {
      const r = await fetch(ctx.backendUrl + '/api/eval-assets');
      const j = await r.json();
      ctx.chatExamples = j.chat_examples || [];
      ctx.benchmarkCases = j.benchmarks || [];
      ctx.massTemplates = j.mass_templates || [];
      ctx.failureTaxonomy = j.failure_taxonomy || [];
    } catch (e) {
      console.warn('加载评估资产失败:', e);
      ctx.chatExamples = [];
      ctx.benchmarkCases = [];
      ctx.massTemplates = [];
      ctx.failureTaxonomy = [];
    }
  }

  root.AgentLabLoaders = {
    checkHealth,
    launchBackend,
    loadTools,
    loadProviders,
    loadLessons,
    loadEvalAssets,
  };
})(typeof window !== 'undefined' ? window : globalThis);
