#!/usr/bin/env node
/**
 * Watch RSS Dashboard data.json and run strip-rss-dashboard-shorts.mjs when it changes.
 *
 *   node .obsidian/scripts/watch-rss-dashboard-shorts.mjs
 *
 * Options (times in seconds):
 *   --debounce 0.75
 *   --poll 0.35
 *   --run-on-start
 */

import { statSync, existsSync } from "fs";
import { spawn } from "child_process";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const vault = join(__dirname, "..", "..");
const dataPath = join(vault, ".obsidian/plugins/rss-dashboard/data.json");
const stripPath = join(__dirname, "strip-rss-dashboard-shorts.mjs");

function parseArgs() {
  const a = process.argv.slice(2);
  let debounceMs = 750;
  let pollMs = 350;
  let runOnStart = false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] === "--debounce" && a[i + 1]) debounceMs = Number(a[++i]) * 1000;
    else if (a[i] === "--poll" && a[i + 1]) pollMs = Number(a[++i]) * 1000;
    else if (a[i] === "--run-on-start") runOnStart = true;
  }
  return { debounceMs, pollMs, runOnStart };
}

function runStrip() {
  return new Promise((resolve, reject) => {
    const p = spawn(process.execPath, [stripPath], {
      cwd: vault,
      stdio: "inherit",
    });
    p.on("close", (code) => (code === 0 ? resolve() : reject(new Error(`exit ${code}`))));
    p.on("error", reject);
  });
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function main() {
  const { debounceMs, pollMs, runOnStart } = parseArgs();

  if (!existsSync(stripPath)) {
    console.error(`Missing: ${stripPath}`);
    process.exit(1);
  }
  if (!existsSync(dataPath)) {
    console.error(`RSS Dashboard data not found: ${dataPath}`);
    console.error("Open Obsidian with RSS Dashboard at least once, then restart.");
    process.exit(1);
  }

  console.log(`Watching ${dataPath}`);
  console.log("Press Ctrl+C to stop.");

  let lastProcessed = statSync(dataPath).mtimeMs;

  if (runOnStart) {
    await runStrip().catch(() => {});
    lastProcessed = statSync(dataPath).mtimeMs;
  }

  for (;;) {
    await sleep(pollMs);
    let cur;
    try {
      cur = statSync(dataPath).mtimeMs;
    } catch {
      continue;
    }
    if (cur === lastProcessed) continue;

    for (;;) {
      await sleep(120);
      let n;
      try {
        n = statSync(dataPath).mtimeMs;
      } catch {
        break;
      }
      if (n !== cur) {
        cur = n;
        continue;
      }
      break;
    }

    await sleep(debounceMs);
    try {
      if (statSync(dataPath).mtimeMs !== cur) continue;
    } catch {
      continue;
    }

    await runStrip().catch(() => {});
    lastProcessed = statSync(dataPath).mtimeMs;
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
