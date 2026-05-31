(function (root) {
  function currentProviderDefaultModel(ctx) {
    const p = (ctx.availableProviders || []).find(p => p.name === ctx.provider);
    return p ? p.default_model : '';
  }

  function modelOverridePlaceholder(ctx) {
    if (ctx.provider === 'gemini') return 'gemini-2.5-flash / gemini-flash-latest';
    if (ctx.provider === 'ark') return 'ep-xxxxxx (留空=默认)';
    return '(留空=默认)';
  }

  function systemPromptStale(ctx) {
    if (!ctx.history.length) return false;
    const first = ctx.history[0];
    if (!first || first.role !== 'system') return false;
    return first.content !== ctx.systemPrompt;
  }

  function visibleMessages(ctx) {
    return (ctx.history || []).filter(m => m.role !== 'system');
  }

  function truncate(s, n) {
    if (!s) return '';
    return s.length > n ? s.slice(0, n) + '...' : s;
  }

  function renderMarkdown(md) {
    if (!md) return '';
    const escape = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    let html = '';
    const lines = md.split('\n');
    let inOl = false;
    for (const raw of lines) {
      const line = escape(raw);
      if (/^##\s+/.test(line)) {
        if (inOl) { html += '</ol>'; inOl = false; }
        html += `<h2>${line.replace(/^##\s+/, '')}</h2>`;
      } else if (/^\d+\.\s+/.test(line)) {
        if (!inOl) { html += '<ol>'; inOl = true; }
        html += `<li>${line.replace(/^\d+\.\s+/, '')}</li>`;
      } else if (line.trim() === '') {
        if (inOl) { html += '</ol>'; inOl = false; }
      } else {
        if (inOl) { html += '</ol>'; inOl = false; }
        html += `<p>${line}</p>`;
      }
    }
    if (inOl) html += '</ol>';
    html = html
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*([^*]+?)\*/g, '<em>$1</em>')
      .replace(/`([^`]+?)`/g, '<code>$1</code>');
    return html;
  }

  function scrollChatBottom(ctx) {
    ctx.$nextTick(() => {
      const box = ctx.$refs.chatBox;
      if (box) box.scrollTop = box.scrollHeight;
    });
  }

  function scrollTimelineBottom(ctx) {
    ctx.$nextTick(() => {
      const box = ctx.$refs.timelineBox;
      if (box) box.scrollTop = box.scrollHeight;
    });
  }

  function jumpToEvent(ctx, eventId) {
    if (eventId === undefined || eventId === null) return;
    ctx.inspectorView = 'trace';
    const ev = ctx.timeline.find(e => e._id === eventId);
    if (!ev) return;
    ev._open = true;
    ctx.$nextTick(() => {
      const box = ctx.$refs.timelineBox;
      const el = box?.querySelector(`[data-event-id="${eventId}"]`);
      if (!el) return;
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.remove('flash-jump');
      void el.offsetWidth;
      el.classList.add('flash-jump');
      setTimeout(() => el.classList.remove('flash-jump'), 600);
    });
  }

  function stepEvents(ctx, n) {
    return (ctx.timeline || []).filter(e => e.step === n);
  }

  function stepBead(ctx, n, kind) {
    const events = stepEvents(ctx, n);
    if (kind === 'thought') return events.some(e => e.event === 'llm_response');
    if (kind === 'action') return events.some(e => e.event === 'llm_response' && e.data?.tool_calls?.length);
    if (kind === 'observe') return events.some(e => e.event === 'tool_result' || e.event === 'tool_input_required');
    if (kind === 'final') return events.some(e => e.event === 'final_answer');
    if (kind === 'max') return events.some(e => e.event === 'max_steps');
    return false;
  }

  function capsuleClass(ctx, n) {
    if (n > ctx.currentStep) return 'pending';
    if (ctx.isRunning && n === ctx.currentStep) return 'current';
    return 'done';
  }

  function reactPhase(ctx) {
    if (!ctx.isRunning) return null;
    if (!ctx.timeline.length) return 'reason';
    const last = ctx.timeline[ctx.timeline.length - 1];
    if (last.event === 'user_input') return 'reason';
    if (last.event === 'llm_response') return last.data?.tool_calls?.length ? 'act' : 'reason';
    if (last.event === 'tool_input_required') return 'observe';
    if (last.event === 'tool_result') return 'observe';
    return 'reason';
  }

  function stepCellTitle(ctx, n) {
    if (n > ctx.currentStep) return `Step ${n} · 待执行`;
    const parts = [];
    if (stepBead(ctx, n, 'thought')) parts.push('思考');
    if (stepBead(ctx, n, 'action')) parts.push('行动');
    if (stepBead(ctx, n, 'observe')) parts.push('观察');
    if (stepBead(ctx, n, 'final')) parts.push('终答');
    if (stepBead(ctx, n, 'max')) parts.push('上限触发');
    const shape = parts.length ? ' · ' + parts.join(' → ') : '';
    if (ctx.isRunning && n === ctx.currentStep) return `Step ${n} · 进行中${shape}`;
    return `Step ${n} · 已完成${shape}`;
  }

  function isLessonStepCurrent(ctx, i) { return i === ctx.lessonStepIdx; }
  function isLessonStepDone(ctx, i) { return i < ctx.lessonStepIdx; }

  root.AgentLabUI = {
    currentProviderDefaultModel,
    modelOverridePlaceholder,
    systemPromptStale,
    visibleMessages,
    truncate,
    renderMarkdown,
    scrollChatBottom,
    scrollTimelineBottom,
    jumpToEvent,
    stepEvents,
    stepBead,
    capsuleClass,
    reactPhase,
    stepCellTitle,
    isLessonStepCurrent,
    isLessonStepDone,
  };
})(typeof window !== 'undefined' ? window : globalThis);
