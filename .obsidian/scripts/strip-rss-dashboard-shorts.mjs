#!/usr/bin/env node
/**
 * Remove YouTube Shorts entries from RSS Dashboard cached data.
 *
 * Usage (from vault root):
 *   node .obsidian/scripts/strip-rss-dashboard-shorts.mjs
 *   node .obsidian/scripts/strip-rss-dashboard-shorts.mjs --dry-run
 */

import { readFileSync, writeFileSync, existsSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
// .obsidian/scripts/this.mjs -> vault
const vault = join(__dirname, "..", "..");
const defaultDataPath = join(vault, ".obsidian/plugins/rss-dashboard/data.json");

function isYoutubeShort(link) {
  if (!link || typeof link !== "string") return false;
  const l = link.toLowerCase();
  return (
    l.includes("youtube.com/shorts/") ||
    l.includes("youtu.be/shorts/") ||
    l.includes("m.youtube.com/shorts/")
  );
}

const args = process.argv.slice(2);
const dryRun = args.includes("--dry-run");
const dataIdx = args.indexOf("--data");
const dataPath =
  dataIdx >= 0 && args[dataIdx + 1] ? args[dataIdx + 1] : defaultDataPath;

if (!existsSync(dataPath)) {
  console.error(`Not found: ${dataPath}`);
  process.exit(1);
}

const data = JSON.parse(readFileSync(dataPath, "utf8"));
const feeds = data.feeds;
if (!Array.isArray(feeds)) {
  console.error("Invalid data: missing feeds array");
  process.exit(1);
}

let removed = 0;
let totalBefore = 0;
for (const feed of feeds) {
  const items = feed.items;
  if (!Array.isArray(items)) continue;
  totalBefore += items.length;
  const kept = [];
  for (const item of items) {
    if (isYoutubeShort(item?.link)) removed++;
    else kept.push(item);
  }
  feed.items = kept;
}

console.log(`Feeds in file  Items: ${totalBefore}  Shorts removed: ${removed}`);

if (dryRun) {
  console.log("Dry run — no changes written.");
  process.exit(0);
}

if (removed === 0) {
  console.log("No Shorts in cache — left unchanged.");
  process.exit(0);
}

writeFileSync(dataPath, JSON.stringify(data), "utf8");
console.log(`Updated ${dataPath}`);
