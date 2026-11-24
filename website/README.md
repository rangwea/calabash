# Calabash website

Independent, buildless Chinese/English landing page and usage guide. Open
`index.html` directly, or serve this directory with any static file server.
No account, analytics, remote fonts, or CDN scripts.
The download button points to the latest public GitHub Release. Preview installers
are available for macOS arm64/x64 and Windows x64; developer signing and Apple
notarization remain pending.

## Deployment

Public site: https://rangwea.github.io/calabash/

`.github/workflows/pages.yml` deploys changes under `website/` pushed to `main`.
It can also be run manually from GitHub Actions. Repository Settings → Pages
must use **GitHub Actions** as its source. The workflow publishes the two HTML
pages, CSS, JavaScript and `assets/`; recording scripts are excluded.

## Demonstrations

The five demo GIFs are real screen recordings of published tools running through
the local shared runtime, driven by `demos/record-real.cjs`. Only the input files
are synthetic: a generated workbook, generated JPEGs and a generated WebM clip.
The tool UI, the backend calls and the resulting numbers are the app's own.

What is *not* recorded is the chat shell around the tool. Each frame is the tool
pane only, so the demo shows the finished workspace rather than a model
conversation, and it makes no claim about generation speed. The tools are not
installed App modules; each was built by AI in Calabash.

Tool interfaces are Chinese-only because tool frontends hard-code their labels
(`frontend/App.tsx` has no i18n). The `-en` assets are therefore the same
capture as `-zh`; the surrounding page copy is what changes per language. Do not
describe them as English-language recordings.

Both languages have separate GIFs and WebP posters in `assets/demos`.
Animations load only for the selected visible scene; reduced-motion users
see still posters until they explicitly play a demo.

## Re-record locally

Capture runs the real tool backend and drives the real page with Playwright:

```bash
# Serve tools so they can be opened by hand
.venv/bin/python3 demos/serve-tools.py image_watermark/image_watermark

# One still per tool
.venv/bin/python3 demos/render-real.py ./out image_watermark/image_watermark

# Multi-step frames, then encode
.venv/bin/python3 demos/render-real.py ./out image_watermark/image_watermark \
  --recipe watermark --fixtures ./fixtures
.venv/bin/python3 demos/compose_gif.py ./out
```

Each recipe in `demos/record-real.cjs` moves real controls, so a renamed field
or a changed dialog breaks it loudly instead of silently producing a wrong
picture. Frames per tool: `ledger` 7, `todo` 6, `watermark` 4, `excel` 4,
`video` 3-4.

Always use a disposable `HOME` with copied tool bundles and no `data.sqlite`.
`~/.calabash` is the user's real profile: it holds real ledger entries, real
todos and real CRM rows. Never capture against it, and never copy its databases
into the captured bundle.

