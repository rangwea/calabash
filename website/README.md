# Calabash website

Independent, buildless Chinese/English landing page and usage guide. Open
`index.html` directly, or serve this directory with any static file server.
No account, analytics, remote fonts, CDN scripts, or deployment configuration.
The site deliberately has no download button until a public release exists.

## Demonstrations

The five recorded examples demonstrate SQLite, spreadsheet, PDF and media
workflows using synthetic data. Their illustrated chat steps are scripted,
not recorded model responses or generation-speed claims. Existing GIFs and
posters show the earlier desktop UI; the current app uses React + Ant Design.
These examples are not installed App modules.

Both languages have separate GIFs and WebP posters in `assets/demos`.
Animations load only for the selected visible scene; reduced-motion users
see still posters until they explicitly play a demo.

## Re-record locally

Record the current React desktop app using a disposable HOME and synthetic
React/Python tool bundles. Never use the normal user HOME or real model credits.
The previous server-side UI demonstration runner has been removed.

`demos/prepare.py` prepares synthetic files. `demos/record-story.cjs` and
`demos/story.html` compose illustrated chat flows from captured tool frames;
`demos/render_gifs.py` produces GIFs and posters. Keep generated recordings
explicitly labeled as demonstrations, and verify actual tool interactions
before replacing the published assets.
