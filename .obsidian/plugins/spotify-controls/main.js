'use strict';

const { Plugin, Notice, ItemView, PluginSettingTab, Setting } = require('obsidian');
const { exec, execFile } = require('child_process');

const VIEW_TYPE = 'spotify-controls-view';

const DEFAULT_PLAYLISTS = [
  { name: 'On Repeat', url: 'https://open.spotify.com/playlist/37i9dQZF1Epss3zwhy7VRW' },
  { name: 'Spanish Pop Mix', url: 'https://open.spotify.com/playlist/37i9dQZF1EIfDaAjvyftbX' },
  { name: 'The Sublime', url: 'https://open.spotify.com/playlist/2L5Jaqz7bdThdLvYbi0GyN' },
  { name: 'Chill Mix', url: 'https://open.spotify.com/playlist/37i9dQZF1EVHGWrwldPRtj' },
  { name: 'Daily Mix 1', url: 'https://open.spotify.com/playlist/37i9dQZF1E35NCTJbBabFt' },
  { name: 'Modern Jazz Mix', url: 'https://open.spotify.com/playlist/37i9dQZF1EIfD76SANX498' },
  { name: 'homework vibes', url: 'https://open.spotify.com/playlist/37i9dQZF1DX3csziQj0d5b' },
  { name: 'Pop Mix', url: 'https://open.spotify.com/playlist/37i9dQZF1EQncLwOalG3K7' },
];

const DEFAULT_SETTINGS = {
  playlists: DEFAULT_PLAYLISTS,
  /** After switching playlist, run `open -b md.obsidian` so Obsidian comes forward again. */
  restoreFocusAfterPlaylist: true,
};

const OBSIDIAN_BUNDLE_ID = 'md.obsidian';

function runAppleScript(script) {
  return new Promise((resolve, reject) => {
    exec(`osascript -e '${script.replace(/'/g, "'\\''")}'`, (err, stdout, stderr) => {
      if (err) reject(stderr || err.message);
      else resolve(stdout.trim());
    });
  });
}

/** True only if Spotify.app is already running — avoids `tell application "Spotify"` relaunching it. */
const isSpotifyProcessRunningScript =
  'tell application "System Events" to return ((count of (every application process whose name is "Spotify")) > 0)';

async function isSpotifyRunning() {
  try {
    const out = await runAppleScript(isSpotifyProcessRunningScript);
    return out === 'true';
  } catch {
    return false;
  }
}

function toSpotifyPlaylistUri(input) {
  const s = String(input || '').trim();
  if (!s) return '';
  if (/^spotify:playlist:[a-zA-Z0-9]+$/i.test(s)) return s;
  const m = s.match(/playlist\/([a-zA-Z0-9]+)/);
  if (m) return `spotify:playlist:${m[1]}`;
  return '';
}

function playlistsToText(rows) {
  return (rows || []).map((r) => `${r.name} | ${r.url}`).join('\n');
}

function textToPlaylists(text) {
  const lines = String(text || '').split('\n');
  const out = [];
  for (const line of lines) {
    const t = line.trim();
    if (!t) continue;
    const pipe = t.indexOf('|');
    if (pipe === -1) continue;
    const name = t.slice(0, pipe).trim();
    const url = t.slice(pipe + 1).trim();
    if (name && url && toSpotifyPlaylistUri(url)) out.push({ name, url });
  }
  return out.length ? out : DEFAULT_PLAYLISTS.slice();
}

function escapeAppleScriptString(s) {
  return String(s).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
}

function playPlaylistAppleScript(uri) {
  const u = escapeAppleScriptString(uri);
  return `tell application "Spotify" to play track "${u}"`;
}

/** macOS built-in: `open -b md.obsidian` */
function openObsidian() {
  return new Promise((resolve, reject) => {
    execFile('open', ['-b', OBSIDIAN_BUNDLE_ID], { timeout: 5000 }, (err, stdout, stderr) => {
      if (err) reject(stderr || err.message);
      else resolve(String(stdout || '').trim());
    });
  });
}

const S = {
  playpause:    `tell application "Spotify" to playpause`,
  next:         `tell application "Spotify" to next track`,
  prev:         `tell application "Spotify" to previous track`,
  track:        `tell application "Spotify" to get name of current track`,
  artist:       `tell application "Spotify" to get artist of current track`,
  album:        `tell application "Spotify" to get album of current track`,
  artwork:      `tell application "Spotify" to get artwork url of current track`,
  state:        `tell application "Spotify" to get player state`,
  position:     `tell application "Spotify" to get player position`,
  duration:     `tell application "Spotify" to get duration of current track`,
  volGet:       `tell application "Spotify" to get sound volume`,
  volSet: (v)  => `tell application "Spotify" to set sound volume to ${v}`,
  shuffleGet:   `tell application "Spotify" to get shuffling`,
  shuffleSet:(v)=> `tell application "Spotify" to set shuffling to ${v}`,
};


class SpotifyView extends ItemView {
  constructor(leaf, plugin) {
    super(leaf);
    this.plugin = plugin;
    this.state = { track: '', artist: '', album: '', artwork: '', playing: false, position: 0, duration: 0, volume: 50, shuffle: false };
    this.pollInterval = null;
  }

  getViewType() { return VIEW_TYPE; }
  getDisplayText() { return 'Spotify'; }
  getIcon() { return 'music'; }

  async onOpen() {
    this.render();
    this.pollInterval = window.setInterval(() => this.poll(), 3000);
    this.poll();
  }

  async onClose() {
    if (this.pollInterval) window.clearInterval(this.pollInterval);
  }

  render() {
    const root = this.containerEl.children[1];
    root.empty();
    root.addClass('sp-root');
    const SVG = {
      shuffle: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="4" y1="4" x2="9" y2="9"/></svg>`,
      prev:    `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="19 20 9 12 19 4 19 20"/><rect x="4" y="4" width="3" height="16" rx="1"/></svg>`,
      play:    `<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>`,
      pause:   `<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg>`,
      next:    `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 4 15 12 5 20 5 4"/><rect x="17" y="4" width="3" height="16" rx="1"/></svg>`,
      volLow:  `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>`,
      volHigh: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>`,
      music:   `<svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>`,
    };
    root.innerHTML = `
      <div class="sp-wrap">
        <div class="sp-artwork-wrap">
          <img class="sp-artwork" src="" alt="" />
          <div class="sp-artwork-placeholder">${SVG.music}</div>
        </div>
        <div class="sp-meta">
          <div class="sp-track" title=""></div>
          <div class="sp-artist"></div>
          <div class="sp-album"></div>
        </div>
        <div class="sp-playlist-row">
          <label class="sp-playlist-label" for="sp-playlist-select">Playlist</label>
          <select class="dropdown sp-playlist-select" id="sp-playlist-select">
            <option value="">Play playlist…</option>
          </select>
        </div>
        <div class="sp-progress-wrap">
          <span class="sp-time sp-pos">0:00</span>
          <div class="sp-progress-track"><div class="sp-progress-fill"></div></div>
          <span class="sp-time sp-dur">0:00</span>
        </div>
        <div class="sp-controls">
          <button class="sp-btn sp-shuffle" title="Shuffle">${SVG.shuffle}</button>
          <button class="sp-btn sp-prev" title="Previous">${SVG.prev}</button>
          <button class="sp-btn sp-playpause sp-primary" title="Play/Pause">${SVG.play}</button>
          <button class="sp-btn sp-next" title="Next">${SVG.next}</button>
        </div>
        <div class="sp-vol-wrap">
          <span class="sp-vol-icon">${SVG.volLow}</span>
          <input class="sp-vol" type="range" min="0" max="100" value="50" />
          <span class="sp-vol-icon">${SVG.volHigh}</span>
        </div>
      </div>`;
    this.fillPlaylistSelect(root);
    this.bindEvents(root);
  }

  fillPlaylistSelect(root) {
    const sel = root.querySelector('.sp-playlist-select');
    if (!sel) return;
    const playlists = this.plugin.settings?.playlists || DEFAULT_PLAYLISTS;
    sel.innerHTML = '<option value="">Play playlist…</option>';
    for (const p of playlists) {
      const uri = toSpotifyPlaylistUri(p.url);
      if (!uri) continue;
      const opt = document.createElement('option');
      opt.value = uri;
      opt.textContent = p.name;
      sel.appendChild(opt);
    }
  }

  bindEvents(root) {
    root.querySelector('.sp-playpause').addEventListener('click', async () => {
      await runAppleScript(S.playpause).catch(() => {});
      setTimeout(() => this.poll(), 150);
    });
    root.querySelector('.sp-next').addEventListener('click', async () => {
      await runAppleScript(S.next).catch(() => {});
      setTimeout(() => this.poll(), 500);
    });
    root.querySelector('.sp-prev').addEventListener('click', async () => {
      await runAppleScript(S.prev).catch(() => {});
      setTimeout(() => this.poll(), 500);
    });
    root.querySelector('.sp-shuffle').addEventListener('click', async () => {
      const next = !this.state.shuffle;
      await runAppleScript(S.shuffleSet(next)).catch(() => {});
      this.state.shuffle = next;
      this.updateShuffleBtn(root);
    });
    const vol = root.querySelector('.sp-vol');
    vol.addEventListener('input', async () => {
      await runAppleScript(S.volSet(vol.value)).catch(() => {});
      this.state.volume = parseInt(vol.value);
    });
    const playlistSel = root.querySelector('.sp-playlist-select');
    playlistSel.addEventListener('change', async () => {
      const uri = playlistSel.value;
      playlistSel.value = '';
      if (!uri) return;
      try {
        await runAppleScript(playPlaylistAppleScript(uri));
        const refocus = this.plugin.settings.restoreFocusAfterPlaylist !== false;
        if (refocus) {
          await openObsidian().catch(() => {});
        }
        new Notice('Playing playlist');
        setTimeout(() => this.poll(), 600);
      } catch (e) {
        new Notice('Could not start playlist: ' + (e || 'error'), 4000);
      }
    });
  }


  async poll() {
    try {
      if (!(await isSpotifyRunning())) {
        this.state = {
          track: '',
          artist: '',
          album: '',
          artwork: '',
          playing: false,
          position: 0,
          duration: 0,
          volume: this.state?.volume ?? 50,
          shuffle: false,
        };
        this.updateUI();
        return;
      }
      const [track, artist, album, artwork, playerState, pos, dur, vol, shuffle] = await Promise.all([
        runAppleScript(S.track),
        runAppleScript(S.artist),
        runAppleScript(S.album),
        runAppleScript(S.artwork),
        runAppleScript(S.state),
        runAppleScript(S.position),
        runAppleScript(S.duration),
        runAppleScript(S.volGet),
        runAppleScript(S.shuffleGet),
      ]);
      this.state = {
        track, artist, album, artwork,
        playing: playerState === 'playing',
        position: parseFloat(pos) || 0,
        duration: (parseInt(dur) || 0) / 1000,
        volume: parseInt(vol) || 50,
        shuffle: shuffle === 'true',
      };
      this.updateUI();
    } catch {}
  }

  updateUI() {
    const root = this.containerEl.children[1];
    if (!root) return;
    const { track, artist, album, artwork, playing, position, duration, volume, shuffle } = this.state;

    // Artwork
    const img = root.querySelector('.sp-artwork');
    const placeholder = root.querySelector('.sp-artwork-placeholder');
    if (artwork && artwork.startsWith('http')) {
      img.src = artwork;
      img.style.display = 'block';
      placeholder.style.display = 'none';
    } else {
      img.style.display = 'none';
      placeholder.style.display = 'flex';
    }

    // Meta
    const trackEl = root.querySelector('.sp-track');
    trackEl.textContent = track || '—';
    trackEl.title = track || '';
    root.querySelector('.sp-artist').textContent = artist || '';
    root.querySelector('.sp-album').textContent = album || '';

    // Play/pause button
    const playSVG = `<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>`;
    const pauseSVG = `<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg>`;
    root.querySelector('.sp-playpause').innerHTML = playing ? pauseSVG : playSVG;

    // Progress
    const pct = duration > 0 ? (position / duration) * 100 : 0;
    root.querySelector('.sp-progress-fill').style.width = `${pct}%`;
    root.querySelector('.sp-pos').textContent = this.fmt(position);
    root.querySelector('.sp-dur').textContent = this.fmt(duration);

    // Volume
    root.querySelector('.sp-vol').value = volume;

    // Shuffle
    this.updateShuffleBtn(root);
  }

  updateShuffleBtn(root) {
    const btn = root.querySelector('.sp-shuffle');
    btn.classList.toggle('sp-active', this.state.shuffle);
  }

  fmt(sec) {
    const s = Math.floor(sec);
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }
}

class SpotifyControlsSettingTab extends PluginSettingTab {
  constructor(app, plugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display() {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl('h2', { text: 'Spotify Controls' });
    new Setting(containerEl)
      .setName('Open Obsidian after playlist')
      .setDesc('Runs `open -b md.obsidian` after Spotify starts the playlist so Obsidian is front again. Spotify may still flash briefly.')
      .addToggle((t) => {
        t.setValue(this.plugin.settings.restoreFocusAfterPlaylist !== false);
        t.onChange(async (v) => {
          this.plugin.settings.restoreFocusAfterPlaylist = v;
          await this.plugin.saveSettings();
        });
      });
    new Setting(containerEl)
      .setName('Playlist presets')
      .setDesc('One per line: name | URL (open.spotify.com or spotify:playlist:…). Used by the player dropdown.')
      .addTextArea((ta) => {
        ta.inputEl.rows = 12;
        ta.inputEl.cols = 60;
        ta.setValue(playlistsToText(this.plugin.settings.playlists));
        ta.onChange(async (v) => {
          this.plugin.settings.playlists = textToPlaylists(v);
          await this.plugin.saveSettings();
        });
      });
  }
}

class SpotifyControlsPlugin extends Plugin {
  async onload() {
    await this.loadSettings();
    this.registerView(VIEW_TYPE, (leaf) => new SpotifyView(leaf, this));
    this.addSettingTab(new SpotifyControlsSettingTab(this.app, this));

    this.addCommand({
      id: 'open-player',
      name: 'Open Player',
      callback: () => this.activateView(),
    });
    this.addCommand({ id: 'playpause', name: 'Play / Pause', callback: () => runAppleScript(S.playpause).catch(() => {}) });
    this.addCommand({ id: 'next-track', name: 'Next Track', callback: () => runAppleScript(S.next).catch(() => {}) });
    this.addCommand({ id: 'prev-track', name: 'Previous Track', callback: () => runAppleScript(S.prev).catch(() => {}) });

    // Status bar
    this.statusBarItem = this.addStatusBarItem();
    this.statusBarItem.addClass('sp-statusbar');
    this.statusBarItem.onClickEvent(() => this.activateView());
    this.registerInterval(window.setInterval(() => this.updateStatusBar(), 5000));
    this.updateStatusBar();

    console.log('Spotify Controls loaded');
  }

  async loadSettings() {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
    if (!Array.isArray(this.settings.playlists) || !this.settings.playlists.length) {
      this.settings.playlists = DEFAULT_PLAYLISTS.slice();
    }
    if (typeof this.settings.restoreFocusAfterPlaylist !== 'boolean') {
      this.settings.restoreFocusAfterPlaylist = DEFAULT_SETTINGS.restoreFocusAfterPlaylist;
    }
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }

  async activateView() {
    const { workspace } = this.app;
    let leaf = workspace.getLeavesOfType(VIEW_TYPE)[0];
    if (!leaf) {
      leaf = workspace.getRightLeaf(false);
      await leaf.setViewState({ type: VIEW_TYPE, active: true });
    }
    workspace.revealLeaf(leaf);
  }

  async updateStatusBar() {
    try {
      if (!(await isSpotifyRunning())) {
        this.statusBarItem.setText('');
        return;
      }
      const state = await runAppleScript(S.state);
      if (state === 'playing') {
        const [track, artist] = await Promise.all([runAppleScript(S.track), runAppleScript(S.artist)]);
        this.statusBarItem.setText(`▶  ${track}  —  ${artist}`);
      } else if (state === 'paused') {
        this.statusBarItem.setText(`⏸  ${await runAppleScript(S.track)}`);
      } else {
        this.statusBarItem.setText('');
      }
    } catch { this.statusBarItem.setText(''); }
  }

  onunload() {
    this.app.workspace.detachLeavesOfType(VIEW_TYPE);
  }
}

module.exports = SpotifyControlsPlugin;
