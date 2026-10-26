// Records actual NiceGUI actions against the isolated showcase server.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '/Applications/ChatGPT.app/Contents/Resources/cua_node/lib/node_modules/playwright');

const base = process.argv[2];
const directory = process.argv[3];
const scenarios = (process.argv[4] || 'ledger,excel,customers,documents,media').split(',');
if (!base || !directory) throw new Error('Usage: node record.cjs <local-url> <frames-directory> [scenarios]');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
  try {
    for (const language of ['zh', 'en']) {
      for (const name of scenarios) {
        if (process.env.SHOWCASE_HOME && ['ledger', 'customers'].includes(name)) {
          const home = fs.realpathSync(process.env.SHOWCASE_HOME);
          assert.ok(home.startsWith('/private/tmp/calabash-website-'), 'Only reset isolated showcase data');
          fs.rmSync(path.join(home, '.calabash', 'showcase', `${name}-${language}.db`), { force: true });
        }
        const root = path.join(directory, `${name}-${language}`);
        fs.mkdirSync(root, { recursive: true });
        const page = await browser.newPage({ viewport: { width: 1120, height: 760 }, deviceScaleFactor: 1 });
        const errors = [];
        page.on('pageerror', error => errors.push(String(error)));
        const frames = [];
        const text = (zh, en) => language === 'en' ? en : zh;
        const input = testid => page.locator(`input[data-testid="${testid}"], textarea[data-testid="${testid}"], [data-testid="${testid}"] input, [data-testid="${testid}"] textarea`);
        const capture = async (duration = 1300) => {
          await page.waitForTimeout(170);
          const file = `${String(frames.length).padStart(2, '0')}.png`;
          await page.screenshot({ path: path.join(root, file) });
          frames.push({ file, duration });
        };
        const select = async (testid, value) => {
          await page.getByTestId(testid).click();
          await page.getByRole('option', { name: value, exact: true }).click();
          await page.waitForTimeout(120);
        };
        const appendFiles = async () => {
          await page.locator('button').filter({ has: page.locator('i').filter({ hasText: /^attach_file$/ }) }).first().click();
          await page.waitForTimeout(300);
        };
        await page.goto(`${base}/demo/${name}?lang=${language}`, { waitUntil: 'networkidle' });
        await page.waitForTimeout(700);
        await capture(1500);
        if (name === 'ledger') {
          await page.getByTestId('ledger-add').click();
          await page.getByRole('dialog').waitFor();
          await capture(900);
          await input('ledger-note').fill(text('团队午餐', 'Team lunch'));
          await input('ledger-amount').fill('128');
          await capture(1200);
          await page.getByTestId('ledger-save').click();
          await page.waitForTimeout(500);
          await capture(1600);
          await page.getByTestId('ledger-filter').getByRole('button', { name: text('餐饮', 'Food'), exact: true }).click();
          await capture(1500);
          await page.getByTestId('ledger-filter').getByRole('button', { name: text('全部分类', 'All categories'), exact: true }).click();
          await page.getByTestId('ledger-export').click();
          await page.getByText('monthly-ledger.csv', { exact: true }).first().waitFor();
          await capture(1800);
        } else if (name === 'excel') {
          await appendFiles();
          await capture(1100);
          await page.getByTestId('excel-load').click();
          await page.getByText('192', { exact: true }).first().waitFor();
          await capture(1400);
          await page.getByTestId('excel-analyze').click();
          await page.locator('canvas').first().waitFor();
          await page.waitForTimeout(500);
          await capture(1700);
          await select('excel-group', 'Product');
          await page.getByTestId('excel-analyze').click();
          await page.waitForTimeout(500);
          await capture(1500);
          await page.getByTestId('excel-export').click();
          await page.getByText('sales-summary.xlsx', { exact: true }).first().waitFor();
          await capture(1700);
        } else if (name === 'customers') {
          await page.getByTestId('customers-filter').getByRole('button', { name: text('洽谈中', 'In progress'), exact: true }).click();
          await capture(1200);
          await input('customers-search').fill(text('澄光', 'Lucent'));
          await capture(1100);
          await input('customers-note').fill(text('方案已确认，周五签约；下周安排交付。', 'Proposal approved. Contract Friday; kickoff next week.'));
          await select('customers-stage', text('已合作', 'Active client'));
          await capture(1600);
          await page.getByTestId('customers-save').click();
          await page.waitForTimeout(300);
          await page.getByTestId('customers-filter').getByRole('button', { name: text('全部客户', 'All customers'), exact: true }).click();
          await input('customers-search').fill('');
          await capture(1500);
          await page.getByTestId('customers-export').click();
          await page.getByText('customer-pipeline.csv', { exact: true }).first().waitFor();
          await capture(1700);
        } else if (name === 'documents') {
          await appendFiles();
          await capture(1100);
          await page.getByTestId('documents-preview').click();
          await page.getByTestId('documents-move-2').waitFor();
          await capture(1500);
          await page.getByTestId('documents-move-2').click();
          await capture(1200);
          await input('documents-range').fill('1');
          await capture(1000);
          await page.getByTestId('documents-run').click();
          await page.getByText('merged-documents.pdf', { exact: true }).first().waitFor();
          await capture(1800);
        } else if (name === 'media') {
          await appendFiles();
          await capture(1000);
          await page.getByTestId('media-inspect').click();
          await page.locator('video').waitFor();
          await page.locator('video').evaluate(video => { video.currentTime = 1; });
          await page.waitForTimeout(400);
          await capture(1500);
          await input('media-start').fill('2');
          await input('media-end').fill('6');
          await select('media-format', 'FLAC · Lossless');
          await capture(1300);
          await page.getByTestId('media-run').click();
          await capture(900);
          await page.getByText('Studio-briefing-3-clip.flac', { exact: true }).first().waitFor({ timeout: 30000 });
          await page.getByText(/^3 \/ 3 ·/).waitFor({ timeout: 30000 });
          await page.getByText('Studio-briefing-3-clip.flac', { exact: true }).first().scrollIntoViewIfNeeded();
          await capture(1800);
        }
        assert.deepEqual(errors, [], `${name}-${language} browser errors`);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${name} overflows`);
        fs.writeFileSync(path.join(root, 'frames.json'), JSON.stringify(frames, null, 2));
        console.log(`Recorded ${name}-${language}: ${frames.length} real UI states`);
        await page.close();
      }
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
