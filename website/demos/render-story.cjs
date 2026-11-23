// Build the five README/website animations from illustrated frames.
// Both the chat shell and the tool pane are illustrations. The recordings of
// the previous UI generation no longer match the current app, so nothing here
// claims to be a screen recording, and the shell says so in the image itself.
// No model calls, keys, personal tools or user databases are accessed.
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { pathToFileURL } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '/Applications/ChatGPT.app/Contents/Resources/cua_node/lib/node_modules/playwright');
const output = process.argv[2];
if (!output) throw Error('Usage: node render-story.cjs <output-directory>');

// [title, prompt] per language, in the order the frames are generated.
const stories = {
  ledger: {
    zh: ['个人账本', '做一个记账工具：记录收支、分类筛选，查看月度趋势和预算，支持导出账本。'],
    en: ['Personal ledger', 'Build a ledger with income and expenses, category filters, monthly trends, budgets and CSV export.'],
  },
  excel: {
    zh: ['销售统计', '创建 Excel 销售统计工具：读取工作簿，按地区或产品汇总，用图表展示，导出统计结果。'],
    en: ['Sales summary', 'Create an Excel sales tool: read a workbook, summarize by region or product, show charts and export the results.'],
  },
  customers: {
    zh: ['客户管理', '帮我做一个客户管理工具：搜索客户、管理销售阶段、保存跟进记录，并导出客户列表。'],
    en: ['Customer workspace', 'Build a customer workspace with search, sales stages, saved follow-up notes and customer list export.'],
  },
  documents: {
    zh: ['PDF 整理', '创建 PDF 整理工具：预览页面、调整文件顺序、选择页码，再合并成一份新的 PDF。'],
    en: ['PDF workspace', 'Create a PDF workspace: preview pages, reorder files, select page ranges and merge them into a new PDF.'],
  },
  media: {
    zh: ['音视频处理', '做一个音视频工具：预览视频，设置起止时间，批量提取 FLAC 音频，保留原文件。'],
    en: ['Media workspace', 'Build a media tool: preview videos, set a time interval and batch-extract FLAC audio without changing the originals.'],
  },
};

// Frame plan: type the request, send it, watch it build, then land on a
// two-pane view with the finished tool beside the conversation.
function plan(prompt) {
  const frames = [];
  for (const portion of [0.24, 0.53, 0.79, 1]) {
    frames.push({
      phase: 'typing',
      draft: prompt.slice(0, Math.ceil(prompt.length * portion)),
      duration: portion === 1 ? 1100 : 380,
    });
  }
  frames.push({ phase: 'sent', duration: 950 });
  frames.push({ phase: 'building', duration: 1050 });
  frames.push({ phase: 'ready', duration: 1600 });
  frames.push({ phase: 'tool', duration: 2600 });
  return frames;
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  });
  const python = path.join(__dirname, '..', '..', '.venv', 'bin', 'python3');
  try {
    fs.mkdirSync(output, { recursive: true });
    for (const demo of Object.keys(stories)) {
      for (const language of ['zh', 'en']) {
        const [title, prompt] = stories[demo][language];
        const preview = path.join(output, `preview-${demo}-${language}.png`);
        execFileSync(python, [path.join(__dirname, 'compose_preview.py'), preview, demo, language], { stdio: 'inherit' });

        const directory = path.join(output, `${demo}-${language}`);
        fs.mkdirSync(directory, { recursive: true });
        const page = await browser.newPage({ viewport: { width: 1120, height: 760 }, deviceScaleFactor: 1 });
        const errors = [];
        page.on('pageerror', error => errors.push(String(error)));
        await page.goto(pathToFileURL(path.join(__dirname, 'story.html')).href);
        await page.addStyleTag({ content: '[hidden]{display:none!important}' });
        const entries = [];
        for (const [index, frame] of plan(prompt).entries()) {
          await page.evaluate(
            data =>
              window.showcase({
                language: data.language,
                prompt: data.prompt,
                title: data.title,
                phase: data.phase,
                draft: data.draft || '',
                image: data.phase === 'ready' || data.phase === 'tool' ? data.image : '',
              }),
            { ...frame, language, prompt, title, image: pathToFileURL(preview).href },
          );
          if (frame.phase === 'ready' || frame.phase === 'tool') {
            await page.waitForFunction(() => {
              const node = document.querySelector('#recording');
              return node && node.complete && node.naturalWidth > 0;
            });
          }
          const file = `${String(index).padStart(2, '0')}.png`;
          await page.screenshot({ path: path.join(directory, file) });
          entries.push({ file, duration: frame.duration });
        }
        if (errors.length) throw Error(`${demo}-${language}: ${errors.join('; ')}`);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
        if (overflow) throw Error(`${demo}-${language}: horizontal overflow`);
        fs.writeFileSync(path.join(directory, 'frames.json'), JSON.stringify(entries, null, 2));
        console.log(`${demo}-${language}: ${entries.length} frames`);
        await page.close();
      }
    }
  } finally {
    await browser.close();
  }
  execFileSync(python, [path.join(__dirname, 'compose_gif.py'), output], { stdio: 'inherit' });
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
