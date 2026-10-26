// Compose an explicitly illustrated chat flow with actual recorded tool states.
// No model calls, real keys, personal tools or user databases are accessed.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '/Applications/ChatGPT.app/Contents/Resources/cua_node/lib/node_modules/playwright');
const source=process.argv[2], destination=process.argv[3];
if(!source||!destination) throw Error('Usage: node record-story.cjs <real-frames-directory> <story-frames-directory>');
const stories={
  ledger:[['个人账本','Personal ledger'],['做一个记账工具：记录收支、分类筛选，查看月度趋势和预算，支持导出账本。','Build a ledger with income and expenses, category filters, monthly trends, budgets and CSV export.']],
  excel:[['销售数据工作台','Sales analytics'],['创建 Excel 销售统计工具：读取工作簿，按地区或产品汇总，用图表展示，导出统计结果。','Create an Excel sales tool: read a workbook, summarize by region or product, show charts and export the results.']],
  customers:[['客户关系工作台','Customer workspace'],['帮我做一个客户管理工具：搜索客户、管理销售阶段、保存跟进记录，并导出客户列表。','Build a customer workspace with search, sales stages, saved follow-up notes and customer list export.']],
  documents:[['文档工作台','Document workspace'],['创建 PDF 整理工具：预览页面、调整文件顺序、选择页码，再合并成一份新的 PDF。','Create a PDF workspace: preview pages, reorder files, select page ranges and merge them into a new PDF.']],
  media:[['音视频工作台','Media workspace'],['做一个音视频工具：预览视频，设置起止时间，批量提取 FLAC 音频，保留原文件。','Build a media tool: preview videos, set a time interval and batch-extract FLAC audio without changing the originals.']]
};
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try{
    for(const language of ['zh','en']) for(const [name,copy] of Object.entries(stories)){
      const key=`${name}-${language}`,root=path.join(destination,key),index=language==='en'?1:0;
      const manifest=JSON.parse(fs.readFileSync(path.join(source,key,'frames.json')));
      assert.equal(manifest.length,6);
      fs.mkdirSync(root,{recursive:true});
      const page=await browser.newPage({viewport:{width:1120,height:760},deviceScaleFactor:1});
      const errors=[];page.on('pageerror',e=>errors.push(String(e)));
      await page.goto(pathToFileURL(path.join(__dirname,'story.html')).href);
      await page.addStyleTag({content:'[hidden]{display:none!important}'});
      const frames=[],prompt=copy[1][index],title=copy[0][index];
      async function capture(phase,duration,extra={}){
        await page.evaluate(data=>window.showcase(data),{language,prompt,title,phase,...extra});
        if(extra.image)await page.waitForFunction(()=>{const i=document.querySelector('#recording');return i.complete&&i.naturalWidth>0;});
        const file=`${String(frames.length).padStart(2,'0')}.png`;
        await page.screenshot({path:path.join(root,file)});frames.push({file,duration});
      }
      for(const portion of [.24,.53,.79,1])await capture('typing',portion===1?1000:360,{draft:prompt.slice(0,Math.ceil(prompt.length*portion))});
      await capture('sent',800);await capture('building',900);
      const realImage=n=>pathToFileURL(path.resolve(source,key,manifest[n].file)).href;
      await capture('ready',1400,{image:realImage(0)});
      for(let n=0;n<manifest.length;n++)await capture('tool',n===5?2400:manifest[n].duration,{image:realImage(n),step:n+1});
      fs.writeFileSync(path.join(root,'frames.json'),JSON.stringify(frames,null,2));
      assert.deepEqual(errors,[]);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      console.log(`${key}: input → generation illustration → real preview → six real tool states`);
      await page.close();
    }
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
