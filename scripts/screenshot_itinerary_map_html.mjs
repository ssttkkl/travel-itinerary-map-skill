#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i++) {
    const current = argv[i];
    if (!current.startsWith('--')) continue;
    const next = argv[i + 1];
    if (next && !next.startsWith('--')) {
      args[current.slice(2)] = next;
      i += 1;
    } else {
      args[current.slice(2)] = 'true';
    }
  }
  return args;
}

function listFrom(value) {
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeInputUrl(raw) {
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(raw)) {
    return new URL(raw);
  }
  return new URL(`file://${path.resolve(raw)}`);
}

function stripSearch(url) {
  const clone = new URL(url.toString());
  clone.search = '';
  return clone;
}

function keyForTarget(target) {
  if (target.startsWith('day-')) return target;
  if (target === 'optional') return 'optional';
  if (target === 'home') return 'home';
  return target;
}

const args = parseArgs(process.argv);
const rawUrl = args.url;
const rawOutput = args.output;

if (!rawUrl || !rawOutput) {
  console.error('Usage: screenshot_itinerary_map_html.mjs --url <html-url> --output <png-path> [--width 1700] [--height 1120] [--scale 2]');
  process.exit(1);
}

const inputUrl = normalizeInputUrl(rawUrl);
const captureUrl = stripSearch(inputUrl);
const params = inputUrl.searchParams;
const showTargets = new Set(listFrom(params.get('show')).map(keyForTarget));
const hideTargets = new Set(listFrom(params.get('hide')).map(keyForTarget));
const title = params.get('title');
const subtitle = params.get('subtitle');
const waitMs = Number(params.get('wait') || args.wait || 600);
const width = Number(args.width || params.get('width') || 1700);
const height = Number(args.height || params.get('height') || 1120);
const scale = Number(args.scale || params.get('scale') || 2);

fs.mkdirSync(path.dirname(path.resolve(rawOutput)), { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: scale });
const page = await context.newPage();

await page.goto(captureUrl.toString(), { waitUntil: 'load' });
await page.waitForTimeout(waitMs);

await page.evaluate(({ show, hide, title, subtitle }) => {
  const showSet = new Set(show);
  const hideSet = new Set(hide);
  const legendFilters = Array.from(document.querySelectorAll('.legend-filter'));
  const dayFilters = legendFilters.filter((box) => String(box.dataset.target || '').startsWith('.day-'));
  const anyShowTargets = showSet.size > 0;

  const legendKeyForBox = (box) => {
    const target = String(box.dataset.target || '');
    if (target.startsWith('.day-')) return target.slice(1);
    if (target === '.optional-item') return 'optional';
    if (target === '.home-item') return 'home';
    return target;
  };

  if (anyShowTargets) {
    for (const box of legendFilters) {
      const key = legendKeyForBox(box);
      if (key.startsWith('day-')) {
        box.checked = showSet.has(key) && !hideSet.has(key);
      } else {
        box.checked = showSet.has(key) && !hideSet.has(key) ? true : box.checked;
      }
    }
  }

  for (const box of legendFilters) {
    const key = legendKeyForBox(box);
    if (hideSet.has(key)) {
      box.checked = false;
    }
  }

  for (const box of legendFilters) {
    box.dispatchEvent(new Event('change', { bubbles: true }));
  }

  if (title) {
    const h1 = document.querySelector('.title-box h1');
    if (h1) h1.textContent = title;
  }
  if (subtitle) {
    const sub = document.querySelector('.title-box .sub');
    if (sub) sub.textContent = subtitle;
  }

  for (const selector of hide) {
    if (selector === 'legend') {
      const legend = document.querySelector('.legend');
      if (legend) legend.style.display = 'none';
    }
    if (selector === 'controls') {
      const controls = document.querySelector('.zoom-controls');
      if (controls) controls.style.display = 'none';
    }
    if (selector === 'title') {
      const titleBox = document.querySelector('.title-box');
      if (titleBox) titleBox.style.display = 'none';
    }
  }
}, { show: Array.from(showTargets), hide: Array.from(hideTargets), title, subtitle });

await page.waitForTimeout(200);
await page.screenshot({ path: path.resolve(rawOutput), fullPage: true });

await browser.close();
