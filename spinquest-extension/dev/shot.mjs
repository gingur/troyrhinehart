#!/usr/bin/env node
// Screenshot harness for the SpinQuest HUD dev mock.
//
//   node dev/shot.mjs <fixtureName> <outPng>   one fixture → full page + HUD crop
//   node dev/shot.mjs all <outDir>             every fixture → <outDir>/<name>.png
//
// Fixtures named popup-* render mock-popup.html (crop = the popup body);
// everything else renders mock-page.html (crop = #sqx-hud).
'use strict';

import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, resolve, join } from 'node:path';
import { mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';

const devDir = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(devDir, 'noop.js'));

function loadPlaywright() {
  for (const name of ['playwright', 'playwright-core']) {
    try {
      return require(name);
    } catch {
      // not installed under this name — try the next
    }
  }
  console.error(
    'playwright/playwright-core not found. Run:\n  cd ' + devDir + ' && npm install playwright-core'
  );
  process.exit(1);
}

const EXECUTABLE = '/opt/pw-browsers/chromium';
const HUD_SELECTOR = '#sqx-hud';

const [, , fixtureArg, outArg] = process.argv;
if (!fixtureArg || !outArg) {
  console.error('usage: node dev/shot.mjs <fixtureName>|all <outPng>|<outDir>');
  process.exit(1);
}

const { chromium } = loadPlaywright();

async function shoot(page, name, outPng) {
  const isPopup = name.startsWith('popup-');
  const file = isPopup ? 'mock-popup.html' : 'mock-page.html';
  const url = pathToFileURL(join(devDir, file)).href + '?fixture=' + encodeURIComponent(name);
  await page.goto(url, { waitUntil: 'load' });

  const known = await page.evaluate(() => Object.keys(globalThis.__SQX_FIXTURES || {}));
  if (!known.includes(name)) {
    throw new Error(`unknown fixture "${name}" — available: ${known.join(', ')}`);
  }

  const cropSel = isPopup ? 'body' : HUD_SELECTOR;
  await page.waitForSelector(cropSel, { state: 'attached', timeout: 5000 });
  // Let fonts/layout settle so crops aren't mid-paint.
  await page.evaluate(() => document.fonts && document.fonts.ready);
  await page.waitForTimeout(120);

  await page.screenshot({ path: outPng, fullPage: false });
  const hudPng = outPng.replace(/\.png$/i, '') + '-hud.png';
  await page.locator(cropSel).screenshot({ path: hudPng });
  console.log(`${name}\n  page: ${outPng}\n  crop: ${hudPng}`);
}

const browser = await chromium.launch({ executablePath: EXECUTABLE });
const page = await browser.newPage({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
  // Pin locale + timezone so time rendering is identical on every machine
  // (en-GB → 24h clock, which also fits the HUD's narrow history column).
  locale: 'en-GB',
  timezoneId: 'UTC',
});

try {
  if (fixtureArg === 'all') {
    const outDir = resolve(outArg);
    mkdirSync(outDir, { recursive: true });
    // Discover fixture names from the page itself (fixtures.js is not a module).
    await page.goto(pathToFileURL(join(devDir, 'mock-page.html')).href, { waitUntil: 'load' });
    const names = await page.evaluate(() => Object.keys(globalThis.__SQX_FIXTURES || {}));
    for (const name of names) {
      await shoot(page, name, join(outDir, name + '.png'));
    }
  } else {
    const outPng = resolve(outArg);
    mkdirSync(dirname(outPng), { recursive: true });
    await shoot(page, fixtureArg, outPng);
  }
} finally {
  await browser.close();
}
