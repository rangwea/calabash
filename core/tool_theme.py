"""Fluent-inspired tool defaults, scoped away from the application chrome.

Keep the scope at zero specificity; namespaced tool CSS can override defaults
without changing the application chrome.
"""

TOOL_THEME_CSS = """
:where(.calabash-tool-shell) { background: #f5f7fb; }
:where(.calabash-tool) {
    --tool-accent: #0f6cbd;
    --tool-accent-soft: #eff6fc;
    --tool-on-accent: #ffffff;
    --tool-canvas: #f5f7fb;
    --tool-surface: #ffffff;
    --tool-surface-muted: #f5f7fb;
    --tool-text: #242424;
    --tool-muted: #616b7a;
    --tool-border: #e5e7eb;
    --tool-success: #107c41;
    --tool-warning: #9a5700;
    --tool-danger: #c4314b;
    --tool-radius: 8px;
    --tool-control-height: 36px;
    --tool-row-height: 40px;
    --q-primary: var(--tool-accent);
    --q-secondary: #7160c5;
    --q-positive: var(--tool-success);
    --q-warning: var(--tool-warning);
    --q-negative: var(--tool-danger);
    --app-primary: var(--tool-accent);
    --app-primary-light: var(--tool-accent-soft);
    --app-primary-soft: var(--tool-accent-soft);
    --app-text: var(--tool-text);
    color: var(--tool-text);
    font-size: 14px;
    line-height: 1.5;
    min-width: 0;
    gap: 16px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}
:where(.calabash-tool) .tool-theme-teal {
    --tool-accent: #0f766e; --tool-accent-soft: #ecf8f5;
    --q-primary: var(--tool-accent); --app-primary: var(--tool-accent);
    --app-primary-light: var(--tool-accent-soft);
}
:where(.calabash-tool) .tool-theme-violet {
    --tool-accent: #6950a1; --tool-accent-soft: #f4f0fb;
    --q-primary: var(--tool-accent); --app-primary: var(--tool-accent);
    --app-primary-light: var(--tool-accent-soft);
}
:where(.calabash-tool) .q-card, .calabash-tool .tool-panel {
    background: var(--tool-surface); color: var(--tool-text);
    border: 1px solid var(--tool-border); border-radius: var(--tool-radius);
    box-shadow: none;
}
:where(.calabash-tool) .tool-panel { padding: 20px; }
:where(.calabash-tool) .tool-panel-muted { background: var(--tool-surface-muted); }
:where(.calabash-tool) .tool-title { font-size: 24px; line-height: 1.3; font-weight: 650; letter-spacing: -0.02em; }
:where(.calabash-tool) .tool-subtitle { font-size: 16px; font-weight: 600; }
:where(.calabash-tool) .tool-muted { color: var(--tool-muted); }
:where(.calabash-tool) .tool-text-accent { color: var(--tool-accent); }
:where(.calabash-tool) .tool-accent-soft { background: var(--tool-accent-soft); color: var(--tool-accent); }
:where(.calabash-tool) .tool-selected {
    color: var(--tool-accent); background: var(--tool-accent-soft);
    box-shadow: inset 3px 0 var(--tool-accent); font-weight: 600;
}
:where(.calabash-tool) .q-btn:not(.q-btn--round) {
    min-height: var(--tool-control-height); border-radius: 6px;
    text-transform: none; letter-spacing: 0; font-size: 14px;
    font-weight: 500; box-shadow: none;
}
:where(.calabash-tool) .q-btn.bg-primary { color: var(--tool-on-accent); }
:where(.calabash-tool) .q-field__control { border-radius: 6px; }
/* External labels + dense controls provide the 36px office baseline.
   Floating Quasar labels retain their native height, avoiding clipped text. */
:where(.calabash-tool) .q-field--dense:not(.q-field--labeled):not(.q-textarea) .q-field__control,
:where(.calabash-tool) .q-field--dense:not(.q-field--labeled):not(.q-textarea) .q-field__marginal {
    min-height: var(--tool-control-height); height: var(--tool-control-height);
}
:where(.calabash-tool) .q-field--dense:not(.q-field--labeled):not(.q-textarea) .q-field__native {
    min-height: var(--tool-control-height); padding-top: 6px; padding-bottom: 6px;
}
:where(.calabash-tool) .q-table th {
    font-size: 12px; font-weight: 600; color: var(--tool-muted); background: var(--tool-surface-muted);
}
:where(.calabash-tool) .q-table tbody td { height: var(--tool-row-height); font-size: 14px; border-color: var(--tool-border); }
:where(.calabash-tool) .q-table tbody tr:hover { background: var(--tool-accent-soft); }
:where(.calabash-tool) .q-table__container { background: var(--tool-surface); color: var(--tool-text); box-shadow: none; border-radius: var(--tool-radius); }
:where(.calabash-tool) .q-icon { flex-shrink: 0; }
:where(.calabash-tool) :focus-visible { outline: 2px solid var(--tool-accent); outline-offset: 3px; }
@media (prefers-reduced-motion: reduce) {
    :where(.calabash-tool) * { animation-duration: 0s; transition-duration: 0s; }
}
"""
