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
    zh: ['个人记账', '做一个记账工具：记录收支、分类筛选，查看月度趋势和预算，支持导出账本。'],
    en: ['Personal finance', 'Build a ledger with income and expenses, category filters, monthly trends, budgets and CSV export.'],
  },
  excel: {
    zh: ['Excel 统计', '创建一个 Excel 统计工具：读取工作簿，按地区或产品汇总，用图表展示，导出统计结果。'],
    en: ['Excel analytics', 'Create an Excel tool: read a workbook, summarize by region or product, show charts and export the results.'],
  },
  video: {
    zh: ['视频剪裁', '做一个视频剪裁工具：选择本地视频，设置起止时间，剪出需要的片段并导出新文件。'],
    en: ['Video trimming', 'Build a trimming tool: choose a local video, set start and end, cut the segment and export a new file.'],
  },
  watermark: {
    zh: ['图片水印', '做一个图片水印工具：批量添加重复文字水印，可调颜色、透明度、角度和间距。'],
    en: ['Image watermarks', 'Build a watermark tool: add repeating text to a batch of images, with colour, opacity, angle and spacing controls.'],
  },
  todo: {
    zh: ['AI 待办', '做一个 AI 待办工具：输入一句话创建任务，给出整理建议，支持完成、筛选与搜索。'],
    en: ['AI to-do', 'Build an AI to-do tool: create a task from one sentence, suggest how to organise it, and support completion, filters and search.'],
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
