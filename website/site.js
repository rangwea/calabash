(() => {
  'use strict';
  const en = {
    'skip':'Skip to content',
    'nav.demos':'In action','nav.workflow':'How it works','nav.guide':'Guide','nav.start':'Get to know Calabash',
    'hero.eyebrow':'Your ideas. Your own tools.','hero.tagline':'Build your own tools with AI.',
    'hero.description':'From a simple request to a tool you can see, use and reuse.',
    'hero.download':'Download preview','hero.demos':'See what you can make','hero.guide':'Read the guide','hero.note':'Local tools · Your choice of model · No Calabash account',
    'demos.eyebrow':'01 / YOUR WORK, NOT A FIXED TEMPLATE','demos.title':'One desktop. Many possibilities.',
    'demos.description':'Five everyday ideas.<br>Five real, usable workspaces.',
    'demos.play':'Play demo','demos.pause':'Pause demo',
    'demo.ledger.tab':'Personal finance','demo.excel.tab':'Excel product copy','demo.video.tab':'Video trimming','demo.watermark.tab':'Image watermarks','demo.todo.tab':'AI to-do',
    'workflow.eyebrow':'02 / FROM AN IDEA TO A DAILY TOOL','workflow.title':'More than an answer.<br>A tool you can keep using.','workflow.link':'Make your first tool',
    'workflow.one.title':'Describe the job to be done.','workflow.one.copy':'Explain your files, rules and desired result. Start with a simple version, then add the details that fit how you work.',
    'workflow.one.example':'“Build a sales tool. Let me switch between regions and products, then export an Excel summary.”',
    'workflow.two.title':'Try it in a real interface.','workflow.two.copy':'Adjust a form, filter a table and explore a chart. Preview the tool and check that its behavior and results match your needs.','workflow.two.detail':'An interface makes the details tangible.',
    'workflow.three.title':'Keep it local. Use it again.','workflow.three.copy':'Organize local tools by project. When your workflow changes, start a conversation from the tool and keep refining it.','workflow.three.detail':'Import and share tools as ZIP files.',
    'principles.eyebrow':'03 / BUILT AROUND REAL WORK','principles.title':'You keep the controls.<br>The tool handles the repetition.',
    'principles.description':'Not a remote office suite. Not a cloud drive.<br>Your personal tool desktop, on your computer.',
    'principles.local.title':'Your tools and files stay local.','principles.local.copy':'Local inputs, tools and result history. External models still receive your messages and relevant content you ask the agent to read. Take care with sensitive data.',
    'principles.ui.title':'An interface gives you control.','principles.ui.copy':'Stop repeating common parameters. Forms, filters, tables, charts and previews make the same tool useful for your next task.',
    'principles.output.title':'Finish with an actual file.','principles.output.copy':'Track progress, stop later batch items and open or save your results. Tools should use separate output folders and preserve original inputs.',
    'principles.control.title':'You confirm the important steps.','principles.control.copy':'Retry after a repair yourself; approve overwrites explicitly. ZIP imports validate without auto-running code. Only trust tools from sources you know.',
    'faq.eyebrow':'A FEW MORE THINGS','faq.title':'Before you start.','faq.more':'Read the full guide',
    'faq.one.q':'Are these tools built into the app?','faq.one.a':'No. These five tools were built by AI in Calabash and then recorded running on a local machine with synthetic sample data. They show what can be created, not fixed business modules built into the app.',
    'faq.two.q':'Do I need a model? Where does my data go?','faq.two.a':'Creating and editing tools requires an external model connection and your own API key. DeepSeek, OpenAI, Anthropic and Qwen are supported. Tools and results are stored locally, but model requests can include conversations and relevant file content. Local execution does not mean all data stays on your device.',
    'faq.three.q':'What does audio and video processing require?','faq.three.a':'Import a trusted FFmpeg capability ZIP in Settings. The recording environment already has it installed. It is not bundled with the main app and is not downloaded automatically. Transcription, subtitle generation and OCR are not currently provided.',
    'faq.four.q':'Can I download Calabash now?','faq.four.a':'The v1.3.1 preview is available for macOS Apple Silicon (arm64), macOS Intel (x64) and Windows x64. Download the matching installer from GitHub Releases. Developer signing and Apple notarization are still pending; do not disable system security protections to install it.',
    'closing.eyebrow':'START WITH SOMETHING YOU DO EVERY DAY.','closing.title':'Your next useful tool<br>can be your own.','closing.link':'Read the guide',
    'footer.copy':'Your own desktop for everyday tools.','footer.privacy':'Data & safety',
    'guide.contents':'IN THIS GUIDE','guide.nav.start':'Before you start','guide.nav.models':'Connect a model','guide.nav.first':'Your first tool','guide.nav.files':'Files & batch tasks','guide.nav.results':'Keep the results','guide.nav.zip':'Import & export','guide.nav.plugins':'Capability packs','guide.nav.privacy':'Data & safety','guide.nav.questions':'Troubleshooting',
    'guide.back':'Back to Calabash','guide.title':'Put your first tool to work.','guide.intro':'Connect a model, create a tool, try it and use it again.<br>No Calabash account is required. Creating and editing tools uses your own external model connection.',
    'guide.start.title':'Before you start','guide.start.copy':'Calabash is a local desktop app, not a remotely hosted administration system. Tools and results live on your computer; AI generates and edits tool code from your description.',
    'guide.start.release':'<strong>The v1.3.1 preview is available.</strong> <a href="https://github.com/rangwea/calabash/releases/latest">Download from GitHub Releases</a> for macOS arm64, macOS x64 or Windows x64. Developer signing and Apple notarization are still pending; do not disable system security protections to install it.',
    'guide.start.one':'macOS: open the DMG for your architecture and drag <strong>Calabash.app</strong> into Applications. Windows: run the x64 installer.','guide.start.two':'Wait for startup to finish. End users do not need to install Python, uv or npm separately.','guide.start.three':'Open Settings in the sidebar, configure a model connection, then choose New chat.',
    'guide.models.title':'Choose your own model','guide.models.copy':'External APIs from DeepSeek, OpenAI, Anthropic and Qwen are supported. You need an API key from your provider; Calabash does not offer a shared key or free model credits.',
    'guide.models.one':'In Settings, choose a model provider and enter its API URL and your API key.','guide.models.two':'Fetch the model list, select models available to your connection, then save.','guide.models.three':'Use the model selector below the conversation to switch models. Available versions come from the provider’s API response.',
    'guide.models.note':'Model availability, regions, limits and pricing are controlled by the provider. If a connection fails, check the key, URL, account balance and model ID. Do not paste API keys into ordinary chats.',
    'guide.first.title':'Start with a specific task','guide.first.copy':'Instead of asking for an all-purpose system, describe the input, rules, interface and output. For example:',
    'guide.first.prompt':'“Build an Excel analytics tool. Choose a sales workbook, group sales by region or product, show a table and bar chart, then export a summary workbook. Do not overwrite the input file.”',
    'guide.first.one':'Choose New chat, select a model and describe your task. Attach synthetic or de-identified sample files if needed.','guide.first.two':'Open the generated tool in the right-hand preview. Try its fields, filters and exports, and verify the results yourself.','guide.first.three':'Ask for refinements, such as a month filter or a separate list of failed items. Passing static checks does not prove a tool has been tested at runtime.','guide.first.four':'Run it again from the tool list, or use the conversation action beside a tool to continue editing it with the tool already referenced.',
    'guide.first.examples':'The five website scenarios were built by AI and recorded running locally with synthetic sample data. They show what can be created, not fixed modules built into the app.',
    'guide.files.title':'File inputs and batch tasks','guide.files.copy':'Select files inside a tool, append more or remove and clear draft selections. Check availability before running. If a file moves, changes or loses permission, select it again rather than reusing a stale reference.',
    'guide.files.one':'<strong>Directory access:</strong> For “Operation not permitted,” select the file or folder again with the system picker and review directory access in Settings.','guide.files.two':'<strong>During execution:</strong> Tools using platform components lock inputs, prevent duplicate submissions and show actual progress, successes and failures.','guide.files.three':'<strong>Cancellation:</strong> The current file is allowed to finish, then later items stop. Cancellation does not forcibly terminate a thread that is writing a file.','guide.files.four':'<strong>Retry:</strong> Use failed-item retry where available to avoid repeating successful work. Task progress is not restored across app restarts.',
    'guide.results.title':'A real file, not just a reply','guide.results.copy':'Tools using the platform’s result component write exports into separate output directories and keep result history. Open, reveal or save a copy of a result; registered results remain available after refresh and app restart.',
    'guide.results.note':'If an output is moved, deleted or changed, it is marked unavailable. Exports should create new files rather than overwrite inputs. Deleting a tool retains conversations, output files and logs, but permanently removes its source code.',
    'guide.zip.title':'Import and export tools as ZIP files','guide.zip.export':'Use the export icon beside a tool to save its ZIP. Before sharing, check the source for hard-coded keys or business data.','guide.zip.import':'Choose Import tool above the list, select a local Calabash tool ZIP and review its name, project and description before confirming.','guide.zip.conflict':'Existing tools are never overwritten by default. Rename the tool ID or explicitly approve replacing it. Running tools cannot be overwritten.',
    'guide.zip.rule':'Format & boundary','guide.zip.detail':'Details','guide.zip.contents':'ZIP contents','guide.zip.size':'Size limits','guide.zip.limits':'ZIP up to 2 MB; source up to 1 MB','guide.zip.excluded':'Not included','guide.zip.exclusions':'Chats, output files, logs and app configuration','guide.zip.source':'Import source','guide.zip.local':'Local ZIP only; no GitHub URL imports',
    'guide.zip.warning':'<strong>Import does not execute code or install dependencies.</strong> Format and syntax checks are not a security sandbox. Third-party tools can execute local code when run, so import only trusted sources.',
    'guide.plugins.title':'Capability packs are not tools','guide.plugins.copy':'Common spreadsheet, document and image libraries are bundled with the app. FFmpeg is a separate local capability pack for supported media tools. It is not bundled with the main app and is not downloaded automatically.',
    'guide.plugins.one':'Obtain a signed capability ZIP for your system from a trusted publisher.','guide.plugins.two':'Import it under Capability packs in Settings and wait for validation and self-checks to complete.','guide.plugins.three':'Return to the tool and retry manually. Do not import a capability ZIP into the tool list or treat a tool ZIP as a capability pack.',
    'guide.plugins.limits':'The current FFmpeg pack targets macOS arm64. The media adapter supports probing, audio extraction and limited format conversion, not every FFmpeg codec. OCR, transcription, subtitle generation and an Office-to-PDF engine are not currently provided.',
    'guide.privacy.title':'What local execution means','guide.privacy.local':'Tool source lives in <code>~/.calabash/tools</code>. Indexes, conversations and result metadata are stored locally. The app does not provide a cloud drive, remote administration or a Calabash account.',
    'guide.privacy.remote':'<strong>External models do not run on your computer.</strong> Your messages and relevant file content read by the agent may be sent to the selected provider. Attaching a local reference is not the same as sending file contents, but later reads still require attention to data boundaries.',
    'guide.privacy.safety':'Test with synthetic or de-identified data first. Avoid unintended access to keys, do not import untrusted code, and never include model configuration files or business attachments in a shared package.',
    'guide.questions.title':'If something goes wrong','guide.questions.model.q':'A model connection fails','guide.questions.model.a':'Check your network, API URL, key, region, model availability and provider account limits. Fetch the model list again. Never send a full API key to someone for troubleshooting.',
    'guide.questions.permission.q':'A file is inaccessible','guide.questions.permission.a':'Select it again with the system picker, review directory permissions and confirm it has not moved or changed. Browser previews and native desktop file pickers are different environments.',
    'guide.questions.repair.q':'A generated tool fails','guide.questions.repair.a':'After your confirmation, a necessary error summary can be sent to the agent for repair. File contents, keys and full logs are not sent by default. You retry manually after repair; tasks with side effects are not rerun automatically.',
    'guide.questions.zip.q':'A ZIP import fails','guide.questions.zip.a':'Confirm it is a Calabash tool ZIP, not an arbitrary source project or capability pack. Check size, format and file access. Rename conflicting tools or explicitly approve replacement, and never overwrite a running tool.'
  };
  const scenes = {
    ledger:{category:'PERSONAL FINANCE',zh:{name:'个人记账',title:'不止记一笔，更看懂每一笔。',description:'收支明细、月度趋势和分类预算放在同一个工作区。需要调整字段或统计方式？回到对话，继续修改这件工具。',steps:'输入需求 → 生成与预览 → 录入收支 → 分类筛选 → 趋势与预算 → 导出账本',alt:'个人记账工具的界面：录入、筛选、趋势图与预算进度'},en:{name:'Personal finance',title:'Not just logging. Understanding.',description:'Transactions, monthly trends and category budgets in one workspace. Need a different field or calculation? Return to the conversation and keep refining your tool.',steps:'Request → Generate & preview → Add a transaction → Filter → Review trends & budgets → Export',alt:'Ledger interface: transactions, filters, a trend chart and budgets'}},
    excel:{category:'SPREADSHEETS',zh:{name:'Excel 商品文案',title:'一张商品表，逐行写出介绍。',description:'上传表格、选定商品名称和特点两列，工具逐行生成商品介绍。生成前确认要发送的内容，人工修改后导出为新工作簿，原表不改动。',steps:'输入需求 → 生成与预览 → 上传表格 → 选择两列 → 读取商品行 → 生成与修改 → 导出新文件',alt:'Excel 商品文案工具上传表格、选择两列、读取商品行并逐行生成介绍'},en:{name:'Excel product copy',title:'One product sheet. Copy for every row.',description:'Upload a sheet and pick the name and feature columns, then write copy row by row. Confirm what gets sent, edit the draft, and export to a new workbook without touching the original.',steps:'Request → Generate & preview → Upload sheet → Pick two columns → Read rows → Generate & edit → Export a new file',alt:'Excel product copy tool uploading a sheet, picking columns, reading rows and writing copy'}},
    video:{category:'VIDEO EDITING',zh:{name:'视频剪裁',title:'只要那十秒，不必装一整套剪辑软件。',description:'选择本地视频，设置起止时间，剪出需要的片段并保存为新文件。原始视频始终保留。',steps:'输入需求 → 生成与预览 → 选择视频 → 设置起止 → 预览片段 → 导出新文件',alt:'视频剪裁工具选择视频、设置起止时间并导出新片段'},en:{name:'Video trimming',title:'Ten seconds you need, without a whole editor.',description:'Choose a local video, set the start and end, and save the segment as a new file. The original video is always kept.',steps:'Request → Generate & preview → Choose video → Set range → Preview clip → Export new file',alt:'Video trimming tool choosing a video, setting a range and exporting a clip'}},
    watermark:{category:'IMAGES & BATCH WORK',zh:{name:'图片水印',title:'给一批图片，盖上同一句话。',description:'批量添加可重复的文字水印，调整颜色、透明度、大小、角度与间距，再统一导出为新图片，原图不改动。',steps:'输入需求 → 生成与预览 → 选择图片 → 设置水印 → 调整效果 → 批量导出',alt:'图片水印工具选择图片、设置文字水印参数并批量导出'},en:{name:'Image watermarks',title:'One line of text across a whole batch.',description:'Add a repeating text watermark in bulk, tuning colour, opacity, size, angle and spacing, then export new images while the originals stay untouched.',steps:'Request → Generate & preview → Choose images → Set watermark → Tune the result → Export batch',alt:'Watermark tool choosing images, setting text parameters and exporting a batch'}},
    todo:{category:'EVERYDAY LISTS',zh:{name:'AI 待办',title:'说一句，就记下来了。',description:'输入一句话创建待办，AI 同时给出整理建议。完成、编辑、删除、筛选与搜索都在同一处，数据保存在本机。',steps:'输入需求 → 生成与预览 → 说一句话 → AI 整理建议 → 完成与筛选 → 本地保存',alt:'AI 待办工具用一句话创建任务、查看建议并筛选列表'},en:{name:'AI to-do',title:'Say it once. It is recorded.',description:'Describe a task in one sentence and AI suggests how to organise it. Complete, edit, delete, filter and search in one place, stored locally.',steps:'Request → Generate & preview → Say one sentence → AI suggests → Complete & filter → Stored locally',alt:'AI to-do tool creating a task from one sentence, showing suggestions and filtering'}},
  };
  const originals = new Map();
  document.querySelectorAll('[data-i18n]').forEach(node => originals.set(node,node.innerHTML));
  const parameters = new URLSearchParams(location.search);
  let saved;
  try {saved = localStorage.getItem('calabash-site-language');} catch {}
  let language = ['zh','en'].includes(parameters.get('lang')) ? parameters.get('lang') : ['zh','en'].includes(saved) ? saved : navigator.language.startsWith('zh') ? 'zh' : 'en';
  let selected = Object.hasOwn(scenes,parameters.get('demo')) ? parameters.get('demo') : 'ledger';
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let playing = !motion.matches;
  let visible = false;
  const image = document.getElementById('demo-image');
  const playButton = document.getElementById('demo-play');

  function updateAddress() {
    try {
      const url = new URL(location.href);
      url.searchParams.set('lang', language);
      if (image) url.searchParams.set('demo',selected);
      history.replaceState(null,'',url);
    } catch {}
  }
  function updatePlayback() {
    if (!image) return;
    const animate = playing && visible;
    const next = `assets/demos/${selected}-${language}.${animate ? 'gif' : 'webp'}`;
    if (image.getAttribute('src') !== next) image.src = next;
    const action = animate ? (language==='en'?'Pause demo':'暂停演示') : (language==='en'?'Play demo':'播放演示');
    playButton.querySelector('img').src = `assets/icons/${animate?'pause':'play'}.svg`;
    playButton.querySelector('span').textContent = action;
    playButton.setAttribute('aria-label',action);
    playButton.setAttribute('aria-pressed',String(animate));
  }
  function showScene(name, focus=false) {
    if (!Object.hasOwn(scenes,name)) return;
    selected=name;
    const scene=scenes[name], copy=scene[language];
    if (!image) return;
    document.querySelectorAll('[data-demo]').forEach(button=>{
      const active=button.dataset.demo===name;
      button.setAttribute('aria-selected',String(active));
      button.tabIndex=active?0:-1;
      if (active && focus) button.focus();
    });
    document.getElementById('demo-panel').setAttribute('aria-labelledby',`tab-${name}`);
    document.getElementById('demo-window-name').textContent=copy.name;
    document.getElementById('demo-category').textContent=scene.category;
    document.getElementById('demo-name').textContent=copy.title;
    document.getElementById('demo-description').textContent=copy.description;
    const requests = {
      ledger:['做一个记账工具，支持分类、月度趋势、预算和导出。','Build a ledger with categories, monthly trends, budgets and export.'],
      excel:['上传一张商品表，为每行生成商品介绍，改完导出新表。','Upload a product sheet, write copy for every row, then export a new file.'],
      video:['选一个本地视频，剪出需要的片段并导出新文件。','Pick a local video, cut the segment you need and export a new file.'],
      watermark:['给一批图片加上重复文字水印，统一导出为新图。','Add a repeating text watermark to a batch of images and export new copies.'],
      todo:['用一句话记下待办，让它给出整理建议。','Record a to-do in one sentence and get suggestions on how to organise it.']
    };
    document.getElementById('demo-request-label').textContent=language==='en'?'START WITH A REQUEST':'从一句需求开始';
    document.getElementById('demo-request').textContent=requests[name][language==='en'?1:0];
    document.getElementById('demo-steps').textContent=copy.steps;
    document.getElementById('demo-requirement').textContent=name==='video'?(language==='en'?'Requires the local FFmpeg capability pack.':'需先安装本地 FFmpeg 能力插件。'):(language==='en'?'A real example tool, not a fixed module built into the app.':'这是可创建的真实工具示例，并非 App 固定内置模块。');
    document.getElementById('demo-file').href=`assets/demos/${name}-${language}.gif`;
    document.getElementById('demo-file').setAttribute('aria-label',language==='en'?'Open the GIF file':'打开 GIF 文件');
    image.alt=copy.alt;
    updatePlayback();
    updateAddress();
  }
  function setLanguage(next) {
    language=next;
    document.documentElement.lang=next==='en'?'en':'zh-CN';
    document.querySelectorAll('[data-i18n]').forEach(node=>{
      node.innerHTML=next==='en'?(en[node.dataset.i18n]??originals.get(node)):originals.get(node);
    });
    document.querySelectorAll('[data-language-label]').forEach(node=>node.textContent=next==='en'?'中文':'EN');
    document.querySelectorAll('[data-language-toggle]').forEach(button=>button.setAttribute('aria-label',next==='en'?'切换为中文':'Switch to English'));
    document.querySelectorAll('[data-hero-image]').forEach(node=>{
      node.style.backgroundImage=`url("assets/demos/hero-${next}.webp")`;
      node.setAttribute('aria-label',next==='en'?'Calabash workspace with chat on the left and an interactive tool preview on the right':'Calabash 左侧聊天与右侧工具预览，展示从需求到可操作工具的工作区');
    });
    const guide=document.body.dataset.page==='guide';
    document.title=guide?(next==='en'?'Getting started — Calabash':'使用指南 — Calabash'):(next==='en'?'Calabash — Build your own tools with AI':'Calabash — 用 AI 创建你自己的办公工具');
    document.querySelector('meta[name="description"]').content=guide?(next==='en'?'The Calabash guide: models, local tools, files, batch tasks, ZIP sharing and data safety.':'Calabash 使用指南：模型配置、本地工具、文件处理、批量任务、ZIP 分享与数据安全。'):(next==='en'?'Build your own tools with AI. A local desktop for personal finance, spreadsheets, customers, documents and media.':'Calabash：用 AI 创建你自己的办公工具。一个本地运行、带真实操作界面的个人工具桌面。');
    document.querySelectorAll('a[href]').forEach(link=>{
      const href=link.getAttribute('href');
      if (!/^(index|guide)\.html/.test(href)) return;
      const url=new URL(href,location.href);
      url.searchParams.set('lang',next);
      link.setAttribute('href',url.pathname.split('/').pop()+url.search+url.hash);
    });
    try {localStorage.setItem('calabash-site-language',next);} catch {}
    if (image) showScene(selected); else updateAddress();
  }
  document.querySelectorAll('[data-language-toggle]').forEach(button=>button.addEventListener('click',()=>setLanguage(language==='zh'?'en':'zh')));
  document.querySelectorAll('[data-demo]').forEach(button=>{
    button.addEventListener('click',()=>showScene(button.dataset.demo));
    button.addEventListener('keydown',event=>{
      const names=Object.keys(scenes), index=names.indexOf(selected);
      let next;
      if (event.key==='ArrowRight') next=names[(index+1)%names.length];
      else if (event.key==='ArrowLeft') next=names[(index-1+names.length)%names.length];
      else if (event.key==='Home') next=names[0];
      else if (event.key==='End') next=names.at(-1);
      if (next) {event.preventDefault(); showScene(next,true);}
    });
  });
  if (image) {
    new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;updatePlayback();},{threshold:.12}).observe(document.getElementById('demo-frame'));
    playButton.addEventListener('click',()=>{playing=!playing;updatePlayback();});
    motion.addEventListener('change',event=>{playing=!event.matches;updatePlayback();});
  }
  const menu=document.querySelector('[data-menu-toggle]');
  if (menu) {
    const close=()=>{menu.setAttribute('aria-expanded','false');document.getElementById('nav-links').classList.remove('is-open');menu.querySelector('img').src='assets/icons/menu.svg';};
    menu.addEventListener('click',()=>{
      const open=menu.getAttribute('aria-expanded')!=='true';
      menu.setAttribute('aria-expanded',String(open));
      document.getElementById('nav-links').classList.toggle('is-open',open);
      menu.querySelector('img').src=`assets/icons/${open?'x':'menu'}.svg`;
    });
    document.querySelectorAll('.nav-links a').forEach(link=>link.addEventListener('click',close));
    document.addEventListener('keydown',event=>{if(event.key==='Escape')close();});
  }
  const guideLinks=[...document.querySelectorAll('.guide-nav a')];
  if (guideLinks.length) {
    const observer=new IntersectionObserver(entries=>{
      const active=entries.filter(entry=>entry.isIntersecting).sort((a,b)=>a.boundingClientRect.top-b.boundingClientRect.top)[0];
      if(active)guideLinks.forEach(link=>{const selected=link.hash==='#'+active.target.id;link.classList.toggle('active',selected);if(selected)link.setAttribute('aria-current','location');else link.removeAttribute('aria-current');});
    },{rootMargin:'-100px 0px -60% 0px'});
    document.querySelectorAll('.guide-section').forEach(section=>observer.observe(section));
  }
  setLanguage(language);
})();
