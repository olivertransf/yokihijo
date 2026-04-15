# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repository Is

This is an **Obsidian vault** (personal knowledge management system) synced via iCloud. It follows the PARA method (Projects, Areas, Resources, Archives). Code here consists of custom Obsidian plugins and utility scripts, not a traditional software project.

## Vault Structure

- `01 - Projects/` — active projects (Claveo, IggyWiki, Lumiere, Godot, etc.)
- `02 - Areas/` — ongoing responsibilities (School, Health, Personal daily notes)
- `03 - Resources/` — reference material, templates, ideas
- `04 - Archives/` — completed/inactive material
- `.obsidian/plugins/` — custom and community plugins
- `.obsidian/scripts/` — Node.js and Python utility scripts
- `.obsidian/snippets/` — CSS customizations

## Custom Plugins (locally developed)

| Plugin ID | Purpose |
|-----------|---------|
| `claude-usage` | Shows Anthropic Claude OAuth usage (5h/7d) — desktop only, refresh via command palette |
| `garmin-stats` | Garmin fitness data display |
| `spotify-controls` | Spotify playback controls |
| `mcp-tools` | MCP (Model Context Protocol) integration |
| `rss-dashboard-shorts-strip` | Watches `rss-dashboard/data.json` and removes YouTube Shorts entries (mobile workaround) |

Each plugin lives in `.obsidian/plugins/<id>/` with `main.js`, `manifest.json`, and optionally `styles.css`.

## RSS Dashboard: YouTube Shorts Filtering

Two-layer approach — **read the full explanation in `.obsidian/scripts/README.md`** before modifying:

- **Desktop**: `rss-dashboard/main.js` is patched — `processYouTubeFeed` and a second filter in `parseFeed`. **Re-apply both patches after any RSS Dashboard upgrade.**
- **Mobile (iOS)**: The `rss-dashboard-shorts-strip` plugin handles this (cannot patch `main.js` on mobile).

### Strip/watch scripts (run from vault root)

```bash
# Strip Shorts from data.json once
node .obsidian/scripts/strip-rss-dashboard-shorts.mjs
node .obsidian/scripts/strip-rss-dashboard-shorts.mjs --dry-run

# Watch and auto-strip on file change
node .obsidian/scripts/watch-rss-dashboard-shorts.mjs
node .obsidian/scripts/watch-rss-dashboard-shorts.mjs --run-on-start --debounce 0.75

# Background watcher
nohup node .obsidian/scripts/watch-rss-dashboard-shorts.mjs >> /tmp/rss-strip-watch.log 2>&1 &

# Python equivalents also available
python3 .obsidian/scripts/strip-rss-dashboard-shorts.py
python3 .obsidian/scripts/watch-rss-dashboard-shorts.py
```

## Daily Notes

- Location: `02 - Areas/Personal/Daily/`
- Format: `YYYY-MM-DD`
- Template: `03 - Resources/Templates/Template Daily` (end-of-day reflection: win, loss, gratitude, tomorrow's intention)

## Appearance & Snippets

- Theme: **Baseline**, font: **Atkinson Hyperlegible / Atkinson Hyperlegible Mono**
- Active CSS snippet: `daily-notes-editor-title-padding` (others available but disabled)
- Snippets live in `.obsidian/snippets/`

## RSS Dashboard Settings

- Global `maxItems` (view limit): **50**
- Per-feed `maxItemsLimit` (cache limit): **25**
- YouTube native feeds cap at 15 items regardless — use RSSHub/RSS-Bridge for more
