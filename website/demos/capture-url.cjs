// Screenshot one live URL with Playwright, then exit.
// Used by render-real.py: the tool server keeps running in the calling Python
// process, so this must not be run while that process blocks its event loop.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '/Applications/ChatGPT.app/Contents/Resources/cua_node/lib/node_modules/playwright');

const [url, destination] = process.argv.slice(2);
if (!url || !destination) throw Error('Usage: capture-url.cjs <url> <output.png>');

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    args: ['--no-sandbox', '--disable-gpu', '--disable-crash-reporter', '--disable-breakpad'],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1120, height: 760 }, deviceScaleFactor: 1 });
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    // The session endpoint plants a cookie and redirects to the tool itself.
    await page.goto(url, { waitUntil: 'load', timeout: 60000 });
    // Tool pages keep a session heartbeat open, so network idle never settles.
    await page.waitForTimeout(2500);
    await page.screenshot({ path: destination });
    const title = await page.title();
    console.log(JSON.stringify({ title, url: page.url(), errors }));
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
