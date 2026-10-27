"""Client-side panel resizing without rebuilding chat or preview contents."""

from nicegui import ui

from core.i18n import t


def resize_handle(*, label: str, minimum: int, maximum: int, direction: int = 1):
    ui.add_css("""
        .panel-resize {width:5px;flex:0 0 5px;cursor:col-resize;touch-action:none;
            background:transparent;position:relative;z-index:3;align-self:stretch;}
        .panel-resize:hover,.panel-resize:focus-visible {background:#b8c8d7;outline:none;}
        body.panel-resizing {cursor:col-resize!important;user-select:none!important;}
        body.panel-resizing iframe {pointer-events:none!important;}
        #desktop-sidebar .calabash-sidebar {width:100%;}
    """, shared=True)
    ui.add_head_html("""<script>
    if (!window.calabashPanelResize) {
      window.calabashPanelResize = true;
      const bounds = (h, panel) => {
        const parent = panel.id === 'desktop-sidebar' ? panel.parentElement.parentElement : panel.parentElement;
        const available = Math.max(0, parent.clientWidth - 365);
        const max = Math.min(Number(h.dataset.maximum), available);
        return [Math.min(Number(h.dataset.minimum), max), max];
      };
      const resize = (h, width) => {
        const panel = document.getElementById(h.dataset.panel);
        if (!panel) return;
        const [min,max] = bounds(h,panel);
        const value = Math.max(min,Math.min(max,width));
        panel.style.width = `${value}px`;
        panel.style.flex = '0 0 auto';
        h.setAttribute('aria-valuenow',Math.round(value));
        h.setAttribute('aria-valuemin',Math.round(min));
        h.setAttribute('aria-valuemax',Math.round(max));
      };
      document.addEventListener('pointerdown', e => {
        const h = e.target.closest('.panel-resize');
        if (!h || e.button !== 0) return;
        const panel = document.getElementById(h.dataset.panel);
        if (!panel) return;
        e.preventDefault(); h.setPointerCapture(e.pointerId);
        const start = e.clientX, width = panel.getBoundingClientRect().width;
        document.body.classList.add('panel-resizing');
        const move = ev => resize(h,width+(ev.clientX-start)*Number(h.dataset.direction));
        const end = () => {
          document.body.classList.remove('panel-resizing');
          h.removeEventListener('pointermove',move);
          h.removeEventListener('pointerup',end);
          h.removeEventListener('pointercancel',end);
          h.removeEventListener('lostpointercapture',end);
        };
        h.addEventListener('pointermove',move);
        h.addEventListener('pointerup',end);
        h.addEventListener('pointercancel',end);
        h.addEventListener('lostpointercapture',end);
      });
      document.addEventListener('keydown',e => {
        const h = e.target.closest('.panel-resize');
        if (!h || !['ArrowLeft','ArrowRight'].includes(e.key)) return;
        const panel = document.getElementById(h.dataset.panel);
        if (!panel) return;
        e.preventDefault();
        resize(h,panel.getBoundingClientRect().width+(e.key==='ArrowRight'?16:-16)*Number(h.dataset.direction));
      });
      window.addEventListener('resize',()=>document.querySelectorAll('.panel-resize').forEach(h=>{
        const panel=document.getElementById(h.dataset.panel);
        if(panel && panel.getBoundingClientRect().width) resize(h,panel.getBoundingClientRect().width);
      }));
    }
    </script>""", shared=True)
    return ui.element("div").classes("panel-resize").props(
        f'role=separator tabindex=0 aria-orientation=vertical aria-label="{t(label)}" '
        f'aria-valuemin={minimum} aria-valuemax={maximum} '
        f'data-minimum={minimum} data-maximum={maximum} data-direction={direction}'
    )
