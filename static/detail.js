const chartState = {};
function renderCharts() {
  document.querySelectorAll('.chart-container').forEach(function(el) {
    const target = el.dataset.target;
    const range = el.dataset.range || '24h';
    fetch('/chart/' + encodeURIComponent(target) + '?range=' + range)
      .then(function(r) { return r.ok ? r.json() : Promise.reject(); })
      .then(function(data) {
        if (!data || !data.series) return;
        Object.keys(data.series).forEach(function(metric) {
          const canvas = document.getElementById('chart-' + target + '-' + metric);
          if (!canvas) return;
          const points = data.series[metric];
          const labels = points.map(function(p) { return p.ts; });
          const values = points.map(function(p) { return p.value; });
          const key = target + '-' + metric;
          let chart = chartState[key];
          if (!chart) {
            chart = new Chart(canvas, {
              type: 'line',
              data: {
                labels: labels,
                datasets: [{
                  label: metric,
                  data: values,
                  borderWidth: 1.5,
                  pointRadius: 2,
                  pointHoverRadius: 4,
                  tension: 0.2
                }]
              },
              options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                  x: { display: false },
                  y: { beginAtZero: true }
                }
              }
            });
            chartState[key] = chart;
          } else {
            chart.data.labels = labels;
            chart.data.datasets[0].data = values;
            chart.update('none');
          }
        });
      })
      .catch(function() {});
  });
}
document.addEventListener('DOMContentLoaded', function() {
  if (document.querySelector('.chart-container')) {
    renderCharts();
    setInterval(renderCharts, 15000);
    window._setRange = function(target, range) {
      const sel = '.chart-container[data-target="' + target + '"]';
      document.querySelectorAll(sel + ' .range-btn').forEach(function(btn) {
        btn.classList.toggle('active', btn.dataset.range === range);
      });
      const el = document.querySelector(sel);
      if (el) el.dataset.range = range;
      renderCharts();
    };
  }
});
window._loadMetricHistory = function(btn) {
  const metric = btn.dataset.metric;
  const range = btn.dataset.range;
  const block = btn.closest('.metric-block');
  const canvas = block.querySelector('canvas');
  if (!canvas) return;
  block.querySelectorAll('.range-btn').forEach(function(b) { b.classList.toggle('active', b.dataset.range === range); });
  const targetId = block.dataset.target;
  fetch('/targets/' + encodeURIComponent(targetId) + '/metrics/' + encodeURIComponent(metric) + '/history?range=' + range)
    .then(function(r) { return r.ok ? r.json() : Promise.reject(); })
    .then(function(data) {
      if (!canvas.id) return;
      const labels = (data.series || []).map(function(p) { return p.ts; });
      const values = (data.series || []).map(function(p) { return p.value; });
      let chart = window._metricCharts && window._metricCharts[canvas.id];
      if (!chart) {
        chart = new Chart(canvas, {
          type: 'line',
          data: { labels: labels, datasets: [{ label: metric, data: values, borderWidth: 1.5, pointRadius: 2, pointHoverRadius: 4, tension: 0.2 }] },
          options: { responsive: true, plugins: { legend: { display: false } }, scales: { x: { display: false }, y: { beginAtZero: true } } }
        });
        if (!window._metricCharts) window._metricCharts = {};
        window._metricCharts[canvas.id] = chart;
      } else {
        chart.data.labels = labels;
        chart.data.datasets[0].data = values;
        chart.update('none');
      }
    })
    .catch(function() {});
};
