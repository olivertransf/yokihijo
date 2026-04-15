"use strict";

const { Plugin, TFile, normalizePath } = require("obsidian");

const DATA_RELPATH = normalizePath(".obsidian/plugins/rss-dashboard/data.json");

function isShortUrl(link) {
  if (!link || typeof link !== "string") return false;
  const l = link.toLowerCase();
  return (
    l.includes("youtube.com/shorts/") ||
    l.includes("youtu.be/shorts/") ||
    l.includes("m.youtube.com/shorts/")
  );
}

function isRssDashboardDataFile(file) {
  if (!file || file.path == null) return false;
  const p = normalizePath(file.path);
  return (
    p === DATA_RELPATH ||
    p.endsWith(normalizePath("rss-dashboard/data.json"))
  );
}

function stripShortsFromData(data) {
  if (!data || !Array.isArray(data.feeds)) return { data, changed: false };
  let removed = 0;
  for (const feed of data.feeds) {
    if (!feed || !Array.isArray(feed.items)) continue;
    const before = feed.items.length;
    feed.items = feed.items.filter((item) => item && !isShortUrl(item.link));
    removed += before - feed.items.length;
  }
  return { data, changed: removed > 0 };
}

module.exports = class RssDashboardShortsStrip extends Plugin {
  async onload() {
    this.app.workspace.onLayoutReady(() => {
      this.queueStrip();
    });
    this.registerEvent(
      this.app.vault.on("modify", (file) => {
        if (!(file instanceof TFile) || !isRssDashboardDataFile(file)) return;
        this.queueStrip();
      })
    );
    this.registerEvent(
      this.app.vault.on("create", (file) => {
        if (!(file instanceof TFile) || !isRssDashboardDataFile(file)) return;
        this.queueStrip();
      })
    );
    // Plugin.saveData() may not emit vault.modify on all platforms; poll lightly.
    this.registerInterval(() => this.queueStrip(), 12000);
  }

  queueStrip() {
    if (this._timer) window.clearTimeout(this._timer);
    this._timer = window.setTimeout(() => {
      this._timer = null;
      this.strip();
    }, 500);
  }

  async strip() {
    if (this._busy) return;
    const file = this.app.vault.getAbstractFileByPath(DATA_RELPATH);
    if (!(file instanceof TFile)) return;

    let raw;
    try {
      raw = await this.app.vault.read(file);
    } catch {
      return;
    }

    let data;
    try {
      data = JSON.parse(raw);
    } catch {
      return;
    }

    const { data: next, changed } = stripShortsFromData(data);
    if (!changed) return;

    this._busy = true;
    try {
      await this.app.vault.modify(file, JSON.stringify(next, null, 2));
    } finally {
      this._busy = false;
    }
  }
};
