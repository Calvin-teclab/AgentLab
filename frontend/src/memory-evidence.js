(function (root) {
  const system = { role: 'system', content: '你是一个简洁的助手。直接回答用户的问题，不要过多解释。' };
  const question = { role: 'user', content: '我叫什么？' };
  const replay = {
    name: '张三',
    before: [system, { role: 'user', content: '我叫张三' }, { role: 'assistant', content: '你好，张三。' }, question],
    after: [system, question],
  };

  const nameQuestion = /^\s*我叫什么(?:名字)?[?？。!！\s]*$/;

  function observe(ctx, messages) {
    const question = messages.at(-1)?.content || '';
    if (!nameQuestion.test(question)) return;
    const declaration = messages.slice(0, -1).filter(m => m.role === 'user' && !nameQuestion.test(m.content))
      .map(m => /^\s*我叫\s*([^，。,！!？?\s]+)/.exec(m.content)?.[1]).filter(Boolean).pop();
    const snapshot = JSON.parse(JSON.stringify(messages));
    if (declaration) {
      ctx.nameEvidence = { before: snapshot, after: null, name: declaration, cleared: false, question };
    } else if (ctx.nameEvidence?.cleared && !ctx.nameEvidence.after &&
        question.replace(/[?？。!！\s]/g, '') === ctx.nameEvidence.question.replace(/[?？。!！\s]/g, '')) {
      ctx.nameEvidence = { ...ctx.nameEvidence, after: snapshot };
    }
    if (ctx.nameEvidence) ctx.showReplay = false;
  }

  root.AgentLabMemoryEvidence = { replay, observe };
})(typeof window !== 'undefined' ? window : globalThis);
