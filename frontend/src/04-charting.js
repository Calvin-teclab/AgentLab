(function (root) {
  function createState() {
    return { instance: null };
  }

  function ensureState(ctx, state) {
    if (state) return state;
    if (!ctx._chartState) ctx._chartState = createState();
    return ctx._chartState;
  }

  function initChart(ctx, state) {
    state = ensureState(ctx, state);
    if (state.instance || !ctx.$refs.tokenChart) return;
    const canvas = ctx.$refs.tokenChart;
    const chartCtx = canvas.getContext('2d');
    state.instance = new Chart(chartCtx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          { label: 'prompt', data: [], borderColor: '#2dd4bf',
            backgroundColor: 'rgba(45,212,191,.12)', tension: .32, fill: true, pointRadius: 3, pointHoverRadius: 5, yAxisID: 'y' },
          { label: 'completion', data: [], borderColor: '#6ee7b7',
            backgroundColor: 'rgba(110,231,183,.10)', tension: .32, fill: true, pointRadius: 3, pointHoverRadius: 5, yAxisID: 'y' },
          { label: 'cumulative', data: [], borderColor: '#7dd3fc',
            backgroundColor: 'transparent', borderDash: [4, 4], tension: .32, fill: false, pointRadius: 2, pointHoverRadius: 4, yAxisID: 'y1' },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { intersect: false, mode: 'index' },
        plugins: {
          legend: {
            position: 'bottom',
            labels: { boxWidth: 10, color: '#66808f', font: { family: 'JetBrains Mono', size: 10 } }
          },
          tooltip: {
            backgroundColor: '#0d0f14',
            titleColor: '#e6edf3',
            bodyColor: '#9fb2c0',
            borderColor: 'rgba(45,212,191,.42)',
            borderWidth: 1,
            displayColors: true,
          },
        },
        scales: {
          y: {
            beginAtZero: true,
            position: 'left',
            border: { color: '#3e515d' },
            grid: { color: 'rgba(210,230,240,.06)' },
            ticks: { color: '#66808f', font: { family: 'JetBrains Mono', size: 10 } },
          },
          y1: {
            beginAtZero: true,
            position: 'right',
            border: { color: 'rgba(125,211,252,.45)' },
            grid: { drawOnChartArea: false },
            ticks: { color: '#7dd3fc', font: { family: 'JetBrains Mono', size: 10 } },
          },
          x: {
            border: { color: '#3e515d' },
            grid: { color: 'rgba(210,230,240,.04)' },
            ticks: { color: '#66808f', font: { family: 'JetBrains Mono', size: 10 } },
          },
        }
      }
    });
  }

  function updateChart(ctx, state) {
    state = ensureState(ctx, state);
    if (!state.instance) return;
    let cum = 0;
    const tokenData = ctx.tokenData || [];
    const cumulative = tokenData.map(d => {
      cum += (d.prompt || 0) + (d.completion || 0);
      return cum;
    });
    state.instance.data.labels = tokenData.map((d, i) => '#' + (d.callIdx ?? (i + 1)));
    state.instance.data.datasets[0].data = tokenData.map(d => d.prompt);
    state.instance.data.datasets[1].data = tokenData.map(d => d.completion);
    state.instance.data.datasets[2].data = cumulative;
    state.instance.update();
  }

  function totalTokens(ctx) {
    return (ctx.tokenData || []).reduce((s, d) => s + d.prompt + d.completion, 0);
  }

  function hasEstimatedTokens(ctx) {
    return (ctx.tokenData || []).some(d => d.estimated);
  }

  root.AgentLabCharting = {
    createState,
    initChart,
    updateChart,
    totalTokens,
    hasEstimatedTokens,
  };
})(typeof window !== 'undefined' ? window : globalThis);
