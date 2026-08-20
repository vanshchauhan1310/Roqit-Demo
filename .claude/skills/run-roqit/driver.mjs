#!/usr/bin/env node
// Minimal chromium-cli-style driver for roqit_new's frontend.
// chromium-cli isn't installed in this environment, so this wraps
// Playwright directly with a similar line-oriented command vocabulary.
//
// Usage:
//   node driver.mjs script.txt        # run commands from a file
//   node driver.mjs <<'EOF'           # or pipe a heredoc
//   nav http://localhost:5173
//   wait-for text=Trips
//   screenshot trips-page
//   EOF
//
// Commands (one per line, space-separated args):
//   nav <url>                    navigate
//   wait-for text=<substring>    wait until text appears on the page
//   wait-for <css-selector>      wait until selector is visible
//   screenshot [name]            save PNG to screenshots/<name-or-timestamp>.png
//   screenshot-element <sel> [name]
//   click <css-selector>         click first match
//   click text=<substring>       click first element containing text
//   fill <css-selector> <text>   type into a react-controlled input
//   press <key>                  e.g. Enter, Escape
//   eval <js-expression>         run in page context, prints the result
//   console-errors               print any console.error/pageerror seen so far
//   sleep <ms>
//
// Exits non-zero if any command throws, so a smoke script's exit code
// is meaningful.

import { chromium } from "playwright";
import { readFileSync } from "node:fs";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREENSHOT_DIR = path.join(__dirname, "screenshots");
mkdirSync(SCREENSHOT_DIR, { recursive: true });

const scriptPath = process.argv[2];
const input = scriptPath
  ? readFileSync(scriptPath, "utf8")
  : readFileSync(0, "utf8"); // stdin

const lines = input
  .split("\n")
  .map((l) => l.trim())
  .filter((l) => l && !l.startsWith("#"));

const consoleEvents = [];

function splitArgs(rest) {
  // First token vs. "the rest" for commands like `fill <sel> <text...>`
  const m = rest.match(/^(\S+)\s*(.*)$/);
  return m ? [m[1], m[2]] : [rest, ""];
}

async function locatorFor(page, sel) {
  if (sel.startsWith("text=")) {
    return page.getByText(sel.slice(5), { exact: false }).first();
  }
  return page.locator(sel).first();
}

async function run() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await context.newPage();

  page.on("console", (msg) => {
    if (msg.type() === "error") consoleEvents.push(`[console.error] ${msg.text()}`);
  });
  page.on("pageerror", (err) => consoleEvents.push(`[pageerror] ${err.message}`));

  let shotCounter = 0;

  for (const line of lines) {
    const [cmd, rest] = splitArgs(line);
    console.log(`> ${line}`);
    try {
      switch (cmd) {
        case "nav": {
          await page.goto(rest, { waitUntil: "domcontentloaded" });
          break;
        }
        case "wait-for": {
          if (rest.startsWith("text=")) {
            await page.getByText(rest.slice(5), { exact: false }).first().waitFor({ timeout: 15000 });
          } else {
            await page.locator(rest).first().waitFor({ timeout: 15000 });
          }
          break;
        }
        case "screenshot": {
          const name = rest || `shot-${++shotCounter}`;
          const file = path.join(SCREENSHOT_DIR, `${name}.png`);
          await page.screenshot({ path: file, fullPage: true });
          console.log(`  saved ${file}`);
          break;
        }
        case "screenshot-element": {
          const [sel, name] = splitArgs(rest);
          const file = path.join(SCREENSHOT_DIR, `${name || `shot-${++shotCounter}`}.png`);
          await (await locatorFor(page, sel)).screenshot({ path: file });
          console.log(`  saved ${file}`);
          break;
        }
        case "click": {
          await (await locatorFor(page, rest)).click({ timeout: 10000 });
          break;
        }
        case "fill": {
          const [sel, text] = splitArgs(rest);
          await (await locatorFor(page, sel)).fill(text, { timeout: 10000 });
          break;
        }
        case "press": {
          await page.keyboard.press(rest);
          break;
        }
        case "sleep": {
          await page.waitForTimeout(Number(rest));
          break;
        }
        case "eval": {
          // eslint-disable-next-line no-eval
          const result = await page.evaluate(new Function(`return (${rest})`)());
          console.log("  ->", result);
          break;
        }
        case "console-errors": {
          if (consoleEvents.length === 0) console.log("  (none)");
          else consoleEvents.forEach((e) => console.log("  " + e));
          break;
        }
        default:
          console.warn(`  unknown command: ${cmd}`);
      }
    } catch (err) {
      console.error(`  FAILED: ${err.message}`);
      await page.screenshot({ path: path.join(SCREENSHOT_DIR, "failure.png"), fullPage: true }).catch(() => {});
      await browser.close();
      process.exit(1);
    }
  }

  await browser.close();
}

run();
