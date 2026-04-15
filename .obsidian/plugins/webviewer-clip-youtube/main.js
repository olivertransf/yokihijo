/**
 * Web Viewer Clip YouTube — ribbon + command to save the active Web Viewer
 * YouTube URL as a note with title and iframe embed.
 */
const { Plugin, Notice, Setting, SettingTab, normalizePath } = require("obsidian");

const YT_RE =
  /(?:youtube\.com\/(?:watch\?v=|embed\/|shorts\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})/;

function extractYoutubeId(url) {
  if (!url || typeof url !== "string") return null;
  const m = url.match(YT_RE);
  return m ? m[1] : null;
}

function sanitizeFileBase(name) {
  const s = name
    .replace(/[<>:"/\\|?*\n\r]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 120);
  return s || "YouTube clip";
}

async function fetchYoutubeTitle(videoId) {
  const watch = `https://www.youtube.com/watch?v=${videoId}`;
  const oembed = `https://www.youtube.com/oembed?url=${encodeURIComponent(
    watch
  )}&format=json`;
  const res = await fetch(oembed);
  if (!res.ok) throw new Error(`oembed ${res.status}`);
  const j = await res.json();
  return (j && j.title) || `Video ${videoId}`;
}

async function readWebviewUrl(wv) {
  if (!wv) return null;
  try {
    if (typeof wv.getURL === "function") {
      const u = wv.getURL();
      if (u && u.startsWith("http")) return u;
    }
  } catch {
    /* ignore */
  }
  try {
    if (typeof wv.executeJavaScript === "function") {
      const href = await wv.executeJavaScript("location.href");
      if (href && typeof href === "string" && href.startsWith("http")) {
        return href;
      }
    }
  } catch {
    /* ignore */
  }
  const src = wv.getAttribute && wv.getAttribute("src");
  if (src && src.startsWith("http")) return src;
  return null;
}

function findWebviewInLeaf(leaf) {
  const view = leaf?.view;
  if (!view) return null;
  const root = view.contentEl || view.containerEl;
  if (!root) return null;
  return root.querySelector("webview");
}

class WebviewerClipYoutubeSettingTab extends SettingTab {
  constructor(app, plugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display() {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "Web Viewer Clip YouTube" });
    new Setting(containerEl)
      .setName("Notes folder")
      .setDesc("New clips are created under this folder (created if missing).")
      .addText((text) =>
        text
          .setPlaceholder("Clips/YouTube")
          .setValue(this.plugin.settings.folder)
          .onChange(async (v) => {
            this.plugin.settings.folder = v.trim() || "Clips/YouTube";
            await this.plugin.saveSettings();
          })
      );
  }
}

module.exports = class WebviewerClipYoutube extends Plugin {
  async onload() {
    await this.loadSettings();
    this.addRibbonIcon("video", "Clip YouTube from Web Viewer", () => {
      this.clipActiveWebviewer();
    });
    this.addCommand({
      id: "clip-youtube-from-webviewer",
      name: "Clip current Web Viewer YouTube page to note",
      callback: () => this.clipActiveWebviewer(),
    });
    this.addSettingTab(new WebviewerClipYoutubeSettingTab(this.app, this));
  }

  async loadSettings() {
    this.settings = Object.assign(
      { folder: "Clips/YouTube" },
      await this.loadData()
    );
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }

  async clipActiveWebviewer() {
    const leaf = this.app.workspace.activeLeaf;
    if (!leaf) {
      new Notice("No active tab.");
      return;
    }
    const wv = findWebviewInLeaf(leaf);
    if (!wv) {
      new Notice(
        "Active tab has no Web Viewer. Open Web Viewer to a page first."
      );
      return;
    }
    const url = await readWebviewUrl(wv);
    if (!url) {
      new Notice("Could not read URL from Web Viewer.");
      return;
    }
    const vid = extractYoutubeId(url);
    if (!vid) {
      new Notice("Not a YouTube video URL (watch / embed / shorts / youtu.be).");
      return;
    }

    let title;
    try {
      title = await fetchYoutubeTitle(vid);
    } catch (e) {
      console.warn("[webviewer-clip-youtube] oembed failed", e);
      title = `YouTube ${vid}`;
    }

    const base = `${sanitizeFileBase(title)} — ${vid}`;
    const folder = normalizePath(this.settings.folder.replace(/^\/+/, ""));
    const path = normalizePath(`${folder}/${base}.md`);

    try {
      await this.app.vault.createFolder(folder).catch(() => {});
    } catch {
      /* exists */
    }

    if (this.app.vault.getAbstractFileByPath(path)) {
      new Notice(`Note already exists:\n${path}`);
      await this.app.workspace.openLinkText(path, "", true);
      return;
    }

    const body = this.buildNote(title, vid);
    await this.app.vault.create(path, body);
    new Notice(`Saved:\n${path}`);
    const f = this.app.vault.getAbstractFileByPath(path);
    if (f) {
      try {
        await this.app.workspace.getLeaf(true).openFile(f);
      } catch (e) {
        console.warn("[webviewer-clip-youtube] openFile", e);
      }
    }
  }

  buildNote(title, videoId) {
    const watch = `https://www.youtube.com/watch?v=${videoId}`;
    const embed = `https://www.youtube.com/embed/${videoId}`;
    return (
      `# ${title}\n\n` +
      `<iframe width="560" height="315" src="${embed}" ` +
      `title="YouTube video player" frameborder="0" ` +
      `allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" ` +
      `allowfullscreen></iframe>\n\n` +
      `[Open on YouTube](${watch})\n`
    );
  }
};
