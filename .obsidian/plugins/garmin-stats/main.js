'use strict';

const { execFile } = require('child_process');
const path = require('path');
const { promisify } = require('util');
const obsidian = require('obsidian');

const execFileAsync = promisify(execFile);
const VIEW_TYPE = 'garmin-stats';

const DEFAULT_SETTINGS = {
  pythonPath: '/opt/homebrew/bin/python3',
  tokenstorePath: '',
  scriptPath: '',
  showSteps: true,
  showDistance: true,
  showActiveKcal: true,
  showRestingHR: true,
  showSleep: true,
  showSleepScore: true,
  showStress: true,
  showBodyBattery: true,
};

// ── helpers ──────────────────────────────────────────────────────────────────

function toNum(n) {
  if (typeof n === 'number' && !Number.isNaN(n)) return n;
  if (typeof n === 'string' && n.trim() !== '' && !Number.isNaN(Number(n))) return Number(n);
}

function fmtNum(n) {
  const v = toNum(n);
  if (v === undefined) return;
  return Math.abs(v - Math.round(v)) < 1e-6 ? String(Math.round(v)) : v.toFixed(1);
}

function fmtDistance(n) {
  const v = toNum(n);
  if (v === undefined) return;
  return v >= 1000 ? `${(v / 1000).toFixed(2)} km` : `${Math.round(v)} m`;
}

function fmtDuration(secs) {
  const v = toNum(secs);
  if (v === undefined || v <= 0) return;
  const h = Math.floor(v / 3600);
  const m = Math.floor((v % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function extractSleep(sleep) {
  if (!sleep) return;
  const dto = sleep.dailySleepDTO;
  for (const s of [dto?.sleepTimeSeconds, sleep.sleepTimeSeconds, sleep.sleepScores?.totalDuration]) {
    const r = fmtDuration(s);
    if (r) return r;
  }
}

function extractSleepScore(sleep) {
  if (!sleep) return;
  const scores = sleep.sleepScores;
  const v = toNum(scores?.overallScore ?? scores?.value);
  if (v !== undefined) return String(Math.round(v));
}

function extractStress(stress) {
  if (!stress) return;
  const v = toNum(stress.avgStressLevel) ?? toNum(stress.stressLevel) ?? toNum(stress.dailyStressDTO?.avgStressLevel);
  if (v !== undefined) return String(Math.round(v));
}

function extractBodyBattery(bb) {
  if (!Array.isArray(bb) || bb.length === 0) return;
  const last = bb[bb.length - 1];
  const v = toNum(last.charged) ?? toNum(last.bodyBatteryChargedValue);
  if (v !== undefined) return String(Math.round(v));
}

// ── plugin utilities ─────────────────────────────────────────────────────────

function pluginDir(plugin) {
  const adapter = plugin.app.vault.adapter;
  if (!(adapter instanceof obsidian.FileSystemAdapter)) return '';
  return path.join(adapter.getBasePath(), plugin.app.vault.configDir, 'plugins', plugin.manifest.id);
}

function scriptPath(plugin, settings) {
  return settings.scriptPath.trim() || path.join(pluginDir(plugin), 'scripts', 'fetch_garmin_stats.py');
}

async function fetchGarminData(plugin) {
  const python = plugin.settings.pythonPath.trim() || 'python3';
  const args = [scriptPath(plugin, plugin.settings)];
  if (plugin.settings.tokenstorePath.trim()) args.push('--tokenstore', plugin.settings.tokenstorePath.trim());
  try {
    const { stdout } = await execFileAsync(python, args, {
      encoding: 'utf8',
      maxBuffer: 12 * 1024 * 1024,
      timeout: 120_000,
    });
    const last = stdout.trim().split('\n').filter(Boolean).pop();
    return last ? JSON.parse(last) : { ok: false, error: 'empty_output', message: 'Python produced no output' };
  } catch (err) {
    const raw = (typeof err.stdout === 'string' && err.stdout.trim())
      || (typeof err.stderr === 'string' && err.stderr.trim())
      || (err instanceof Error ? err.message : String(err));
    try {
      const last = raw.trim().split('\n').filter(Boolean).pop();
      if (last?.startsWith('{')) return JSON.parse(last);
    } catch {}
    return { ok: false, error: 'spawn', message: raw || 'Failed to run Python helper' };
  }
}

// ── plugin ───────────────────────────────────────────────────────────────────

class GarminStatsPlugin extends obsidian.Plugin {
  constructor() {
    super(...arguments);
    this.settings = { ...DEFAULT_SETTINGS };
  }

  async onload() {
    await this.loadSettings();
    this.addSettingTab(new GarminSettingTab(this.app, this));
    this.registerView(VIEW_TYPE, leaf => new GarminStatsView(leaf, this));
    this.addRibbonIcon('activity', 'Garmin Stats', () => this.activateView());
    this.addCommand({ id: 'open-garmin-stats', name: 'Open Garmin Stats', callback: () => this.activateView() });
    this.addCommand({
      id: 'refresh-garmin-stats',
      name: 'Refresh Garmin Stats',
      callback: async () => {
        await this.activateView();
        this.refreshOpenViews();
      }
    });
  }

  refreshOpenViews() {
    for (const leaf of this.app.workspace.getLeavesOfType(VIEW_TYPE)) {
      if (leaf.view instanceof GarminStatsView) leaf.view.refresh();
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
      const right = workspace.getRightLeaf(false);
      if (right) {
        await right.setViewState({ type: VIEW_TYPE, active: true });
        leaf = right;
      } else {
        await workspace.getLeaf('tab').setViewState({ type: VIEW_TYPE, active: true });
        leaf = workspace.getLeavesOfType(VIEW_TYPE)[0];
      }
    }
    if (leaf) workspace.revealLeaf(leaf);
  }
}

// ── view ─────────────────────────────────────────────────────────────────────

class GarminStatsView extends obsidian.ItemView {
  constructor(leaf, plugin) {
    super(leaf);
    this.plugin = plugin;
  }

  getViewType() { return VIEW_TYPE; }
  getDisplayText() { return 'Garmin Stats'; }
  getIcon() { return 'activity'; }

  async onOpen() {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.addClass('gs-root');

    const panel = contentEl.createDiv({ cls: 'gs-panel' });

    // Header: title left, date·name right
    const head = panel.createDiv({ cls: 'gs-head' });
    head.createDiv({ cls: 'gs-title', text: 'Garmin Stats' });
    this.dateEl = head.createDiv({ cls: 'gs-date' });

    this.statusEl = panel.createDiv({ cls: 'gs-status' });
    this.gridEl = panel.createDiv({ cls: 'gs-grid' });
    this.footEl = panel.createDiv({ cls: 'gs-foot' });

    await this.refresh();
    this.registerInterval(window.setInterval(() => this.refresh(), 5 * 60 * 1000));
  }

  async refresh() {
    if (!this.statusEl || !this.gridEl) return;
    this.setStatus('loading');

    try {
      const data = await fetchGarminData(this.plugin);

      if (!data.ok) {
        const msg = data.message ?? data.error ?? 'Unknown error';
        this.setStatus('error', msg);
        this.gridEl.empty();
        this.footEl.setText('Run: pirate-garmin login --username EMAIL --password PASS');
        this.dateEl.setText('');
        return;
      }

      const s = this.plugin.settings;
      const summary = data.summary ?? {};
      const hr = data.heartRates ?? {};

      // Header date + name
      const namePart = data.displayName ? ` · ${data.displayName}` : '';
      this.dateEl.setText(`${data.date ?? ''}${namePart}`);

      // Build metric grid
      this.gridEl.empty();
      const metrics = [
        { key: 'showSteps',       label: 'Steps',        value: fmtNum(summary.totalSteps) },
        { key: 'showDistance',    label: 'Distance',     value: fmtDistance(summary.totalDistanceMeters) },
        { key: 'showActiveKcal',  label: 'Active kcal',  value: fmtNum(summary.activeKilocalories ?? summary.activeCalories) },
        { key: 'showRestingHR',   label: 'Resting HR',   value: fmtNum(hr.restingHeartRate ?? summary.restingHeartRate) },
        { key: 'showSleep',       label: 'Sleep',        value: extractSleep(data.sleep) },
        { key: 'showSleepScore',  label: 'Sleep score',  value: extractSleepScore(data.sleep) },
        { key: 'showStress',      label: 'Stress',       value: extractStress(data.stress) },
        { key: 'showBodyBattery', label: 'Body battery', value: extractBodyBattery(data.bodyBattery) },
      ];

      let visibleCount = 0;
      let populatedCount = 0;
      for (const { key, label, value } of metrics) {
        if (!s[key]) continue;
        visibleCount += 1;
        if (value !== undefined && value !== '') populatedCount += 1;
        const tile = this.gridEl.createDiv({ cls: 'gs-metric' });
        tile.createDiv({ cls: 'gs-label', text: label });
        tile.createDiv({ cls: 'gs-value', text: value !== undefined && value !== '' ? value : '—' });
      }

      this.setStatus('ok');
      if (visibleCount === 0) {
        this.footEl.setText('No metrics enabled. Turn some on in Garmin Stats settings.');
      } else if (populatedCount === 0) {
        this.footEl.setText('Connected, but Garmin has no stats yet for today. Try again later or choose a different date.');
      } else {
        this.footEl.setText('via pirate-garmin · refreshes every 5 min');
      }
    } catch (err) {
      this.setStatus('error', err instanceof Error ? err.message : String(err));
    }
  }

  setStatus(state, msg) {
    if (!this.statusEl) return;
    this.statusEl.removeClass('gs-status--error', 'gs-status--hidden');
    if (state === 'ok') {
      this.statusEl.addClass('gs-status--hidden');
      this.statusEl.setText('');
    } else if (state === 'loading') {
      this.statusEl.setText('Loading…');
    } else {
      this.statusEl.setText(msg ?? 'Error');
      this.statusEl.addClass('gs-status--error');
    }
  }
}

// ── settings tab ─────────────────────────────────────────────────────────────

class GarminSettingTab extends obsidian.PluginSettingTab {
  constructor(app, plugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display() {
    const { containerEl } = this;
    containerEl.empty();

    containerEl.createEl('h2', { text: 'Garmin Stats' });

    // ── Connection ──────────────────────────────────────────────────────────
    containerEl.createEl('h3', { text: 'Connection' });

    new obsidian.Setting(containerEl)
      .setName('Python executable')
      .setDesc('Must be python3. pirate-garmin binary must be in $PATH (~/.local/bin/pirate-garmin).')
      .addText(t => t
        .setPlaceholder('python3')
        .setValue(this.plugin.settings.pythonPath)
        .onChange(async v => { this.plugin.settings.pythonPath = v; await this.plugin.saveSettings(); }));

    new obsidian.Setting(containerEl)
      .setName('Token store path')
      .setDesc('Ignored — pirate-garmin uses ~/.garmin/native-oauth2.json automatically.')
      .addText(t => t
        .setPlaceholder('~/.garmin')
        .setValue(this.plugin.settings.tokenstorePath)
        .onChange(async v => { this.plugin.settings.tokenstorePath = v; await this.plugin.saveSettings(); }));

    new obsidian.Setting(containerEl)
      .setName('Custom script path')
      .setDesc('Leave empty to use the bundled fetch script.')
      .addText(t => t
        .setPlaceholder('(bundled)')
        .setValue(this.plugin.settings.scriptPath)
        .onChange(async v => { this.plugin.settings.scriptPath = v; await this.plugin.saveSettings(); }));

    new obsidian.Setting(containerEl)
      .setName('Test connection')
      .addButton(b => b.setButtonText('Fetch now').onClick(async () => {
        try {
          const d = await fetchGarminData(this.plugin);
          new obsidian.Notice(d.ok ? '✅ Garmin: connected' : `❌ Garmin: ${d.message ?? d.error ?? 'failed'}`, 6000);
        } catch (e) {
          new obsidian.Notice(e instanceof Error ? e.message : String(e), 6000);
        }
      }));

    // ── Visible metrics ─────────────────────────────────────────────────────
    containerEl.createEl('h3', { text: 'Visible metrics' });

    const toggles = [
      { key: 'showSteps',       name: 'Steps' },
      { key: 'showDistance',    name: 'Distance' },
      { key: 'showActiveKcal',  name: 'Active kcal' },
      { key: 'showRestingHR',   name: 'Resting HR' },
      { key: 'showSleep',       name: 'Sleep duration' },
      { key: 'showSleepScore',  name: 'Sleep score' },
      { key: 'showStress',      name: 'Stress (avg)' },
      { key: 'showBodyBattery', name: 'Body battery' },
    ];

    for (const { key, name } of toggles) {
      new obsidian.Setting(containerEl)
        .setName(name)
        .addToggle(t => t
          .setValue(this.plugin.settings[key])
          .onChange(async v => {
            this.plugin.settings[key] = v;
            await this.plugin.saveSettings();
            this.plugin.refreshOpenViews();
          }));
    }
  }
}

// ── exports ──────────────────────────────────────────────────────────────────

module.exports = { default: GarminStatsPlugin, VIEW_TYPE };
