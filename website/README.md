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

The published demos are illustrations, not screen recordings. The tool panes
are drawn by `demos/compose_preview.py`, and `demos/story.html` composes the
chat shell around them. `demos/render-story.cjs` writes the frames and
`demos/compose_gif.py` encodes `<demo>-<language>.gif` plus the poster webp.

```bash
node demos/render-story.cjs ./out      # needs Playwright and Chrome
```

Recording the real desktop app again is still the goal. If you do, use a
disposable HOME and synthetic tool bundles, never the normal user HOME or real
model credits, and keep the result labeled as a demonstration. Replace the
published assets only after checking the actual tool interactions.

`demos/prepare.py` still prepares the synthetic input files, and
`demos/record-story.cjs` composes illustrated chat flows from captured tool
frames once real captures exist again. `demos/check-site.cjs` verifies the
published page.
