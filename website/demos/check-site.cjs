const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '/Applications/ChatGPT.app/Contents/Resources/cua_node/lib/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
  try {
    for (const width of [1440, 900, 390, 320]) {
      for (const lang of ['zh', 'en']) {
        const page = await browser.newPage({ viewport: { width, height: 900 }, reducedMotion: 'reduce' });
        const errors = [];
        page.on('pageerror', e => errors.push(String(e)));
        const base = pathToFileURL(path.resolve(__dirname, '../index.html')).href;
        await page.goto(`${base}?lang=${lang}`);
        assert.equal(await page.locator('html').getAttribute('lang'), lang === 'en' ? 'en' : 'zh-CN');
        const panel = await page.locator('#demo-panel').boundingBox();
        const description = await page.locator('.demo-explanation').boundingBox();
        assert.equal(await page.locator('.demo-layout > #demo-panel').count(), 1);
        if (width > 720) {
          assert.ok(description.x >= panel.x + panel.width, 'Desktop explanation must be to the right of the GIF');
          assert.ok(Math.abs(description.y - panel.y) < panel.height, 'Desktop columns must overlap vertically');
          assert.ok(panel.height <= 540, 'Desktop demo must remain compact');
        } else {
          assert.ok(description.y >= panel.y + panel.height, 'Mobile explanation must follow the GIF');
        }
        for (const name of ['ledger', 'excel', 'customers', 'documents', 'media']) {
          await page.locator(`[data-demo="${name}"]`).click();
          await page.waitForFunction(() => { const i = document.querySelector('#demo-image'); return i.complete && i.naturalWidth > 0; });
          assert.match(await page.locator('#demo-image').getAttribute('src'), new RegExp(`${name}-${lang}\\.webp$`));
        }
        await page.locator('#demo-frame').scrollIntoViewIfNeeded();
        await page.locator('#demo-play').click();
        await page.waitForFunction(() => document.querySelector('#demo-image').getAttribute('src').endsWith('.gif'));
        await page.locator('#demo-play').click();
        assert.match(await page.locator('#demo-image').getAttribute('src'), /\.webp$/);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `home overflow ${width}/${lang}`);
        if (width < 600) {
          await page.locator('[data-menu-toggle]').click();
          assert.equal(await page.locator('[data-menu-toggle]').getAttribute('aria-expanded'), 'true');
        }
        await page.screenshot({ path: `/private/tmp/calabash-site-${width}-${lang}.png`, fullPage: true });
        await page.goto(`${pathToFileURL(path.resolve(__dirname, '../guide.html')).href}?lang=${lang}`);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `guide overflow ${width}/${lang}`);
        assert.equal(await page.locator('img').evaluateAll(images => images.every(i => i.complete && i.naturalWidth > 0)), true);
        await page.locator('[data-language-toggle]').click();
        assert.equal(await page.locator('html').getAttribute('lang'), lang === 'en' ? 'zh-CN' : 'en');
        assert.deepEqual(errors, []);
        console.log(`PASS ${width}px / ${lang}: five demos, playback, guide, language, overflow`);
        await page.close();
      }
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
