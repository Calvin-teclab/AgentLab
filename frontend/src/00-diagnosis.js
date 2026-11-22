(function (root) {

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

  function scoreResult(rule, input, final, results) {
    if (!input && !final) return { status: '等待运行', detail: '发送用例后开始核对。' };
    const expected = input?.data.score_reference;
    if (!expected || expected.error) {
      return { status: '缺少证据', detail: expected?.error || '运行时未记录成绩，请重新运行。' };
    }
    if (!final) return { status: '未完成', detail: '等待本轮最终回答。' };
    const report = rule === 'score_report';
    const artifact = final.data.report_evidence;
    if (report) {
      const writes = results.filter(e => e.data.report_write_digest);
      if (!artifact?.digest || !writes.length || writes[writes.length - 1].data.report_write_digest !== artifact.digest) {
        return { status: '未通过', detail: '未能回读本轮成功写入且内容一致的 report.txt。' };
      }
    }
    const claims = report ? artifact.claims : { mean: final.data.mean_claims };
    const fields = report ? ['total', 'mean', 'max', 'min'] : ['mean'];
    const labels = { total: '总分', mean: '平均分', max: '最高分', min: '最低分' };
    let correct = true;
    const details = fields.map(key => {
      const values = [...new Set(claims?.[key] || [])];
      const ok = values.length > 0 && values.every(v => Math.abs(v - expected[key]) < (key === 'mean' ? 0.005000001 : 0.000001));
      correct = correct && ok;
      return labels[key] + ' ' + (values.join(' / ') || '未识别') + '（期望 ' + expected[key] + '）';
    });
    return { status: correct ? '通过' : '未通过', detail: details.join('，') };
  }

  function run(ctx) {
    const start = ctx.timeline.map(e => e.event).lastIndexOf('user_input');
    const events = ctx.timeline.slice(Math.max(start, ctx.runStartIndex || 0));
    const input = events.find(e => e.event === 'user_input');
    const final = events.find(e => e.event === 'final_answer');
    const llmEvents = events.filter(e => e.event === 'llm_response');
    const toolCallEvents = events.filter(e => ['tool_call', 'tool_input_required'].includes(e.event));
    const toolResultEvents = events.filter(e => e.event === 'tool_result');
    const terminal = events.some(e => ['final_answer', 'max_steps', 'error'].includes(e.event));
    const tools = toolCallEvents.map(e => e.data?.tool).filter(Boolean);
    const totalTokens = llmEvents.reduce((sum, e) => {
      const usage = e.data?.usage || {};
      return sum + (usage.total_tokens ?? ((usage.prompt_tokens || 0) + (usage.completion_tokens || 0)));
    }, 0);
    const totalLatency = llmEvents.reduce((s, e) => s + (Number(e.data?.latency_s) || 0), 0);
    const signals = [];
    const pushSignal = (code, severity, evidence, eventId) => {
      if (signals.some(s => s.code === code && s.evidence === evidence)) return;
      const t = tax(ctx.failureTaxonomy || [], code);
      signals.push({ code, severity, label: t.label, fix: t.fix, evidence, eventId });
    };

    for (const e of events.filter(e => e.event === 'error')) {
      const code = classifyError(e);
      pushSignal(code, 'high', e.data?.error || '运行时错误。', e._id);
    }

    const maxStepsEv = events.find(e => e.event === 'max_steps');
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
    let configBlocked = false;
    const active = typeof ctx.activeBenchmark === 'function' ? ctx.activeBenchmark() : null;
    if (active) {
      const orderRequired = !!active.expected_tool_order;
      const exp = active.expected_tools || [];
      const missing = exp.filter(t => !tools.includes(t));
      const unexpected = tools.filter(t => !exp.includes(t));

      // 关键区分:期望工具「缺席」可能是两类完全不同的原因 ——
      //   missingDisabled : 该工具当前未在 TOOLS 面板勾选 → 模型根本拿不到 → 配置问题,不怪模型
      //   missingEnabled  : 工具已启用却没被调用 → 真·模型行为问题(应调未调)
      const enabledSet = new Set(input?.data.enabled_tools || ctx.enabledTools || []);
      const missingDisabled = missing.filter(t => !enabledSet.has(t));
      const missingEnabled = missing.filter(t => enabledSet.has(t));
      configBlocked = missingDisabled.length > 0;
      const disabledNote = `本 case 需要 ${missingDisabled.join(', ')},但当前未在 TOOLS 面板勾选,模型拿不到 → 无法调用。此 fail 源于工具集配置,不代表模型行为:启用后重跑即可。`;

      if (orderRequired && exp.length) {
        const subseqOk = (() => {
          let i = 0;
          for (const t of tools) if (i < exp.length && t === exp[i]) i++;
          return i === exp.length;
        })();
        const blockedOnly = !subseqOk && configBlocked && !missingEnabled.length;
        assertions.push({
          name: '工具顺序', ok: subseqOk,
          severity: blockedOnly ? 'config' : 'hard',
          detail: blockedOnly
            ? `期望 ${exp.join(' → ')};未启用 ${missingDisabled.join(', ')}(无法调用)`
            : `期望 ${exp.join(' → ')} / 实际 ${tools.join(' → ') || 'none'}`,
        });
        if (terminal && !subseqOk) {
          if (missingDisabled.length) pushSignal('tool_disabled', 'medium', disabledNote);
          if (!missingDisabled.length || missingEnabled.length) {
            pushSignal('tool_not_called', 'high',
              `工具顺序不符: 期望 ${exp.join(' → ')}, 实际 ${tools.join(' → ') || 'none'}。`);
          }
        }
      } else if (exp.length) {
        const setOk = missing.length === 0;
        const blockedOnly = !setOk && configBlocked && !missingEnabled.length;
        assertions.push({
          name: '预期工具集合', ok: setOk,
          severity: blockedOnly ? 'config' : 'hard',
          detail: setOk ? `已覆盖 ${exp.join(', ')}`
            : (configBlocked
                ? `未启用 ${missingDisabled.join(', ')}${missingEnabled.length ? `;另缺 ${missingEnabled.join(', ')}` : ''}`
                : `缺少 ${missing.join(', ')}`),
        });
        if (terminal && !setOk) {
          if (missingDisabled.length) pushSignal('tool_disabled', 'medium', disabledNote);
          if (missingEnabled.length) {
            pushSignal('tool_not_called', 'high', `Benchmark 缺少预期工具: ${missingEnabled.join(', ')}。`);
          }
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
        const finalEv = events.find(e => e.event === 'final_answer');
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

      const pathRules = assertions.filter(a => a.name.startsWith('工具') || a.name.startsWith('预期工具') || a.name.startsWith('禁用工具'));
      const path = !terminal ? '等待运行' : configBlocked ? '配置阻断' : pathRules.every(a => a.ok) ? '通过' : '未通过';
      let outcome = { status: '未单独评估', detail: '此用例检查工具调用。' };
      if (active.result_check) {
        outcome = scoreResult(active.result_check, input, final, toolResultEvents);
        if (terminal && outcome.status !== '通过') {
          assertions.push({ name: '任务结果', ok: false, severity: 'hard', detail: outcome.detail });
        }
      } else if (needsPolicy) {
        outcome = { status: !terminal ? '等待运行' : policyOk ? '通过' : '未通过', detail: '核对工具层拦截事件。' };
      }
      const hardAssertionsOk = assertions.filter(a => a.severity === 'hard').every(a => a.ok);
      const serious = signals.some(s => s.severity === 'high');
      // configBlocked 时既不算 PASS 也不算模型 FAIL —— 单独的「配置阻断」态,
      // 否则会因为没有 hard 失败而误判成 PASS。
      const passing = terminal && hardAssertionsOk && !serious && !configBlocked;
      const blockedTools = active.expected_tools
        ? active.expected_tools.filter(t => !new Set(input?.data.enabled_tools || ctx.enabledTools || []).has(t))
        : [];
      benchmark = {
        ok: passing,
        outcome,
        path,
        blocked: configBlocked && terminal,   // 「配置阻断」是跑完后的判定;跑前预防交给输入框/卡片横幅
        blockedTools,
        summary: !terminal
          ? '等待运行完成后给出启发式判断。'
          : (configBlocked
              ? `配置阻断:本 case 依赖工具 ${blockedTools.join(', ')},当前未在 TOOLS 面板勾选,模型无法调用。此结果反映工具集配置,而非模型行为——启用后重跑。`
              : (passing
                  ? (needsPolicy
                      ? '所有 hard 断言通过,代码级策略按预期拦下越权请求。'
                      : '所有 hard 断言通过,未发现高危失败信号。')
                  : '存在未通过的 hard 断言或高危失败信号,见下方归因。')),
      };
    }

    const result = {
      tools,
      benchmark,
      assertions,
      metrics: [
        { label: 'LLM Steps', value: String(llmEvents.length) },
        { label: 'Tool Calls', value: String(toolCallEvents.length) },
        { label: 'Tokens', value: String(totalTokens) },
        { label: 'Latency', value: totalLatency ? `${totalLatency.toFixed(1)}s` : '0s' },
      ],
      signals,
      terminal,
    };

    return result;
  }

  root.AgentLabDiagnosis = { run };
})(typeof window !== 'undefined' ? window : globalThis);
