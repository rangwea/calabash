// Host-owned compiler configuration. Tool bundles cannot provide Vite plugins.
import { build, createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { dirname, resolve, relative, isAbsolute, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { writeFileSync, copyFileSync, realpathSync, existsSync } from 'node:fs'
import { spawnSync } from 'node:child_process'

const libraryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const within = (base, file) => { const path = relative(base, file); return path === '' || path !== '..' && !path.startsWith('..' + sep) && !isAbsolute(path) }
const [mode, sourceRoot, backendPort, port] = process.argv.slice(2)
if (!['build', 'serve'].includes(mode) || !sourceRoot) throw new Error('Invalid compiler invocation')
// Canonicalize macOS /var and /private/var aliases before Vite computes assets.
const root = realpathSync(sourceRoot)
const config = {
  configFile: false, root, cacheDir: resolve(root, 'node_modules/.vite'), plugins: [
    { name: 'calabash-source-boundary', enforce: 'pre',
      resolveId(source, importer) {
        if (!importer || !within(resolve(root, 'frontend'), importer.split('?')[0])) return
        if (source === '@calabash/api') return
        if (isAbsolute(source) && source.split('?')[0] === resolve(root, 'calabash-api.ts')) return
        if (source === '\0plugin-vue:export-helper' || source === '/@vite/client') return
        if (isAbsolute(source) && within(resolve(root, 'frontend'), source.split('?')[0])) return
        if (isAbsolute(source) && ['vue', 'element-plus', '@element-plus/icons-vue', 'echarts'].some(name => within(resolve(libraryRoot, 'node_modules', name), source.split('?')[0]))) return
        if (source.startsWith('.')) {
          if (!within(resolve(root, 'frontend'), resolve(dirname(importer.split('?')[0]), source))) throw new Error('Tool imports must stay inside frontend/')
        } else if (!['vue', 'element-plus', '@element-plus/icons-vue', 'echarts'].some(name => source === name || source.startsWith(name + '/'))) {
          throw new Error('Use only bundled frontend libraries and relative frontend files: ' + source.slice(0, 120))
        }
      },
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          let path
          try { path = decodeURIComponent((req.url || '/').split('?')[0]) } catch { res.statusCode = 400; return res.end() }
          const generated = ['/entry.ts', '/probe.js', '/runtime-ui.mjs', '/calabash-api.ts', '/calabash-client.ts']
          if (path.startsWith('/@fs/')) {
            const file = resolve(process.platform === 'win32' ? path.slice(5) : path.slice(4))
            if (!within(resolve(libraryRoot, 'node_modules'), file) && !within(resolve(root, 'frontend'), file) && !generated.some(name => file === resolve(root, '.' + name))) { res.statusCode = 403; return res.end() }
          } else if (!(path === '/' || generated.includes(path) || path.startsWith('/frontend/') || path.startsWith('/api/') || path.startsWith('/@') || path.startsWith('/node_modules/.vite/'))) { res.statusCode = 404; return res.end() }
          res.setHeader('Referrer-Policy', 'no-referrer'); next()
        })
      },
    }, vue()],
  resolve: { alias: {
    '@calabash/api': resolve(root, 'calabash-api.ts'),
    vue: resolve(libraryRoot, 'node_modules/vue/dist/vue.esm-bundler.js'),
    'element-plus': resolve(libraryRoot, 'node_modules/element-plus'),
    '@element-plus/icons-vue': resolve(libraryRoot, 'node_modules/@element-plus/icons-vue/dist/index.js'),
    echarts: resolve(libraryRoot, 'node_modules/echarts'),
  } },
  build: { outDir: resolve(root, 'dist'), emptyOutDir: true },
  server: { host: '127.0.0.1', port: Number(port), strictPort: true, cors: false,
    fs: { strict: true, allow: [root, resolve(libraryRoot, 'node_modules')] },
    proxy: { '/api': `http://127.0.0.1:${Number(backendPort)}` } },
}
writeFileSync(resolve(root, 'index.html'), '<!doctype html><html><head><script src="/api/sdk/runtime-guard.js"></script><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>body{margin:0;font-family:-apple-system,BlinkMacSystemFont,sans-serif;color:#263445}html{--el-color-primary:#0f6cbd}.calabash-files{display:grid;gap:10px;margin:12px 0}.calabash-results,.calabash-job-status{margin:12px 0;font-size:13px}.calabash-results>div{padding:6px 0}.el-dialog{max-width:calc(100vw - 32px)}</style></head><body><div id="app"></div><script type="module" src="/entry.ts"></script></body></html>')
copyFileSync(resolve(libraryRoot, 'component/frontend_probe.js'), resolve(root, 'probe.js'))
copyFileSync(resolve(libraryRoot, 'scripts/tool_runtime_ui.mjs'), resolve(root, 'runtime-ui.mjs'))
copyFileSync(resolve(libraryRoot, 'scripts/tool_api_client.ts'), resolve(root, 'calabash-client.ts'))
const themeImport = existsSync(resolve(root, 'frontend/calabash-theme.css')) ? "import './frontend/calabash-theme.css';" : ''
writeFileSync(resolve(root, 'entry.ts'), `import {createApp} from 'vue';import ElementPlus from 'element-plus';import 'element-plus/dist/index.css';import App from './frontend/App.vue';import * as components from './runtime-ui.mjs';import {installProbe} from './probe.js';${themeImport}document.querySelector('#app').className='calabash-tool';const transport=window.fetch.bind(window);const errors=[];const probe=installProbe(window,e=>{if(errors.length<40)errors.push(e)});const page=crypto.randomUUID();const app=createApp(App).use(ElementPlus);for(const [name,component] of Object.entries(components))app.component(name,component);app.mount('#app');async function poll(){while(true){try{const command=await(await transport('/api/sdk/debug/next')).json();if(command.id){let result=command.operation==='snapshot'?{page,...probe.snapshot(),events:errors}:probe.operate(command.request);await transport('/api/sdk/debug/result',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:command.id,result})});}}catch{}await new Promise(r=>setTimeout(r,250));}}poll();`)
if (mode === 'build') {
  const paths = Object.fromEntries(['vue', 'element-plus', '@element-plus/icons-vue', 'echarts'].flatMap(name => [[name, [resolve(libraryRoot, 'node_modules', name)]], [name + '/*', [resolve(libraryRoot, 'node_modules', name, '*')]]]))
  paths['@calabash/api'] = [resolve(root, 'calabash-api.ts')]
  writeFileSync(resolve(root, 'host-components.d.ts'), `import type {DefineComponent} from 'vue';declare module 'vue' {interface GlobalComponents {CalabashFiles:DefineComponent<any>;CalabashResults:DefineComponent<any>;CalabashJobStatus:DefineComponent<any>;CalabashChart:DefineComponent<any>}}export {};`)
  writeFileSync(resolve(root, 'tsconfig.json'), JSON.stringify({
    compilerOptions: { target: 'ES2022', module: 'ESNext', moduleResolution: 'Bundler', lib: ['ES2022', 'DOM', 'DOM.Iterable'], strict: true, skipLibCheck: true, noEmit: true, allowJs: true, checkJs: false, types: [], paths },
    vueCompilerOptions: { strictTemplates: true },
    include: ['frontend/**/*.vue', 'frontend/**/*.ts', 'host-components.d.ts', resolve(libraryRoot, 'node_modules/element-plus/global.d.ts')],
  }))
  const check = spawnSync(process.execPath, [resolve(libraryRoot, 'node_modules/vue-tsc/bin/vue-tsc.js'), '--project', resolve(root, 'tsconfig.json'), '--noEmit'], { stdio: 'inherit' })
  if (check.status !== 0) throw new Error('Tool Vue/TypeScript validation failed')
  try { await build(config) } catch (error) {
    const file = typeof error.loc?.file === 'string' ? error.loc.file : error.id
    const path = typeof file === 'string' ? relative(root, file.split('?')[0]).replaceAll('\\', '/') : ''
    const diagnostic = {code: 'VITE', message: 'Vue 编译失败，请检查此处语法或导入'}
    if (path.startsWith('frontend/') && !path.split('/').includes('..')) diagnostic.file = path
    if (Number.isSafeInteger(error.loc?.line) && error.loc.line > 0) diagnostic.line = error.loc.line
    if (Number.isSafeInteger(error.loc?.column) && error.loc.column >= 0) diagnostic.column = error.loc.column + 1
    writeFileSync(resolve(root, 'build-diagnostics.json'), JSON.stringify(diagnostic))
    throw error
  }
}
else { const server = await createServer(config); await server.listen(); console.log('CALABASH_TOOL_READY', server.resolvedUrls.local[0]); }
