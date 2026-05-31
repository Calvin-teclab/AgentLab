(function (root) {
  async function consumeEventStream(resp, onEvent) {
    if (!resp.ok) throw new Error('HTTP ' + resp.status);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop();

      for (const frame of frames) {
        if (!frame.trim()) continue;
        const lines = frame.split(/\r?\n/);
        for (const line of lines) {
          if (!line.startsWith('data:')) continue;
          try {
            const payload = JSON.parse(line.slice(5).trim());
            onEvent(payload);
          } catch (e) {
            console.warn('SSE parse error:', e, line);
          }
        }
      }
    }
  }

  function suggestManualToolResult(toolCall) {
    const args = toolCall?.args ?? toolCall?.raw_args ?? {};
    return [
      `[人工工具返回] ${toolCall?.tool || 'tool'}`,
      `参数: ${typeof args === 'string' ? args : JSON.stringify(args, null, 2)}`,
      '结果: ',
    ].join('\n');
  }

  function applyEvent(ctx, payload) {
    const ev = { ...payload, _open: true, _id: ctx._eventCounter++ };
    ctx.timeline.push(ev);
    if (payload.step) ctx.currentStep = payload.step;

    if (payload.event === 'user_input') {
      ctx.history = payload.data.messages_snapshot || ctx.history;
    } else if (payload.event === 'llm_response') {
      if (payload.data.usage) {
        ctx.tokenData.push({
          callIdx: ctx.tokenData.length + 1,
          step: payload.step,
          prompt: payload.data.usage.prompt_tokens || 0,
          completion: payload.data.usage.completion_tokens || 0,
          estimated: Boolean(payload.data.usage.estimated),
        });
        if (window.AgentLabLocalState?.persistTokenData) {
          window.AgentLabLocalState.persistTokenData(ctx);
        }
        ctx.updateChart();
      }
      const msg = {
        role: 'assistant',
        content: payload.data.content || null,
      };
      if (payload.data.tool_calls?.length) {
        msg.tool_calls = payload.data.tool_calls;
      }
      ctx.history.push(msg);
    } else if (payload.event === 'tool_input_required') {
      if (payload.data.messages_snapshot) {
        ctx.history = payload.data.messages_snapshot;
      }
      ctx.pendingManualTool = payload.data;
      ctx.manualToolResult = suggestManualToolResult(payload.data);
      ctx.inspectorView = 'trace';
    } else if (payload.event === 'tool_result') {
      if (payload.data.messages_snapshot) {
        ctx.history = payload.data.messages_snapshot;
      } else {
        ctx.history.push({
          role: 'tool',
          tool_call_id: payload.data.tool_call_id,
          content: payload.data.result,
        });
      }
    } else if (payload.event === 'final_answer' || payload.event === 'max_steps') {
      if (payload.data.messages_snapshot) {
        ctx.history = payload.data.messages_snapshot;
      }
      ctx.pendingToolRollbackHistoryLen = null;
    }

    ctx.scrollChatBottom();
    ctx.scrollTimelineBottom();
  }

  root.AgentLabEventing = {
    consumeEventStream,
    applyEvent,
    suggestManualToolResult,
  };
})(typeof window !== 'undefined' ? window : globalThis);
