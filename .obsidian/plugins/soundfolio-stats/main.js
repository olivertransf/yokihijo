'use strict';

const { execFile } = require('child_process');
const path = require('path');
const { promisify } = require('util');
const obsidian = require('obsidian');

const execFileAsync = promisify(execFile);
const VIEW_TYPE = 'soundfolio-stats';

const DEFAULT_SETTINGS = {
  pythonPath: '/opt/homebrew/bin/python3',
  scriptPath: '',
  envPath: '/Users/olivertran/Documents/Projects/SpotifyStats/.env',
  defaultRange: '30d',
  defaultGranularity: 'weeks',
};

const RANGES = ['30d', '3m', '6m', '1y', 'all'];
const RANGE_LABELS = { '30d': '30 days', '3m': '3 months', '6m': '6 months', '1y': '1 year', 'all': 'All time' };
const GRAN_LABELS = { weeks: 'Weekly', months: 'Monthly', days: 'Daily' };

// ── helpers ──────────────────────────────────────────────────────────────────

function fmtMinutes(mins) {
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60), m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

function fmtNum(n) {
  return typeof n === 'number' ? n.toLocaleString() : String(n ?? '—');
}

function pluginDir(plugin) {
  const adapter = plugin.app.vault.adapter;
  if (!(adapter instanceof obsidian.FileSystemAdapter)) return '';
  return path.join(adapter.getBasePath(), plugin.app.vault.configDir, 'plugins', plugin.manifest.id);
}

function resolveScriptPath(plugin) {
  return plugin.settings.scriptPath.trim()
    || path.join(pluginDir(plugin), 'scripts', 'soundfolio_json.py');
}

async function fetchStats(plugin, range, granularity) {
  const python = plugin.settings.pythonPath.trim() || 'python3';
  const script = resolveScriptPath(plugin);
  const args = [script, '--range', range, '--granularity', granularity];
  const envPath = plugin.settings.envPath?.trim();
  if (envPath) args.push('--env', envPath);

  try {
    const { stdout } = await execFileAsync(python, args,
      { encoding: 'utf8', maxBuffer: 8 * 1024 * 1024, timeout: 60_000 }
    );
    const last = stdout.trim().split('\n').filter(Boolean).pop();
    return last ? JSON.parse(last) : { ok: false, error: 'Empty output from Python' };
  } catch (err) {
    const raw = (err.stdout || err.stderr || err.message || String(err)).trim();
    try {
      const last = raw.split('\n').filter(Boolean).pop();
      if (last?.startsWith('{')) return JSON.parse(last);
    } catch {}
    return { ok: false, error: raw || 'Failed to run Python helper' };
  }
}

// ── SVG bar chart ─────────────────────────────────────────────────────────────

function buildActivityChart(history, metric, width) {
  if (!history || history.length === 0) return '<p class="sf-empty">No data for this period.</p>';

  const W = width || 500;
  const H = 180;
  const padL = 38, padR = 8, padT = 12, padB = 28;
  const chartW = W - padL - padR;
  const chartH = H - padT - padB;
  const values = history.map(p => p[metric] ?? 0);
  const maxVal = Math.max(...values, 1);

  const barW = Math.max(2, Math.floor(chartW / history.length) - 2);
  const gap = Math.floor(chartW / history.length);

  // Y axis labels
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map(f => Math.round(maxVal * f));
  const yLines = yTicks.map(v => {
    const y = padT + chartH - Math.round((v / maxVal) * chartH);
    const label = metric === 'minutes' ? fmtMinutes(v) : String(v);
    return `
      <line x1="${padL}" x2="${padL + chartW}" y1="${y}" y2="${y}"
            stroke="var(--background-modifier-border)" stroke-width="1" opacity="0.5"/>
      <text x="${padL - 4}" y="${y + 4}" text-anchor="end"
            class="sf-chart-tick">${label}</text>`;
  }).join('');

  // Bars
  const bars = history.map((p, i) => {
    const x = padL + i * gap + Math.floor((gap - barW) / 2);
    const barH = Math.max(1, Math.round((p[metric] / maxVal) * chartH));
    const y = padT + chartH - barH;
    const tooltipVal = metric === 'minutes' ? fmtMinutes(p[metric]) : fmtNum(p[metric]);
    return `<rect x="${x}" y="${y}" width="${barW}" height="${barH}"
                  rx="2" class="sf-chart-bar">
              <title>${p.label}: ${tooltipVal}</title>
            </rect>`;
  }).join('');

  // X labels (show max 8 evenly spaced)
  const step = Math.max(1, Math.ceil(history.length / 8));
  const xLabels = history.map((p, i) => {
    if (i % step !== 0 && i !== history.length - 1) return '';
    const x = padL + i * gap + gap / 2;
    const short = p.label.length > 7 ? p.label.slice(2) : p.label;
    return `<text x="${x}" y="${H - 4}" text-anchor="middle" class="sf-chart-tick">${short}</text>`;
  }).join('');

  return `
    <svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" class="sf-activity-svg" preserveAspectRatio="none">
      ${yLines}
      ${bars}
      ${xLabels}
    </svg>`;
}

// ── plugin ───────────────────────────────────────────────────────────────────

class SoundfolioPlugin extends obsidian.Plugin {
  constructor() {
    super(...arguments);
    this.settings = { ...DEFAULT_SETTINGS };
  }

  async onload() {
    await this.loadSettings();
    this.addSettingTab(new SoundfolioSettingTab(this.app, this));
    this.registerView(VIEW_TYPE, leaf => new SoundfolioView(leaf, this));
    this.addRibbonIcon('music', 'Soundfolio Stats', () => this.activateView());
    this.addCommand({ id: 'open-soundfolio', name: 'Open Soundfolio Stats', callback: () => this.activateView() });
    this.addCommand({ id: 'refresh-soundfolio', name: 'Refresh Soundfolio Stats', callback: () => this.refreshOpenViews() });
  }

  refreshOpenViews() {
    for (const leaf of this.app.workspace.getLeavesOfType(VIEW_TYPE)) {
      if (leaf.view instanceof SoundfolioView) leaf.view.refresh();
    }
  }

  async loadSettings() {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }

  async activateView() {
    const { workspace } = this.app;
    let leaf = workspace.getLeavesOfType(VIEW_TYPE)[0];
    if (!leaf) {
      leaf = workspace.getLeaf('tab');
      await leaf.setViewState({ type: VIEW_TYPE, active: true });
    }
    workspace.revealLeaf(leaf);
  }
}

// ── view ─────────────────────────────────────────────────────────────────────

class SoundfolioView extends obsidian.ItemView {
  constructor(leaf, plugin) {
    super(leaf);
    this.plugin = plugin;
    this.range = plugin.settings.defaultRange;
    this.granularity = plugin.settings.defaultGranularity;
    this.chartMetric = 'minutes';
  }

  getViewType()    { return VIEW_TYPE; }
  getDisplayText() { return 'Soundfolio'; }
  getIcon()        { return 'music'; }

  async onOpen() {
    this.buildShell();
    await this.refresh();
    this.registerInterval(window.setInterval(() => this.refresh(), 10 * 60 * 1000));
  }

  buildShell() {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.addClass('sf-root');

    this.scrollEl = contentEl.createDiv({ cls: 'sf-scroll' });
    const wrap = this.scrollEl.createDiv({ cls: 'sf-wrap' });

    // ── Page header ─────────────────────────────────────────────────────────
    const ph = wrap.createDiv({ cls: 'sf-page-header' });
    const phLeft = ph.createDiv({ cls: 'sf-page-header-left' });
    phLeft.createEl('h1', { cls: 'sf-page-title', text: 'Overview' });
    this.periodLabelEl = phLeft.createDiv({ cls: 'sf-page-subtitle', text: '' });
    this.latestPlayEl = ph.createDiv({ cls: 'sf-latest-play', text: '' });

    // ── Time range tabs ──────────────────────────────────────────────────────
    const tabRow = wrap.createDiv({ cls: 'sf-tab-row' });
    this.rangeTabs = tabRow.createDiv({ cls: 'sf-tabs' });
    for (const r of RANGES) {
      const btn = this.rangeTabs.createEl('button', { cls: 'sf-tab', text: RANGE_LABELS[r] });
      if (r === this.range) btn.addClass('sf-tab--active');
      btn.addEventListener('click', () => {
        this.range = r;
        this.rangeTabs.querySelectorAll('.sf-tab').forEach(b => b.removeClass('sf-tab--active'));
        btn.addClass('sf-tab--active');
        this.refresh();
      });
    }
    this.refreshBtn = tabRow.createEl('button', { cls: 'sf-btn-icon', text: '↻' });
    this.refreshBtn.title = 'Refresh';
    this.refreshBtn.addEventListener('click', () => this.refresh());

    // ── Status bar ──────────────────────────────────────────────────────────
    this.statusEl = wrap.createDiv({ cls: 'sf-status sf-status--hidden' });

    // ── Stat cards ───────────────────────────────────────────────────────────
    this.cardsEl = wrap.createDiv({ cls: 'sf-cards' });

    // ── Activity chart section ───────────────────────────────────────────────
    const actSection = wrap.createDiv({ cls: 'sf-section' });
    const actHeader = actSection.createDiv({ cls: 'sf-section-head' });
    this.actTitleEl = actHeader.createDiv({ cls: 'sf-section-title', text: 'Minutes listened · Weekly' });
    const actControls = actHeader.createDiv({ cls: 'sf-section-controls' });

    // Granularity selector
    this.granSelect = actControls.createEl('select', { cls: 'sf-select' });
    for (const [k, v] of Object.entries(GRAN_LABELS)) {
      const opt = this.granSelect.createEl('option', { value: k, text: v });
      if (k === this.granularity) opt.selected = true;
    }
    this.granSelect.addEventListener('change', () => {
      this.granularity = this.granSelect.value;
      this.actTitleEl.setText(`Minutes listened · ${GRAN_LABELS[this.granularity]}`);
      this.refresh();
    });

    // Metric toggle
    const toggle = actControls.createDiv({ cls: 'sf-metric-toggle' });
    for (const [k, label] of [['minutes', 'Minutes'], ['streams', 'Streams']]) {
      const btn = toggle.createEl('button', { cls: 'sf-toggle-btn', text: label });
      if (k === this.chartMetric) btn.addClass('sf-toggle-btn--active');
      btn.addEventListener('click', () => {
        this.chartMetric = k;
        toggle.querySelectorAll('.sf-toggle-btn').forEach(b => b.removeClass('sf-toggle-btn--active'));
        btn.addClass('sf-toggle-btn--active');
        if (this._lastData) this.renderChart(this._lastData);
      });
    }

    this.chartEl = actSection.createDiv({ cls: 'sf-chart-wrap' });

    // ── Top Tracks + Top Artists grid ────────────────────────────────────────
    this.gridEl = wrap.createDiv({ cls: 'sf-top-grid' });

    // ── Updated ─────────────────────────────────────────────────────────────
    this.updatedEl = wrap.createDiv({ cls: 'sf-updated', text: '' });
  }

  async refresh() {
    if (!this.statusEl) return;
    this.setStatus('loading', 'Fetching from Neon…');
    this.refreshBtn?.addClass('sf-spinning');

    try {
      const data = await fetchStats(this.plugin, this.range, this.granularity);
      this.refreshBtn?.removeClass('sf-spinning');

      if (!data.ok) {
        this.setStatus('error', data.error || 'Unknown error');
        return;
      }

      this._lastData = data;
      this.setStatus('ok');
      this.renderAll(data);
    } catch (err) {
      this.refreshBtn?.removeClass('sf-spinning');
      this.setStatus('error', err.message || String(err));
    }
  }

  renderAll(data) {
    this.renderHeader(data);
    this.renderCards(data);
    this.renderChart(data);
    this.renderTopGrid(data);
    this.updatedEl.setText(`Updated ${new Date().toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`);
  }

  renderHeader(data) {
    this.periodLabelEl.setText(`Listening volume, diversity, and trends · ${RANGE_LABELS[data.range]}`);
    if (data.span?.last) {
      const d = new Date(data.span.last + 'T00:00:00');
      const ago = Math.floor((Date.now() - d.getTime()) / 86400000);
      const str = ago === 0 ? 'today' : ago === 1 ? 'yesterday' : `${ago} days ago`;
      this.latestPlayEl.setText(`Latest play ${str}`);
    }
  }

  renderCards(data) {
    const el = this.cardsEl;
    el.empty();
    const defs = [
      { label: 'Total minutes',    value: fmtNum(data.totals.minutes), sub: `${fmtNum(data.totals.hours)} h total` },
      { label: 'Total streams',    value: fmtNum(data.totals.streams), sub: null },
      { label: 'Unique tracks',    value: fmtNum(data.unique.tracks),  sub: 'Distinct songs played' },
      { label: 'Unique artists',   value: fmtNum(data.unique.artists), sub: 'Distinct artists' },
      { label: 'Avg min / day',    value: fmtNum(data.avgs.minutesPerDay), sub: `~${fmtNum(data.avgs.daysInPeriod)} day window` },
      { label: 'Avg streams / day',value: fmtNum(data.avgs.streamsPerDay), sub: null },
    ];
    for (const c of defs) {
      const card = el.createDiv({ cls: 'sf-card' });
      const inner = card.createDiv({ cls: 'sf-card-inner' });
      const left = inner.createDiv({ cls: 'sf-card-left' });
      left.createDiv({ cls: 'sf-card-label', text: c.label });
      left.createDiv({ cls: 'sf-card-value', text: c.value });
      if (c.sub) left.createDiv({ cls: 'sf-card-sub', text: c.sub });
    }
  }

  renderChart(data) {
    const el = this.chartEl;
    el.empty();
    this.actTitleEl.setText(`${this.chartMetric === 'minutes' ? 'Minutes listened' : 'Streams'} · ${GRAN_LABELS[this.granularity]}`);
    el.innerHTML = buildActivityChart(data.history, this.chartMetric, el.clientWidth || 480);
  }

  renderTopGrid(data) {
    const el = this.gridEl;
    el.empty();

    // Top Tracks
    const tracksCard = el.createDiv({ cls: 'sf-top-card' });
    tracksCard.createEl('h3', { cls: 'sf-top-title', text: 'Top tracks' });
    const tracksList = tracksCard.createDiv({ cls: 'sf-top-list' });
    for (const [i, t] of data.tracks.entries()) {
      const row = tracksList.createDiv({ cls: 'sf-top-row' });
      row.createDiv({ cls: 'sf-top-rank', text: String(i + 1) });
      const art = row.createDiv({ cls: 'sf-art sf-art--square' });
      if (t.art) {
        const img = art.createEl('img', { cls: 'sf-art-img' });
        img.src = t.art;
        img.alt = t.album || '';
        img.loading = 'lazy';
      }
      const info = row.createDiv({ cls: 'sf-top-info' });
      info.createDiv({ cls: 'sf-top-name', text: t.name });
      info.createDiv({ cls: 'sf-top-sub', text: t.artist });
      row.createDiv({ cls: 'sf-top-count', text: `${fmtNum(t.streams)} plays` });
    }

    // Top Artists
    const artistsCard = el.createDiv({ cls: 'sf-top-card' });
    artistsCard.createEl('h3', { cls: 'sf-top-title', text: 'Top artists' });
    const artistsList = artistsCard.createDiv({ cls: 'sf-top-list' });
    for (const [i, a] of data.artists.entries()) {
      const row = artistsList.createDiv({ cls: 'sf-top-row' });
      row.createDiv({ cls: 'sf-top-rank', text: String(i + 1) });
      const art = row.createDiv({ cls: 'sf-art sf-art--round' });
      if (a.art) {
        const img = art.createEl('img', { cls: 'sf-art-img' });
        img.src = a.art;
        img.alt = a.name;
        img.loading = 'lazy';
      }
      const info = row.createDiv({ cls: 'sf-top-info' });
      info.createDiv({ cls: 'sf-top-name', text: a.name });
      info.createDiv({ cls: 'sf-top-sub', text: `${fmtMinutes(a.minutes)} listened` });
      row.createDiv({ cls: 'sf-top-count', text: `${fmtNum(a.streams)} plays` });
    }
  }

  setStatus(state, msg) {
    if (!this.statusEl) return;
    this.statusEl.removeClass('sf-status--hidden', 'sf-status--error', 'sf-status--loading');
    if (state === 'ok') {
      this.statusEl.addClass('sf-status--hidden');
    } else if (state === 'loading') {
      this.statusEl.setText(msg ?? 'Loading…');
      this.statusEl.addClass('sf-status--loading');
    } else {
      this.statusEl.setText(msg ?? 'Error');
      this.statusEl.addClass('sf-status--error');
    }
  }
}

// ── settings tab ─────────────────────────────────────────────────────────────

class SoundfolioSettingTab extends obsidian.PluginSettingTab {
  constructor(app, plugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display() {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl('h2', { text: 'Soundfolio Stats' });

    new obsidian.Setting(containerEl)
      .setName('Python executable')
      .setDesc('Path to python3 with psycopg2 and python-dotenv installed.')
      .addText(t => t
        .setPlaceholder('/opt/homebrew/bin/python3')
        .setValue(this.plugin.settings.pythonPath)
        .onChange(async v => { this.plugin.settings.pythonPath = v; await this.plugin.saveSettings(); }));

    new obsidian.Setting(containerEl)
      .setName('.env file path')
      .setDesc('Path to the SpotifyStats .env containing DATABASE_URL.')
      .addText(t => t
        .setPlaceholder('/path/to/SpotifyStats/.env')
        .setValue(this.plugin.settings.envPath)
        .onChange(async v => { this.plugin.settings.envPath = v; await this.plugin.saveSettings(); }));

    new obsidian.Setting(containerEl)
      .setName('Custom script path')
      .setDesc('Leave empty to use the bundled script.')
      .addText(t => t
        .setPlaceholder('(bundled)')
        .setValue(this.plugin.settings.scriptPath)
        .onChange(async v => { this.plugin.settings.scriptPath = v; await this.plugin.saveSettings(); }));

    new obsidian.Setting(containerEl)
      .setName('Default time range')
      .addDropdown(d => {
        for (const r of RANGES) d.addOption(r, RANGE_LABELS[r]);
        d.setValue(this.plugin.settings.defaultRange);
        d.onChange(async v => { this.plugin.settings.defaultRange = v; await this.plugin.saveSettings(); });
      });

    new obsidian.Setting(containerEl)
      .setName('Default granularity')
      .addDropdown(d => {
        for (const [k, v] of Object.entries(GRAN_LABELS)) d.addOption(k, v);
        d.setValue(this.plugin.settings.defaultGranularity);
        d.onChange(async v => { this.plugin.settings.defaultGranularity = v; await this.plugin.saveSettings(); });
      });

    new obsidian.Setting(containerEl)
      .setName('Test connection')
      .addButton(b => b.setButtonText('Fetch now').onClick(async () => {
        try {
          const d = await fetchStats(this.plugin, '30d', 'weeks');
          new obsidian.Notice(
            d.ok ? `✅ Connected — ${d.totals?.streams} streams` : `❌ ${d.error}`,
            6000
          );
        } catch (e) {
          new obsidian.Notice(e.message || String(e), 6000);
        }
      }));
  }
}

module.exports = { default: SoundfolioPlugin };
