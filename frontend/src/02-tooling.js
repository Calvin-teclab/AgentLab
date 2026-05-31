(function (root) {
  function emptyToolDraft() {
    return {
      originalName: '',
      name: 'my_custom_tool',
      description: '说明这个工具什么时候该被模型调用,什么时候不该调用。',
      parametersText: JSON.stringify({
        type: 'object',
        properties: {
          query: {
            type: 'string',
            description: '用户要查询的内容',
          },
        },
        required: ['query'],
      }, null, 2),
      response_template: 'Mock 工具 {{tool_name}} 已收到参数:\n{{args_json}}',
    };
  }

  function allTools(ctx) {
    const builtIns = Object.entries(ctx.tools || {}).map(([name, t]) => ({
      name,
      description: t.description,
      parameters: t.parameters || { type: 'object', properties: {} },
      source: 'built_in',
    }));
    const builtInNames = new Set(builtIns.map(t => t.name));
    const custom = (ctx.customTools || [])
      .filter(t => t && t.name && !builtInNames.has(t.name))
      .map(t => ({ ...t, source: 'custom' }));
    return [...builtIns, ...custom];
  }

  function uniqueToolName(ctx, baseName) {
    let name = baseName || 'custom_tool';
    let i = 2;
    while ((ctx.tools || {})[name] || (ctx.customTools || []).some(t => t.name === name)) {
      const suffix = `_${i}`;
      name = `${baseName.slice(0, 64 - suffix.length)}${suffix}`;
      i += 1;
    }
    return name;
  }

  function startNewTool(ctx) {
    ctx.leftTab = 'tools';
    ctx.toolEditorError = '';
    ctx.toolDraft = emptyToolDraft();
    ctx.editingTool = true;
  }

  function editTool(ctx, tool) {
    ctx.leftTab = 'tools';
    ctx.toolEditorError = '';
    ctx.toolDraft = {
      originalName: tool.name,
      name: tool.name,
      description: tool.description || '',
      parametersText: JSON.stringify(tool.parameters || { type: 'object', properties: {} }, null, 2),
      response_template: tool.response_template || '',
    };
    ctx.editingTool = true;
  }

  function duplicateTool(ctx, tool) {
    ctx.leftTab = 'tools';
    ctx.toolEditorError = '';
    const baseName = `${tool.name}_mock`.replace(/[^A-Za-z0-9_]/g, '_').slice(0, 64);
    ctx.toolDraft = {
      originalName: '',
      name: uniqueToolName(ctx, baseName),
      description: tool.description || '',
      parametersText: JSON.stringify(tool.parameters || { type: 'object', properties: {} }, null, 2),
      response_template: 'Mock 工具 {{tool_name}} 已收到参数:\n{{args_json}}',
    };
    ctx.editingTool = true;
  }

  function closeToolEditor(ctx) {
    ctx.editingTool = false;
    ctx.toolEditorError = '';
  }

  function saveToolDraft(ctx) {
    const name = ctx.toolDraft.name.trim();
    const originalName = ctx.toolDraft.originalName;
    if (!/^[A-Za-z_][A-Za-z0-9_]{0,63}$/.test(name)) {
      ctx.toolEditorError = 'Name 只能使用字母、数字、下划线,且不能以数字开头。';
      return;
    }
    if ((ctx.tools || {})[name]) {
      ctx.toolEditorError = '不能覆盖内置工具。请换一个 name,或先复制为 mock 版本。';
      return;
    }
    if (!ctx.toolDraft.description.trim()) {
      ctx.toolEditorError = 'Description 不能为空,这是模型判断是否调用工具的关键。';
      return;
    }

    let parameters;
    try {
      parameters = JSON.parse(ctx.toolDraft.parametersText);
    } catch (e) {
      ctx.toolEditorError = 'Parameters JSON Schema 不是合法 JSON。';
      return;
    }
    if (!parameters || parameters.type !== 'object') {
      ctx.toolEditorError = 'Parameters JSON Schema 顶层 type 必须是 object。';
      return;
    }

    const duplicate = (ctx.customTools || []).some(t => t.name === name && t.name !== originalName);
    if (duplicate) {
      ctx.toolEditorError = '已经存在同名自定义工具。';
      return;
    }

    const saved = {
      name,
      description: ctx.toolDraft.description.trim(),
      parameters,
      response_template: ctx.toolDraft.response_template,
    };
    if (originalName) {
      ctx.customTools = (ctx.customTools || []).map(t => t.name === originalName ? saved : t);
      ctx.enabledTools = (ctx.enabledTools || []).map(n => n === originalName ? name : n);
    } else {
      ctx.customTools = [...(ctx.customTools || []), saved];
      if (!(ctx.enabledTools || []).includes(name)) ctx.enabledTools.push(name);
    }
    closeToolEditor(ctx);
  }

  function deleteCustomTool(ctx, name) {
    ctx.customTools = (ctx.customTools || []).filter(t => t.name !== name);
    ctx.enabledTools = (ctx.enabledTools || []).filter(n => n !== name);
    if (ctx.toolDraft.originalName === name) closeToolEditor(ctx);
  }

  function resetCustomTools(ctx) {
    ctx.customTools = [];
    ctx.enabledTools = (ctx.enabledTools || []).filter(n => ctx.tools[n]);
    closeToolEditor(ctx);
  }

  function addToolExamples(ctx) {
    const next = [...(ctx.customTools || [])];
    for (const tool of (ctx.customToolExamples || [])) {
      if (!next.some(t => t.name === tool.name) && !(ctx.tools || {})[tool.name]) {
        next.push(tool);
        if (!(ctx.enabledTools || []).includes(tool.name)) ctx.enabledTools.push(tool.name);
      }
    }
    ctx.customTools = next;
  }

  function toggleManualTool(ctx, name) {
    if (!(ctx.enabledTools || []).includes(name)) return;
    const i = ctx.manualTools.indexOf(name);
    if (i >= 0) ctx.manualTools.splice(i, 1);
    else ctx.manualTools.push(name);
  }

  function onToolToggled(ctx) {
    ctx.manualTools = (ctx.manualTools || []).filter(n => (ctx.enabledTools || []).includes(n));
  }

  root.AgentLabTooling = {
    emptyToolDraft,
    allTools,
    uniqueToolName,
    startNewTool,
    editTool,
    duplicateTool,
    closeToolEditor,
    saveToolDraft,
    deleteCustomTool,
    resetCustomTools,
    addToolExamples,
    toggleManualTool,
    onToolToggled,
  };
})(typeof window !== 'undefined' ? window : globalThis);
