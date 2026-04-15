# RSS Dashboard helpers

## Shorts handling in this vault

RSS Dashboard’s keyword filters only match **title / summary / content**, not the **link**, so they cannot hide Shorts by URL.

1. **Desktop patch** — `.obsidian/plugins/rss-dashboard/main.js`: `processYouTubeFeed` filters Shorts, and **`parseFeed` runs a second filter on `m.items` after `detectAndProcessFeed`** (needed because feeds that don’t match `isYouTubeFeed(url)` skip YouTube processing and Shorts were still merged in). **Re-apply both patches** after upgrading RSS Dashboard from Community Plugins.

2. **iPhone / iPad** — Obsidian Mobile often does **not** use a hand-edited `main.js` the same way (or iCloud may not ship your patch). Enable the bundled plugin **`RSS Dashboard — strip Shorts`** (`rss-dashboard-shorts-strip`). It watches `.obsidian/plugins/rss-dashboard/data.json` and rewrites it to drop Shorts entries after each save (runs inside Obsidian on iOS; no Node). Turn it on under **Settings → Community plugins** after the vault syncs.

The scripts below clean **existing** cache in `data.json` manually (or catch anything that slips through).

Strip YouTube Shorts (`youtube.com/shorts/…`) from RSS Dashboard’s `plugins/rss-dashboard/data.json`. If there are no Shorts, the strip step **does not rewrite** the file (so a watcher won’t loop).

Run commands from the **vault root** (parent of `.obsidian`).

## Node.js (recommended)

Requires [Node.js](https://nodejs.org/).

```bash
node .obsidian/scripts/strip-rss-dashboard-shorts.mjs
node .obsidian/scripts/strip-rss-dashboard-shorts.mjs --dry-run
```

Watch the data file and strip whenever it changes:

```bash
node .obsidian/scripts/watch-rss-dashboard-shorts.mjs
```

- `--run-on-start` — strip once when the watcher starts  
- `--debounce 0.75` — extra wait after the file stops changing (seconds)  
- `--poll 0.35` — how often to poll for changes (seconds)

Background:

```bash
nohup node .obsidian/scripts/watch-rss-dashboard-shorts.mjs >> /tmp/rss-strip-watch.log 2>&1 &
```

## Python

Same behavior as the `.mjs` scripts:

```bash
python3 .obsidian/scripts/strip-rss-dashboard-shorts.py
python3 .obsidian/scripts/watch-rss-dashboard-shorts.py
```

## RSS Dashboard: view vs per-channel limit

In **RSS Dashboard → Settings**:

- **Maximum items** (global slider, `maxItems` in `data.json`) controls how many articles **show in the list view** per feed — this vault keeps that at **50**.
- **Max items limit** per feed (Edit feed → slider, `maxItemsLimit`) controls how many items are **kept in cache** after a refresh — this vault uses **25** per channel.

### YouTube only shows 15 in the official RSS

YouTube’s native feed URL (`youtube.com/feeds/videos.xml?channel_id=…`) **only contains 15 videos**, no matter what `maxItemsLimit` is. That cap is from YouTube, not RSS Dashboard.

To actually **receive** more than 15 entries, you need a different feed source (e.g. self-hosted [RSSHub](https://github.com/DIYgod/RSSHub) / [RSS-Bridge](https://github.com/RSS-Bridge/rss-bridge) with a YouTube route, or another proxy that builds a larger feed). Then set the feed URL in RSS Dashboard to that feed.

## Notes

Obsidian does not run these scripts when RSS Dashboard refreshes. Use a **watcher** in a terminal (or a login Launch Agent) so strip runs after each save to `data.json`.
