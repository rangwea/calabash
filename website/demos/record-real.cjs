// Drive a live tool through real interactions and capture one frame per step.
// Every frame is the actual tool page; only the input files are synthetic.
const fs = require('node:fs');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '/Applications/ChatGPT.app/Contents/Resources/cua_node/lib/node_modules/playwright');

// argv: <url> <out-dir> <recipe> <fixture-dir>
const [url, outDir, recipe, fixtures] = process.argv.slice(2);
if (!url || !outDir || !recipe) throw Error('Usage: record-real.cjs <url> <out-dir> <recipe> <fixtures>');

const W = 1120, H = 760;
// The site shows this pane at roughly 740 CSS px wide, so capture at 2x and let
// the browser downscale: text and hairlines stay sharp instead of being
// resampled away at capture time.
const SCALE = 2;

// Each recipe receives a `shot(name, ms)` callback and moves the real controls.
const recipes = {
  // Image watermark: add a batch, then change the tiling so the preview reacts.
  watermark: async (page, shot) => {
    await shot('01-empty', 1200);

    await page.locator('input[type="file"]').first().setInputFiles([
      `${fixtures}/product-01.jpg`,
      `${fixtures}/product-02.jpg`,
      `${fixtures}/product-03.jpg`,
    ]);
    await page.waitForTimeout(2200);
    await shot('02-loaded', 1400);

    // Drag the opacity slider (second slider on the page is text size; the
    // first one is opacity) to a clearer watermark.
    const slider = page.locator('.ant-slider-handle').first();
    const box = await slider.boundingBox();
    if (box) {
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.mouse.move(box.x + 120, box.y + box.height / 2, { steps: 12 });
      await page.mouse.up();
    }
    await page.waitForTimeout(1200);
    await shot('03-opacity', 1500);

    // Switch to the single centred watermark for a visibly different layout.
    const centered = page.getByText('居中单个').first();
    await centered.click({ timeout: 4000 }).catch(() => {});
    await page.waitForTimeout(1400);
    await shot('04-centered', 1700);
  },

  // Video trimming: upload a clip, then move the in/out handles.
  video: async (page, shot) => {
    await shot('01-empty', 1100);

    await page.locator('input[type="file"]').first().setInputFiles(`${fixtures}/sample-clip.webm`);
    await page.waitForTimeout(4500);
    const close = page.locator('[role="alert"] button, .ant-alert-close-icon').first();
    await close.click({ timeout: 2500 }).catch(() => {});
    await page.waitForTimeout(1400);
    await page.evaluate(() => window.scrollTo(0, 300));
    await page.waitForTimeout(700);
    await shot('02-loaded', 1600);

    // Keep one fixed scroll offset for every frame: the tool is taller than the
    // viewport, and a moving scroll makes the animation jump.
    await page.evaluate(() => window.scrollTo(0, 300));
    await page.waitForTimeout(900);
    await shot('03-range', 1400);

    // Drag the end handle leftwards to shorten the kept segment.
    const handles = page.locator('.ant-slider-handle');
    const count = await handles.count();
    if (count >= 2) {
      const box = await handles.nth(1).boundingBox();
      if (box) {
        await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
        await page.mouse.down();
        await page.mouse.move(box.x - 260, box.y + box.height / 2, { steps: 14 });
        await page.mouse.up();
      }
    }
    await page.waitForTimeout(1200);
    await shot('04-trimmed', 1800);
  },

  // AI to-do: add tasks through the real editor modal. The "AI 创建待办"
  // button would need a model call, which a demo capture must not make.
  todo: async (page, shot) => {
    await shot('01-empty', 1100);
    const tasks = [
      { title: '把季度报表发给王经理', due: '2026-11-25 15:00' },
      { title: '整理本周会议要点', due: '2026-11-27 18:00' },
      { title: '更新报价单模板', due: '' },
    ];
    for (const [index, task] of tasks.entries()) {
      await page.getByRole('button', { name: '新增' }).first().click();
      await page.waitForTimeout(900);
      const modal = page.locator('[role="dialog"]').first();
      await modal.waitFor({ state: 'visible', timeout: 10000 });
      await modal.getByPlaceholder('要做什么').fill(task.title);
      if (task.due) {
        await modal.getByPlaceholder('YYYY-MM-DD HH:mm，可留空').fill(task.due);
      }
      if (index === 0) await shot('02-editor', 1500);
      // Ant Design inserts a space between two Chinese characters in buttons.
      await modal.getByRole('button', { name: /保\s*存/ }).click();
      await page.waitForTimeout(1500);
      await shot(`0${index + 3}-saved`, 1000);
    }
    // The success toast lasts a few seconds; wait it out so the final frame
    // shows only the list.
    await page.mouse.move(5, 740);
    await page.waitForTimeout(6000);
    await shot('06-list', 2200);
  },

  // Personal ledger: record entries through the real editor modal, then set a
  // monthly budget so the progress bar and charts fill in. The dialog already
  // defaults to 支出 / 餐饮, so only the date and amount need changing.
  ledger: async (page, shot) => {
    await shot('01-empty', 1100);
    const rows = [
      { date: '2026-11-03', amount: '38', note: '午餐外卖' },
      { date: '2026-11-08', amount: '126.5', note: '日用品' },
      { date: '2026-11-12', amount: '45', note: '打车' },
      { date: '2026-11-15', amount: '68', note: '晚餐' },
    ];
    for (const [index, row] of rows.entries()) {
      await page.getByRole('button', { name: '手动新增' }).first().click();
      const modal = page.locator('[role="dialog"]').first();
      await modal.waitFor({ state: 'visible', timeout: 10000 });
      await modal.getByPlaceholder('YYYY-MM-DD').fill(row.date);
      await modal.getByRole('spinbutton').first().fill(row.amount);
      await modal.getByPlaceholder('可选，写点补充说明').fill(row.note);
      if (index === 0) await shot('02-editor', 1500);
      await modal.getByRole('button', { name: /保\s*存/ }).click();
      await page.waitForTimeout(1700);
      await shot(`0${index + 3}-saved`, 900);
    }

    // Set a budget so the monthly progress bar shows a real value.
    const budget = page.locator('.ant-input-number-input').first();
    await budget.fill('3000').catch(() => {});
    await page.getByRole('button', { name: /保存预算/ }).first().click().catch(() => {});
    await page.waitForTimeout(2200);
    await page.mouse.move(5, 740);
    await page.waitForTimeout(6000);
    await shot('07-summary', 2400);
  },

  // Excel: upload a workbook, then read the rows so the table fills.
  excel: async (page, shot) => {
    await shot('01-empty', 1100);
    await page.locator('input[type="file"]').first().setInputFiles(`${fixtures}/products.xlsx`);
    await page.waitForTimeout(4200);
    await page.mouse.move(5, 740);
    await page.waitForTimeout(1200);
    await shot('02-detected', 1600);

    const read = page.getByRole('button', { name: /读取商品行|读取/ }).first();
    await read.click({ timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(2600);
    await page.mouse.move(5, 740);
    await page.waitForTimeout(900);
    await shot('03-rows', 1500);

    // Select the first product row so the right column shows its copy panel.
    const row = page.getByText('折叠露营椅').first();
    await row.click({ timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(2000);
    await shot('04-selected', 1900);
  },
};

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    args: ['--no-sandbox', '--disable-gpu', '--disable-crash-reporter', '--disable-breakpad'],
  });
  const frames = [];
  try {
    fs.mkdirSync(outDir, { recursive: true });
    const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: SCALE });
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto(url, { waitUntil: 'load', timeout: 60000 });
    await page.waitForTimeout(2200);

    const shot = async (name, duration) => {
      const file = `${name}.png`;
      await page.screenshot({ path: `${outDir}/${file}` });
      frames.push({ file, duration });
      process.stdout.write(`  frame ${file}\n`);
    };

    const step = recipes[recipe];
    if (!step) throw Error(`Unknown recipe: ${recipe}`);
    await step(page, shot);
    fs.writeFileSync(`${outDir}/frames.json`, JSON.stringify(frames, null, 2));
    console.log(JSON.stringify({ recipe, frames: frames.length, errors }));
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
