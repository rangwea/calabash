# Calabash website

Independent, buildless Chinese/English landing page and usage guide. Open
`index.html` directly, or serve this directory with any static file server.
No account, analytics, remote fonts, CDN scripts, or deployment configuration.
The site deliberately has no download button until a public release exists.

## Demonstrations

The five examples are real NiceGUI tools with real SQLite, spreadsheet, PDF,
and media operations. GIFs begin with an explicitly labeled illustrated chat
flow: typed request, submitted message and accelerated generation states.
Those chat messages are scripted illustrations, not recorded model responses
or generation-speed claims. The right-side preview then shows actual captured
tool operations. All people, companies, transactions and files are synthetic.
These tools are website examples, not installed App modules.

Both languages have separate GIFs and WebP posters in `assets/demos`.
Animations load only for the selected visible scene; reduced-motion users
see still posters until they explicitly play a demo.

## Re-record locally

From the repository root, use a disposable HOME, never your normal HOME:

```sh
mkdir -p /private/tmp/calabash-website-showcase/home
HOME=/private/tmp/calabash-website-showcase/home .venv/bin/python3 website/demos/server.py \
  --data /private/tmp/calabash-website-showcase/data \
  --plugin /absolute/path/to/signed-ffmpeg-plugin.zip
```

Use the printed random local port in the recorder command:

```sh
SHOWCASE_HOME=/private/tmp/calabash-website-showcase/home \
  node website/demos/record.cjs http://127.0.0.1:PORT /private/tmp/calabash-website-showcase/frames
.venv/bin/python3 website/demos/render_gifs.py \
  /private/tmp/calabash-website-showcase/frames website/assets/demos
node website/demos/record-story.cjs \
  /private/tmp/calabash-website-showcase/frames /private/tmp/calabash-website-showcase/stories
.venv/bin/python3 website/demos/render_gifs.py \
  /private/tmp/calabash-website-showcase/stories website/assets/demos --workflow
```

The recorder uses Playwright and Chrome; override `PLAYWRIGHT_MODULE` and
`CHROME_PATH` for your machine. It replaces only the native file picker with
selection of the generated fixtures. All subsequent operations are real.
Optional `SHOWCASE_HOME` resets only the named synthetic ledger/customer
databases, making repeated recordings deterministic.

The media scenario needs the existing signed FFmpeg capability ZIP.
On macOS, fixture preparation uses the OS `avconvert` to make its synthetic
video browser-playable. This is a recording tool only, not an App runtime
dependency. No real model calls or user documents are used.

Lucide icons are vendored under their included ISC license. The favicon
comes from the repository's Calabash application icon.

## Validation

```sh
node website/demos/check-site.cjs
```

Checks both languages, all five demos, playback, reduced motion, mobile
navigation, local asset loading, guide navigation and horizontal overflow.
