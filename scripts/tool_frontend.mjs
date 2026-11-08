// Host-owned React compiler. Tool bundles cannot provide plugins or dependencies.
import { build, createServer } from 'vite'
import react from '@vitejs/plugin-react'
import { dirname, resolve, relative, isAbsolute, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { writeFileSync, copyFileSync, realpathSync, existsSync } from 'node:fs'
import { spawn } from 'node:child_process'
let checker, previewServer, stopping = false
async function shutdown() {
  if (stopping) return
  stopping = true; checker?.kill(); await previewServer?.close(); process.exit(0)
}
process.stdin.resume(); process.stdin.on('end', shutdown)
process.on('SIGTERM', shutdown); process.on('SIGINT', shutdown)
const libraryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const within = (base, file) => { const path = relative(base, file); return path === '' || path !== '..' && !path.startsWith('..' + sep) && !isAbsolute(path) }
const [mode, sourceRoot, backendPort, port, workingSource] = process.argv.slice(2)
if (!['build', 'serve'].includes(mode) || !sourceRoot) throw new Error('Invalid compiler invocation')
const root = realpathSync(sourceRoot)
const frontend = resolve(realpathSync(workingSource || sourceRoot), 'frontend')
const libraries = ['react', 'react-dom', 'antd', '@ant-design/icons', 'echarts']
const generated = ['/entry.tsx', '/probe.js', '/runtime-ui.tsx', '/calabash-api.ts', '/calabash-client.ts']
const alias = Object.fromEntries(libraries.map(name => [name, resolve(libraryRoot, 'node_modules', name)]))
Object.assign(alias, { '@calabash/api': resolve(root, 'calabash-api.ts'), '@calabash/ui': resolve(root, 'runtime-ui.tsx'), '@tool': frontend })
const config = {
  configFile: false, root, cacheDir: resolve(root, 'node_modules/.vite'),
  plugins: [{ name: 'calabash-source-boundary', enforce: 'pre', resolveId(source, importer) {
    if (!importer || !within(frontend, importer.split('?')[0])) return
    if (['@calabash/api', '@calabash/ui', '/@vite/client', '/@react-refresh'].includes(source)) return
    if (isAbsolute(source) && (within(frontend, source.split('?')[0]) || libraries.some(name => within(resolve(libraryRoot, 'node_modules', name), source.split('?')[0])) || ['calabash-api.ts', 'runtime-ui.tsx'].some(name => source === resolve(root, name)))) return
    if (source.startsWith('.')) {
      if (!within(frontend, resolve(dirname(importer.split('?')[0]), source))) throw new Error('Tool imports must stay inside frontend/')
    } else if (!libraries.some(name => source === name || source.startsWith(name + '/'))) throw new Error('Use only bundled frontend libraries and relative frontend files')
  }, configureServer(server) {
    server.middlewares.use((req, res, next) => {
      let path
      try { path = decodeURIComponent((req.url || '/').split('?')[0]) } catch { res.statusCode = 400; return res.end() }
      if (path.startsWith('/@fs/')) {
        const file = resolve(process.platform === 'win32' ? path.slice(5) : path.slice(4))
        if (!within(resolve(libraryRoot, 'node_modules'), file) && !within(frontend, file) && !generated.some(name => file === resolve(root, '.' + name))) { res.statusCode = 403; return res.end() }
      } else if (!(path === '/' || generated.includes(path) || path.startsWith('/frontend/') || path.startsWith('/api/') || path.startsWith('/@') || path.startsWith('/node_modules/.vite/'))) { res.statusCode = 404; return res.end() }
      res.setHeader('Referrer-Policy', 'no-referrer'); next()
    })
  } }, react()],
  resolve: { alias, dedupe: ['react', 'react-dom'] },
  build: { outDir: resolve(root, 'dist'), emptyOutDir: true },
  server: { host: '127.0.0.1', port: Number(port), strictPort: true, cors: false, fs: { strict: true, allow: [root, frontend, resolve(libraryRoot, 'node_modules')] }, proxy: { '/api': `http://127.0.0.1:${Number(backendPort)}` } },
}
writeFileSync(resolve(root, 'index.html'), '<!doctype html><html><head><script src="/api/sdk/runtime-guard.js"></script><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>body{margin:0;font-family:-apple-system,BlinkMacSystemFont,sans-serif;color:#263445}*{box-sizing:border-box}.calabash-tool{min-width:0}img,video{max-width:100%}</style></head><body><div id="app" class="calabash-tool"></div><script type="module" src="/entry.tsx"></script></body></html>')
copyFileSync(resolve(libraryRoot, 'component/frontend_probe.js'), resolve(root, 'probe.js'))
copyFileSync(resolve(libraryRoot, 'scripts/tool_runtime_ui.tsx'), resolve(root, 'runtime-ui.tsx'))
copyFileSync(resolve(libraryRoot, 'scripts/tool_api_client.ts'), resolve(root, 'calabash-client.ts'))
const themeImport = existsSync(resolve(frontend, 'calabash-theme.css')) ? "import '@tool/calabash-theme.css';" : ''
writeFileSync(resolve(root, 'entry.tsx'), `import React from 'react';import {createRoot} from 'react-dom/client';import {ConfigProvider,App as AntApp} from 'antd';import 'antd/dist/reset.css';import App from '@tool/App.tsx';import {themeTokens,ToolErrorBoundary} from './runtime-ui';import {installProbe} from './probe.js';${themeImport}const transport=window.fetch.bind(window);const errors=[];const probe=installProbe(window,e=>{if(errors.length<40)errors.push(e)});const page=crypto.randomUUID();createRoot(document.getElementById('app')!).render(<ConfigProvider theme={{token:themeTokens()}}><AntApp><ToolErrorBoundary><App/></ToolErrorBoundary></AntApp></ConfigProvider>);async function poll(){while(true){try{const command=await(await transport('/api/sdk/debug/next')).json();if(command.id){const result=command.operation==='snapshot'?{page,...probe.snapshot(),events:errors}:probe.operate(command.request);await transport('/api/sdk/debug/result',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:command.id,result})});}}catch{}await new Promise(r=>setTimeout(r,250));}}poll();`)
if (mode === 'build') {
  const paths = Object.fromEntries(libraries.flatMap(name => [[name, [resolve(libraryRoot, 'node_modules', name === 'react' || name === 'react-dom' ? '@types/' + name : name)]], [name + '/*', [resolve(libraryRoot, 'node_modules', name === 'react' || name === 'react-dom' ? '@types/' + name : name, '*')]]]))
  paths['@calabash/api'] = [resolve(root, 'calabash-api.ts')]; paths['@calabash/ui'] = [resolve(root, 'runtime-ui.tsx')]
  writeFileSync(resolve(root, 'tsconfig.json'), JSON.stringify({ compilerOptions: { target: 'ES2022', module: 'ESNext', moduleResolution: 'Bundler', jsx: 'react-jsx', lib: ['ES2022', 'DOM', 'DOM.Iterable'], strict: true, skipLibCheck: true, noEmit: true, allowJs: true, checkJs: false, esModuleInterop: true, types: ['react','react-dom'], typeRoots: [resolve(libraryRoot, 'node_modules/@types')], paths }, include: ['frontend/**/*.tsx', 'frontend/**/*.ts', 'runtime-ui.tsx'] }))
  const status = await new Promise((done, reject) => { checker = spawn(process.execPath, [resolve(libraryRoot, 'node_modules/typescript/bin/tsc'), '--project', resolve(root, 'tsconfig.json'), '--noEmit'], { stdio: ['ignore', 'inherit', 'inherit'] }); checker.once('error', reject); checker.once('close', done) })
  checker = undefined
  if (status !== 0) throw new Error('Tool React/TypeScript validation failed')
  try { await build(config) } catch (error) {
    const file = typeof error.loc?.file === 'string' ? error.loc.file : error.id
    const path = typeof file === 'string' ? relative(root, file.split('?')[0]).replaceAll('\\', '/') : ''
    const diagnostic = { code: 'VITE', message: 'React 编译失败，请检查此处语法或导入' }
    if (path.startsWith('frontend/') && !path.split('/').includes('..')) diagnostic.file = path
    if (Number.isSafeInteger(error.loc?.line) && error.loc.line > 0) diagnostic.line = error.loc.line
    writeFileSync(resolve(root, 'build-diagnostics.json'), JSON.stringify(diagnostic)); throw error
  }
  process.stdin.destroy()
} else { previewServer = await createServer(config); await previewServer.listen(); console.log('CALABASH_TOOL_READY', previewServer.resolvedUrls.local[0]) }
