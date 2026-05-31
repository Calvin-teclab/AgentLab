(function (root) {
  function eventColor(ev) {
    return ({
      user_input: '#3b82f6',
      llm_response: '#7c3aed',
      tool_call: '#2dd4bf',
      tool_input_required: '#38bdf8',
      tool_result: '#34d399',
      final_answer: '#38bdf8',
      error: '#dc2626',
      max_steps: '#991b1b',
    })[ev] || '#9ca3af';
  }

  function eventBadgeClass(ev) {
    return ({
      user_input: 'bg-blue-100 text-blue-700',
      llm_response: 'bg-purple-100 text-purple-700',
      tool_call: 'bg-amber-100 text-amber-700',
      tool_input_required: 'bg-cyan-100 text-cyan-700',
      tool_result: 'bg-green-100 text-green-700',
      final_answer: 'bg-cyan-100 text-cyan-700',
      error: 'bg-red-100 text-red-700',
      max_steps: 'bg-red-200 text-red-800',
    })[ev] || 'bg-gray-100 text-gray-600';
  }

  function usageLabel(usage) {
    if (!usage) return '? tok';
    return `${usage.estimated ? '~' : ''}${usage.total_tokens || '?'} tok`;
  }

  function summarize(ctx, ev) {
    const d = ev.data || {};
    switch (ev.event) {
      case 'user_input':
        return d.content;
      case 'llm_response':
        if (d.tool_calls?.length) {
          return 'TOOL ' + d.tool_calls.map(tc => tc.function.name).join(', ') +
            ` · ${usageLabel(d.usage)} · ${d.latency_s}s`;
        }
        return ctx.truncate(d.content || '(无内容)', 80) +
          ` · ${usageLabel(d.usage)}`;
      case 'tool_call':
        return `${d.tool}(${JSON.stringify(d.args || {})})`;
      case 'tool_input_required':
        return `等待人工返回 ${d.tool}(${JSON.stringify(d.args || {})})`;
      case 'tool_result':
        return `${d.tool} → ${ctx.truncate(d.result, 60)}`;
      case 'final_answer':
        return ctx.truncate(d.content, 80);
      case 'error':
        return d.error;
      case 'max_steps':
        return d.hint;
      default:
        return '';
    }
  }

  function filteredTimeline(ctx) {
    if (ctx.timelineFilter === 'all') return ctx.timeline;
    if (ctx.timelineFilter === 'llm') {
      return ctx.timeline.filter(e => ['llm_response', 'final_answer'].includes(e.event));
    }
    if (ctx.timelineFilter === 'tool') {
      return ctx.timeline.filter(e => ['tool_call', 'tool_input_required', 'tool_result'].includes(e.event));
    }
    return ctx.timeline;
  }

  root.AgentLabTimeline = {
    eventColor,
    eventBadgeClass,
    summarize,
    filteredTimeline,
    usageLabel,
  };
})(typeof window !== 'undefined' ? window : globalThis);
