/**
 * Health Dashboard — displays scraper health status
 *
 * Renders: last run time, job success rate, failure types, and overall health status.
 */

function renderHealthDashboard(health) {
  if (!health || Object.keys(health).length === 0) {
    return; // No health data
  }

  const container = document.getElementById('health-status-card');
  if (!container) return;

  const status = health.health_status || 'unknown';
  const successRate = health.success_rate || 100.0;
  const lastRun = health.last_run || 'Never';
  const totalJobs = health.total_jobs || 0;
  const failedJobs = health.failed_jobs || 0;
  const observationsTotal = health.observations_total || 0;
  const hoursSinceLast = health.hours_since_last_run;

  // Format last run time
  let lastRunText = lastRun;
  if (lastRun !== 'Never' && hoursSinceLast !== null) {
    if (hoursSinceLast < 1) {
      lastRunText = `${Math.round(hoursSinceLast * 60)} min ago`;
    } else if (hoursSinceLast < 24) {
      lastRunText = `${Math.round(hoursSinceLast)} hours ago`;
    } else {
      lastRunText = lastRun;
    }
  }

  // Build health status badge
  let statusLabel = status.charAt(0).toUpperCase() + status.slice(1);
  let statusIcon = '';
  if (status === 'healthy') {
    statusIcon = '✓';
  } else if (status === 'degraded') {
    statusIcon = '⚠';
  } else if (status === 'critical' || status === 'blocked') {
    statusIcon = '✕';
  } else {
    statusIcon = '?';
  }

  let html = `
    <div class="health-metric">
      <div class="health-metric__label">Status</div>
      <div class="health-status-badge ${status}">
        ${statusIcon} ${statusLabel}
      </div>
    </div>
    <div class="health-metric">
      <div class="health-metric__label">Success Rate</div>
      <div class="health-metric__value status-${status}">
        ${successRate.toFixed(1)}%
      </div>
    </div>
    <div class="health-metric">
      <div class="health-metric__label">Jobs (Last Run)</div>
      <div class="health-metric__value">
        ${totalJobs - failedJobs}/${totalJobs}
      </div>
    </div>
    <div class="health-metric">
      <div class="health-metric__label">Observations</div>
      <div class="health-metric__value">
        ${observationsTotal.toLocaleString()}
      </div>
    </div>
    <div class="health-metric">
      <div class="health-metric__label">Last Run</div>
      <div class="health-metric__value" style="font-size: 0.95rem;">
        ${lastRunText}
      </div>
    </div>
  `;

  // Add failure breakdown if there are failures
  const failuresByKind = health.failures_by_kind || {};
  const hasFailures = Object.values(failuresByKind).some(v => v > 0);

  if (hasFailures) {
    html += '<div class="health-metric" style="grid-column: 1 / -1;">';
    html += '<div class="health-metric__label">Failure Types</div>';
    html += '<div style="display: flex; gap: 1rem; flex-wrap: wrap; justify-content: center; margin-top: 0.5rem;">';

    const failureMap = {
      bot_challenge: 'Bot Challenge',
      rate_limited: 'Rate Limited',
      parse_error: 'Parse Error',
      network: 'Network',
      other: 'Other',
    };

    for (const [key, label] of Object.entries(failureMap)) {
      const count = failuresByKind[key] || 0;
      if (count > 0) {
        html += `<span style="background: #f5f5f5; padding: 0.4rem 0.8rem; border-radius: 4px; font-size: 0.85rem;">
          ${label}: <strong>${count}</strong>
        </span>`;
      }
    }

    html += '</div>';
    html += '</div>';
  }

  container.innerHTML = html;
}

// Export for use in main app
if (typeof window !== 'undefined') {
  window.renderHealthDashboard = renderHealthDashboard;
}
