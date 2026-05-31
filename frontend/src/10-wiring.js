(function (root) {
  root.AgentLabWiring = {
    async init() {
      const { savedLesson } = window.AgentLabLocalState.restore(this);
      window.AgentLabLocalState.bindPersistence(this);

      await this.checkHealth();
      await this.loadTools();
      await this.loadProviders();
      await this.loadLessons();
      await this.loadEvalAssets();
      window.AgentLabLocalState.finalizeRestore(this, savedLesson);

      this.$nextTick(() => {
        this.initChart();
        if (this.tokenData.length) this.updateChart();
      });

      setInterval(() => this.checkHealth(), 10000);
    },

    async checkHealth() {
      return window.AgentLabLoaders.checkHealth(this);
    },

    async loadTools() {
      return window.AgentLabLoaders.loadTools(this);
    },

    async loadProviders() {
      return window.AgentLabLoaders.loadProviders(this);
    },

    currentProviderDefaultModel() {
      return window.AgentLabUI.currentProviderDefaultModel(this);
    },

    modelOverridePlaceholder() {
      return window.AgentLabUI.modelOverridePlaceholder(this);
    },

    toggleManualTool(name) {
      window.AgentLabTooling.toggleManualTool(this, name);
    },

    onToolToggled(_name) {
      window.AgentLabTooling.onToolToggled(this, _name);
    },

    allTools() {
      return window.AgentLabTooling.allTools(this);
    },

    emptyToolDraft() {
      return window.AgentLabTooling.emptyToolDraft();
    },

    startNewTool() {
      window.AgentLabTooling.startNewTool(this);
    },

    editTool(tool) {
      window.AgentLabTooling.editTool(this, tool);
    },

    duplicateTool(tool) {
      window.AgentLabTooling.duplicateTool(this, tool);
    },

    closeToolEditor() {
      window.AgentLabTooling.closeToolEditor(this);
    },

    saveToolDraft() {
      window.AgentLabTooling.saveToolDraft(this);
    },

    deleteCustomTool(name) {
      window.AgentLabTooling.deleteCustomTool(this, name);
    },

    resetCustomTools() {
      window.AgentLabTooling.resetCustomTools(this);
    },

    addToolExamples() {
      window.AgentLabTooling.addToolExamples(this);
    },

    uniqueToolName(baseName) {
      return window.AgentLabTooling.uniqueToolName(this, baseName);
    },

    initChart() {
      window.AgentLabCharting.initChart(this);
    },

    updateChart() {
      window.AgentLabCharting.updateChart(this);
    },

    totalTokens() {
      return window.AgentLabCharting.totalTokens(this);
    },

    hasEstimatedTokens() {
      return window.AgentLabCharting.hasEstimatedTokens(this);
    },

    systemPromptStale() {
      return window.AgentLabUI.systemPromptStale(this);
    },

    async consumeEventStream(resp) {
      return window.AgentLabEventing.consumeEventStream(resp, (payload) => this.handleEvent(payload));
    },

    async send() {
      return window.AgentLabSession.send(this);
    },

    _pushRunHistory(caseId) {
      return window.AgentLabSession.pushRunHistory(this, caseId);
    },

    async submitManualToolResult() {
      return window.AgentLabSession.submitManualToolResult(this);
    },

    discardPendingToolCall() {
      return window.AgentLabSession.discardPendingToolCall(this);
    },

    stepEvents(n) {
      return window.AgentLabUI.stepEvents(this, n);
    },

    stepBead(n, kind) {
      return window.AgentLabUI.stepBead(this, n, kind);
    },

    capsuleClass(n) {
      return window.AgentLabUI.capsuleClass(this, n);
    },

    reactPhase() {
      return window.AgentLabUI.reactPhase(this);
    },

    stepCellTitle(n) {
      return window.AgentLabUI.stepCellTitle(this, n);
    },

    handleEvent(payload) {
      window.AgentLabEventing.applyEvent(this, payload);
    },

    suggestManualToolResult(toolCall) {
      return window.AgentLabEventing.suggestManualToolResult(toolCall);
    },

    resetSession() {
      return window.AgentLabSession.resetSession(this);
    },

    async loadLessons() {
      return window.AgentLabLoaders.loadLessons(this);
    },

    async loadEvalAssets() {
      return window.AgentLabLoaders.loadEvalAssets(this);
    },

    applySystemPromptPreset(preset) {
      return window.AgentLabSession.applySystemPromptPreset(this, preset);
    },

    applyMassTemplate(tpl) {
      return window.AgentLabSession.applyMassTemplate(this, tpl);
    },

    scenarioStateFingerprint() {
      return window.AgentLabSession.scenarioStateFingerprint(this);
    },

    showNotification({ title, detail, undoSnapshot }) {
      return window.AgentLabSession.showNotification(this, { title, detail, undoSnapshot });
    },

    dismissNotification() {
      return window.AgentLabSession.dismissNotification(this);
    },

    undoMassTemplate() {
      return window.AgentLabSession.undoMassTemplate(this);
    },

    clearMassScenario() {
      return window.AgentLabSession.clearMassScenario(this);
    },

    loadBenchmarkCase(b) {
      window.AgentLabScenario.loadBenchmarkCase(this, b);
    },

    useBenchmarkInput(b) {
      window.AgentLabScenario.useBenchmarkInput(this, b);
    },

    async runAllBenchmarks() {
      return window.AgentLabScenario.runAllBenchmarks(this);
    },

    stopBatchRun() {
      window.AgentLabScenario.stopBatchRun(this);
    },

    batchSummary() {
      return window.AgentLabScenario.batchSummary(this);
    },

    activeBenchmark() {
      return window.AgentLabScenario.activeBenchmark(this);
    },

    activeMassTemplate() {
      return window.AgentLabScenario.activeMassTemplate(this);
    },

    currentLesson() {
      return window.AgentLabScenario.currentLesson(this);
    },

    lockedConfig() {
      return window.AgentLabScenario.lockedConfig(this);
    },

    lockedFlag(key) {
      return window.AgentLabScenario.lockedFlag(this, key);
    },

    toolEnableLocked() {
      return window.AgentLabScenario.toolEnableLocked(this);
    },

    tabVisible(tab) {
      return window.AgentLabScenario.tabVisible(this, tab);
    },

    lessonLockSummary() {
      return window.AgentLabScenario.lessonLockSummary(this);
    },

    sideTabsStyle() {
      const tabs = 1 + (this.tabVisible('tools') ? 1 : 0) + (this.tabVisible('eval') ? 1 : 0);
      return {
        gridTemplateColumns: `repeat(${tabs}, minmax(0, 1fr))`,
      };
    },

    setMode(m) {
      window.AgentLabScenario.setMode(this, m);
    },

    enterLesson(id) {
      window.AgentLabScenario.enterLesson(this, id);
    },

    nextLessonStep() {
      window.AgentLabScenario.nextLessonStep(this);
    },

    finishLesson() {
      window.AgentLabScenario.finishLesson(this);
    },

    resetLessonProgress() {
      window.AgentLabScenario.resetLessonProgress(this);
    },

    goToNextLesson() {
      window.AgentLabScenario.goToNextLesson(this);
    },

    isLessonStepCurrent(i) {
      return window.AgentLabUI.isLessonStepCurrent(this, i);
    },

    isLessonStepDone(i) {
      return window.AgentLabUI.isLessonStepDone(this, i);
    },

    cancelRun() {
      return window.AgentLabSession.cancelRun(this);
    },

    visibleMessages() {
      return window.AgentLabUI.visibleMessages(this);
    },

    truncate(s, n) {
      return window.AgentLabUI.truncate(s, n);
    },

    renderMarkdown(md) {
      return window.AgentLabUI.renderMarkdown(md);
    },

    scrollChatBottom() {
      return window.AgentLabUI.scrollChatBottom(this);
    },

    jumpToEvent(eventId) {
      return window.AgentLabUI.jumpToEvent(this, eventId);
    },

    scrollTimelineBottom() {
      return window.AgentLabUI.scrollTimelineBottom(this);
    },

    runDiagnosis() {
      return window.AgentLabDiagnosis.run(this);
    },

    eventColor(ev) {
      return window.AgentLabTimeline.eventColor(ev);
    },

    eventBadgeClass(ev) {
      return window.AgentLabTimeline.eventBadgeClass(ev);
    },

    summarize(ev) {
      return window.AgentLabTimeline.summarize(this, ev);
    },

    filteredTimeline() {
      return window.AgentLabTimeline.filteredTimeline(this);
    },

    usageLabel(usage) {
      return window.AgentLabTimeline.usageLabel(usage);
    },
  };
})(typeof window !== 'undefined' ? window : globalThis);
