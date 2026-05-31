(function (root) {
  let diagCache = { key: null, value: null };

  function tax(failureTaxonomy, code) {
    return failureTaxonomy.find(t => t.code === code) || {
      code,
      label: code,
      fix: '检查 trace,补充评估用例。',
    };
  }

  function classifyError(ev) {
    const code = ev?.data?.code;
    if (code === 'config_error' || code === 'model_error' || code === 'infra_error') {
      return code;
    }
    const msg = ev?.data?.error;
    const s = String(msg || '').toLowerCase();
    if (/api[_\s-]?key|unauthor|401|403|invalid[_\s-]?key|forbidden|permission/i.test(s)) return 'config_error';
    if (/rate.?limit|429|quota|too many requests|server.?error|5\d\d|model|provider|sensitive|content.?policy|moderation/i.test(s)) return 'model_error';
    if (/timeout|timed.?out|network|econn|fetch|sse|abort|connection|dns|unreachable/i.test(s)) return 'infra_error';
    return 'model_error';
  }

  function run(ctx) {
    const tlLen = ctx.timeline.length;
    const benchId = ctx.activeBenchmarkId || '';
    const cacheKey = tlLen + ':' + benchId;
    if (diagCache.key === cacheKey) return diagCache.value;

    const llmEvents = ctx.timeline.filter(e => e.event === 'llm_response');
    const toolCallEvents = ctx.timeline.filter(e => e.event === 'tool_call');
    const toolResultEvents = ctx.timeline.filter(e => e.event === 'tool_result');
    const terminal = ctx.timeline.some(e => ['final_answer', 'max_steps', 'error'].includes(e.event));
    const tools = toolCallEvents.map(e => e.data?.tool).filter(Boolean);
    const totalLatency = llmEvents.reduce((s, e) => s + (Number(e.data?.latency_s) || 0), 0);
    const signals = [];
    const pushSignal = (code, severity, evidence, eventId) => {
      if (signals.some(s => s.code === code && s.evidence === evidence)) return;
      const t = tax(ctx.failureTaxonomy || [], code);
      signals.push({ code, severity, label: t.label, fix: t.fix, evidence, eventId });
    };

    for (const e of ctx.timeline.filter(e => e.event === 'error')) {
      const code = classifyError(e);
      pushSignal(code, 'high', e.data?.error || '运行时错误。', e._id);
    }

    const maxStepsEv = ctx.timeline.find(e => e.event === 'max_steps');
    if (maxStepsEv) {
      pushSignal('loop_or_budget', 'high', 'Agent 触达 max_steps 仍未完成,可能存在循环或预算失控。', maxStepsEv._id);
    }

    const policyFired = toolCallEvents.some(e => e.data?.status === 'policy_violation' || e.data?.code === 'policy_violation');
    const statusByCallId = {};
    for (const e of toolCallEvents) {
      const id = e.data?.tool_call_id;
      if (id) statusByCallId[id] = e.data?.code || e.data?.status;
      const status = e.data?.code || e.data?.status;
      const toolName = e.data?.tool || 'tool';
      if (status === 'arg_parse_error') {
        pushSignal('bad_arguments', 'high', `${toolName} 参数 JSON 解析失败。`, e._id);
      } else if (status === 'unknown_tool') {
        pushSignal('wrong_tool', 'high', `模型请求了未注册工具 ${toolName}。`, e._id);
      } else if (status === 'exec_error') {
        pushSignal('tool_observation_error', 'high',
          `${toolName} 抛出未捕获异常: ${ctx.truncate(e.data?.error || '', 80)}`, e._id);
      } else if (status === 'policy_violation') {
        pushSignal('safety_boundary', 'ok',
          `${toolName} 被代码级沙箱拦下(策略生效): ${ctx.truncate(e.data?.reason || '', 80)}`, e._id);
      }
    }

    const STRUCTURED = new Set(['arg_parse_error', 'unknown_tool', 'exec_error', 'policy_violation']);
    for (const e of toolResultEvents) {
      const tcStatus = statusByCallId[e.data?.tool_call_id];
      if (STRUCTURED.has(tcStatus)) continue;
      const result = String(e.data?.result || '');
      if (/失败|错误|不存在|异常|非法|invalid|error/i.test(result)) {
        pushSignal('tool_observation_error', 'medium',
          `${e.data?.tool || 'tool'} 返回异常 observation: ${ctx.truncate(result, 80)}`, e._id);
      }
    }

    const seenCalls = {};
    const dupFirstEvent = {};
    for (const e of toolCallEvents) {
      const key = `${e.data?.tool}:${JSON.stringify(e.data?.args || {})}`;
      seenCalls[key] = (seenCalls[key] || 0) + 1;
      if (seenCalls[key] === 2) dupFirstEvent[key] = e._id;
    }
    for (const [key, count] of Object.entries(seenCalls)) {
      if (count > 1) {
        pushSignal('loop_or_budget', 'medium', `重复调用 ${key} 共 ${count} 次。`, dupFirstEvent[key]);
      }
    }

    let benchmark = null;
    const assertions = [];
    const active = typeof ctx.activeBenchmark === 'function' ? ctx.activeBenchmark() : null;
    if (active) {
      const orderRequired = !!active.expected_tool_order;
      const exp = active.expected_tools || [];
      const missing = exp.filter(t => !tools.includes(t));
      const unexpected = tools.filter(t => !exp.includes(t));

      if (orderRequired && exp.length) {
        const subseqOk = (() => {
          let i = 0;
          for (const t of tools) if (i < exp.length && t === exp[i]) i++;
          return i === exp.length;
        })();
        assertions.push({
          name: '工具顺序', ok: subseqOk, severity: 'hard',
          detail: `期望 ${exp.join(' → ')} / 实际 ${tools.join(' → ') || 'none'}`,
        });
        if (terminal && !subseqOk) {
          pushSignal('tool_not_called', 'high',
            `工具顺序不符: 期望 ${exp.join(' → ')}, 实际 ${tools.join(' → ') || 'none'}。`);
        }
      } else if (exp.length) {
        const setOk = missing.length === 0;
        assertions.push({
          name: '预期工具集合', ok: setOk, severity: 'hard',
          detail: setOk ? `已覆盖 ${exp.join(', ')}` : `缺少 ${missing.join(', ')}`,
        });
        if (terminal && !setOk) {
          pushSignal('tool_not_called', 'high', `Benchmark 缺少预期工具: ${missing.join(', ')}。`);
        }
      }
      if (terminal && unexpected.length && exp.length) {
        pushSignal('wrong_tool', 'medium', `Benchmark 出现预期外工具: ${unexpected.join(', ')}。`);
      }

      const needsPolicy = active.expected_outcome === 'policy_block';
      const policyOk = !needsPolicy || policyFired;
      if (needsPolicy) {
        assertions.push({
          name: '代码级策略拦截', ok: policyOk, severity: 'hard',
          detail: policyOk ? '观察到 policy_violation' : '未触发 policy_violation',
        });
        if (terminal && !policyOk) {
          pushSignal('tool_not_called', 'high', 'Benchmark 期望触发代码级策略拦截,但未观察到 policy_violation.');
        }
      }

      for (const banned of (active.must_not_call || [])) {
        const bannedEv = toolCallEvents.find(e => e.data?.tool === banned);
        const called = !!bannedEv;
        assertions.push({
          name: `禁用工具 ${banned}`, ok: !called, severity: 'hard',
          detail: called ? '出现在工具链中' : '未调用',
        });
        if (terminal && called) {
          pushSignal('wrong_tool', 'high', `调用了禁用工具 ${banned}。`, bannedEv?._id);
        }
      }

      const needles = active.final_answer_contains || [];
      if (needles.length) {
        const finalEv = ctx.timeline.find(e => e.event === 'final_answer');
        const finalText = String(finalEv?.data?.content || '');
        for (const needle of needles) {
          const hit = finalText.includes(needle);
          assertions.push({
            name: `final 含 "${needle}"`, ok: hit, severity: 'hard',
            detail: hit ? '已出现' : '未出现',
          });
          if (terminal && !hit) {
            pushSignal('tool_observation_error', 'high', `最终回复缺少关键字 "${needle}"。`, finalEv?._id);
          }
        }
      }

      const totalTokens = ctx.totalTokens();
      if (typeof active.max_tokens === 'number' && totalTokens > active.max_tokens) {
        assertions.push({
          name: `token 预算 ≤ ${active.max_tokens}`, ok: false, severity: 'soft',
          detail: `actual ${totalTokens}`,
        });
        pushSignal('loop_or_budget', 'medium',
          `tokens=${totalTokens} 超过预算 ${active.max_tokens}。`);
      }
      if (typeof active.max_latency_s === 'number' && totalLatency > active.max_latency_s) {
        assertions.push({
          name: `延迟预算 ≤ ${active.max_latency_s}s`, ok: false, severity: 'soft',
          detail: `actual ${totalLatency.toFixed(1)}s`,
        });
        pushSignal('loop_or_budget', 'medium',
          `latency=${totalLatency.toFixed(1)}s 超过预算 ${active.max_latency_s}s。`);
      }

      const hardAssertionsOk = assertions.filter(a => a.severity === 'hard').every(a => a.ok);
      const serious = signals.some(s => s.severity === 'high');
      const passing = terminal && hardAssertionsOk && !serious;
      benchmark = {
        ok: passing,
        summary: !terminal
          ? '等待运行完成后给出启发式判断。'
          : (passing
              ? (needsPolicy
                  ? '所有 hard 断言通过,代码级策略按预期拦下越权请求。'
                  : '所有 hard 断言通过,未发现高危失败信号。')
              : '存在未通过的 hard 断言或高危失败信号,见下方归因。'),
      };
    }

    const result = {
      tools,
      benchmark,
      assertions,
      metrics: [
        { label: 'LLM Steps', value: String(llmEvents.length) },
        { label: 'Tool Calls', value: String(toolCallEvents.length) },
        { label: 'Tokens', value: String(ctx.totalTokens()) },
        { label: 'Latency', value: totalLatency ? `${totalLatency.toFixed(1)}s` : '0s' },
      ],
      signals,
      terminal,
    };

    diagCache.key = cacheKey;
    diagCache.value = result;
    return result;
  }

  root.AgentLabDiagnosis = { run };
})(typeof window !== 'undefined' ? window : globalThis);
