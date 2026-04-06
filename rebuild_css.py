import sys

with open(
    r"C:\Users\syste\Desktop\Melikhan\Web\Web Projeler\web_ar-main\templates\view.html",
    "r",
    encoding="utf-8",
) as f:
    content = f.read()

style_open = content.find("<style>")
style_close = content.find("</style>")

css_lines = []
css_lines.append("        :root {")
css_lines.append("            --color-black: #000000;")
css_lines.append("            --color-gray-900: #111111;")
css_lines.append("            --color-gray-800: #1a1a1a;")
css_lines.append("            --color-gray-700: #333333;")
css_lines.append("            --color-gray-600: #555555;")
css_lines.append("            --color-gray-500: #777777;")
css_lines.append("            --color-gray-400: #999999;")
css_lines.append("            --color-gray-300: #cccccc;")
css_lines.append("            --color-gray-200: #eeeeee;")
css_lines.append("            --color-gray-100: #f5f5f5;")
css_lines.append("            --color-white: #ffffff;")
css_lines.append(
    "            --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;"
)
css_lines.append("            --spacing-xs: 0.25rem;")
css_lines.append("            --spacing-sm: 0.5rem;")
css_lines.append("            --spacing-md: 0.75rem;")
css_lines.append("            --spacing-lg: 1rem;")
css_lines.append("            --spacing-xl: 1.25rem;")
css_lines.append("            --spacing-2xl: 1.5rem;")
css_lines.append("            --spacing-3xl: 2rem;")
css_lines.append("        }")
css_lines.append("")
css_lines.append(
    "        html { font-size: 16px; -webkit-font-smoothing: antialiased; }"
)
css_lines.append(
    "        body { font-family: var(--font-sans); font-size: 1rem; line-height: 1.6; color: var(--color-gray-900); background: var(--color-white); margin: 0; }"
)
css_lines.append(
    "        .dark body { color: var(--color-gray-200); background: var(--color-gray-900); }"
)
css_lines.append(
    "        h1, h2, h3, h4, h5, h6 { font-weight: 600; line-height: 1.3; letter-spacing: -0.02em; }"
)
css_lines.append("        *, *::before, *::after { box-sizing: border-box; }")
css_lines.append("")
css_lines.append(
    "        .action-button { background: var(--color-gray-100); border: 1px solid var(--color-gray-200); padding: var(--spacing-md); cursor: pointer; display: flex; align-items: center; justify-content: center; z-index: 2000; width: 48px; height: 48px; flex: 0 0 48px; margin: 0 2px; transition: background 0.15s ease, border-color 0.15s ease; position: relative; }"
)
css_lines.append("        .action-button:hover { background: var(--color-gray-200); }")
css_lines.append(
    "        .dark .action-button { background: var(--color-gray-800); border-color: var(--color-gray-700); color: var(--color-gray-200); }"
)
css_lines.append(
    "        .dark .action-button:hover { background: var(--color-gray-700); }"
)
css_lines.append("")
css_lines.append(
    "        .top-nav a { font-size: 0.875rem; color: var(--color-gray-700); text-decoration: none; padding: var(--spacing-sm) var(--spacing-md); transition: color 0.15s ease; }"
)
css_lines.append(
    "        .top-nav a:hover { color: var(--color-black); text-decoration: underline; text-underline-offset: 2px; }"
)
css_lines.append("        .dark .top-nav a { color: var(--color-gray-400); }")
css_lines.append("        .dark .top-nav a:hover { color: var(--color-white); }")
css_lines.append("")
css_lines.append(
    "        .panel-container { background: var(--color-gray-100); border: 1px solid var(--color-gray-200); transition: border-color 0.15s ease; overflow: hidden; flex-shrink: 0; }"
)
css_lines.append(
    "        .dark .panel-container { background: var(--color-gray-800); border-color: var(--color-gray-700); }"
)
css_lines.append(
    "        .panel-content { max-height: 0; overflow: hidden; transition: max-height 0.28s ease, padding 0.28s ease; }"
)
css_lines.append(
    "        .panel-content.open { padding: var(--spacing-md) !important; }"
)
css_lines.append("")
css_lines.append(
    "        #rightSidebar { position: fixed; top: 50%; right: var(--spacing-lg); transform: translateY(-50%); width: 20rem; max-height: calc(100vh - var(--spacing-2xl)); overflow-y: auto; transition: transform 0.3s ease; }"
)
css_lines.append(
    "        #rightSidebar.sidebar-collapsed { transform: translateX(calc(100% + var(--spacing-lg))); }"
)
css_lines.append("")
css_lines.append(
    "        #sidebarToggle { position: absolute; left: -2rem; top: 50%; transform: translateY(-50%); width: 2rem; height: 3.5rem; background: var(--color-gray-100); border: 1px solid var(--color-gray-200); border-right: none; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 30; transition: background 0.2s; }"
)
css_lines.append(
    "        .dark #sidebarToggle { background: var(--color-gray-800); border-color: var(--color-gray-700); }"
)
css_lines.append("        #sidebarToggle:hover { background: var(--color-gray-200); }")
css_lines.append(
    "        .dark #sidebarToggle:hover { background: var(--color-gray-700); }"
)
css_lines.append("")
css_lines.append(
    "        #saveChangesWrapper { position: sticky; bottom: 0; flex-shrink: 0; z-index: 5; padding-top: 2px; }"
)
css_lines.append(
    "        .modal-overlay { background-color: rgba(0, 0, 0, 0.7); transition: opacity 0.3s ease; }"
)
css_lines.append(
    "        .modal-container { transform: scale(0.95); opacity: 0; transition: all 0.3s ease; }"
)
css_lines.append("        .modal-container.active { transform: scale(1); opacity: 1; }")
css_lines.append("")
css_lines.append(
    "        #qrModal { display: none; background: var(--color-white); padding: var(--spacing-2xl); text-align: center; border: 1px solid var(--color-gray-200); max-width: 90%; width: 400px; position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); z-index: 1000; }"
)
css_lines.append(
    "        .dark #qrModal { background: var(--color-gray-800); border-color: var(--color-gray-700); }"
)
css_lines.append("        #qrModal.show { display: block; }")
css_lines.append(
    "        #qrcode { background: var(--color-white); padding: var(--spacing-lg); display: inline-block; margin: var(--spacing-lg) 0; }"
)
css_lines.append("")
css_lines.append(
    "        #arModal { display: none; position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: var(--color-white); padding: var(--spacing-2xl); z-index: 1000; border: 1px solid var(--color-gray-200); max-width: 90%; width: 400px; text-align: center; }"
)
css_lines.append(
    "        .dark #arModal { background: var(--color-gray-900); color: var(--color-gray-200); }"
)
css_lines.append("        #arModal.show { display: block; }")
css_lines.append("        model-viewer::part(ar-button) { display: none; }")
css_lines.append("")
css_lines.append(
    "        .viewer-shell { position: relative; height: 100vh; overflow: hidden; }"
)
css_lines.append(
    "        .viewer-stage { position: absolute; inset: 0; z-index: 1; background: var(--color-gray-100); }"
)
css_lines.append("        .dark .viewer-stage { background: var(--color-gray-900); }")
css_lines.append(
    "        model-viewer { background: transparent !important; width: 100%; height: 100%; }"
)
css_lines.append("")
css_lines.append(
    "        .top-header { position: fixed; top: var(--spacing-lg); left: var(--spacing-lg); right: var(--spacing-lg); z-index: 45; display: flex; justify-content: space-between; align-items: flex-start; gap: var(--spacing-lg); pointer-events: none; }"
)
css_lines.append(
    "        .brand-shell, .top-actions { pointer-events: auto; display: flex; align-items: center; background: transparent; }"
)
css_lines.append("        .brand-shell { gap: 0.8rem; padding: 0; min-width: 14rem; }")
css_lines.append(
    "        .brand-mark { font-size: 2.1rem; font-weight: 800; line-height: 1; letter-spacing: -0.04em; color: var(--color-gray-900); text-decoration: none; }"
)
css_lines.append("        .dark .brand-mark { color: var(--color-gray-200); }")
css_lines.append("        .top-actions { gap: 0.45rem; padding: 0; }")
css_lines.append("")
css_lines.append(
    "        .showcase-sidebar { position: fixed !important; top: 3.5rem !important; right: var(--spacing-xl) !important; bottom: auto !important; width: 22rem !important; max-width: 22rem !important; max-height: calc(100vh - 5rem); z-index: 35; }"
)
css_lines.append(
    "        #rightSidebar.showcase-sidebar { gap: 0; padding-right: 0 !important; scrollbar-width: none; }"
)
css_lines.append(
    "        #rightSidebar.showcase-sidebar::-webkit-scrollbar { display: none; }"
)
css_lines.append(
    "        #rightSidebar.showcase-sidebar #sidebarToggle, #rightSidebar.showcase-sidebar .sidebar-section-label { display: none; }"
)
css_lines.append(
    "        #rightSidebar.showcase-sidebar .panel-container { background: var(--color-gray-900); border: 1px solid var(--color-gray-700); }"
)
css_lines.append(
    "        #rightSidebar.showcase-sidebar .panel-header { color: var(--color-gray-200); min-height: 48px; font-weight: 600; }"
)
css_lines.append(
    "        #rightSidebar.showcase-sidebar .panel-header:hover { background: var(--color-gray-800) !important; }"
)
css_lines.append(
    "        #rightSidebar.showcase-sidebar .panel-content { background: transparent; }"
)
css_lines.append(
    "        #rightSidebar.showcase-sidebar .text-gray-700, #rightSidebar.showcase-sidebar .text-gray-600, #rightSidebar.showcase-sidebar label { color: var(--color-gray-300) !important; font-weight: 500; }"
)
css_lines.append(
    "        #rightSidebar.showcase-sidebar .text-gray-500, #rightSidebar.showcase-sidebar .text-gray-400 { color: var(--color-gray-500) !important; }"
)
css_lines.append(
    '        #rightSidebar.showcase-sidebar input[type="text"], #rightSidebar.showcase-sidebar input[type="number"], #rightSidebar.showcase-sidebar select { background: var(--color-gray-800); border: 1px solid var(--color-gray-700); color: var(--color-gray-200); font-weight: 500; }'
)
css_lines.append(
    "        #rightSidebar.showcase-sidebar .btn-secondary { background: var(--color-gray-800); border: 1px solid var(--color-gray-700); color: var(--color-gray-300); font-weight: 600; }"
)
css_lines.append(
    "        #rightSidebar.showcase-sidebar .btn-secondary:hover { background: var(--color-gray-700); border-color: var(--color-gray-600); }"
)
css_lines.append("")
css_lines.append(
    "        .showcase-card { display: flex; flex-direction: column; height: auto; padding: var(--spacing-xl); background: var(--color-gray-900); color: var(--color-gray-200); border: 1px solid var(--color-gray-700); overflow: hidden; transition: transform 0.2s ease; }"
)
css_lines.append("        .showcase-card:hover { transform: translateY(-2px); }")
css_lines.append(
    "        .showcase-card.is-collapsed { opacity: 0; pointer-events: none; transform: translateX(var(--spacing-lg)); }"
)
css_lines.append("")
css_lines.append(
    "        .showcase-collapsed-pill { position: fixed; bottom: 1.75rem; right: 1.65rem; z-index: 36; display: flex; align-items: center; gap: var(--spacing-md); padding: var(--spacing-md) var(--spacing-lg); background: var(--color-gray-900); color: var(--color-gray-200); border: 1px solid var(--color-gray-700); cursor: pointer; font-size: 0.88rem; font-weight: 600; opacity: 0; pointer-events: none; transform: translateY(var(--spacing-sm)); transition: all 0.3s ease; max-width: 14rem; }"
)
css_lines.append(
    "        .showcase-collapsed-pill.is-visible { opacity: 1; pointer-events: auto; transform: translateY(0); }"
)
css_lines.append(
    "        .showcase-collapsed-pill:hover { background: var(--color-gray-800); }"
)
css_lines.append(
    "        .showcase-collapsed-pill .pill-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }"
)
css_lines.append(
    "        .showcase-collapsed-pill .pill-icon { width: 1.25rem; height: 1.25rem; flex-shrink: 0; color: var(--color-gray-400); }"
)
css_lines.append(
    "        #rightSidebar.sidebar-card-collapsed { pointer-events: none; }"
)
css_lines.append(
    "        #rightSidebar.sidebar-card-collapsed .showcase-card { opacity: 0; pointer-events: none; transform: translateX(var(--spacing-lg)); }"
)
css_lines.append("")
css_lines.append(
    "        .showcase-header { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--spacing-md); padding-bottom: var(--spacing-sm); }"
)
css_lines.append(
    "        .showcase-kicker { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.18em; color: var(--color-gray-400); }"
)
css_lines.append(
    "        .showcase-title { font-size: 1.1rem; font-weight: 800; line-height: 1.2; color: var(--color-gray-100); }"
)
css_lines.append(
    "        .showcase-description { margin-top: var(--spacing-sm); font-size: 0.85rem; line-height: 1.6; color: var(--color-gray-400); }"
)
css_lines.append(
    "        .showcase-publisher { font-size: 0.85rem; color: var(--color-gray-400); text-decoration: underline; text-underline-offset: 2px; margin-top: var(--spacing-sm); display: inline-block; font-weight: 500; }"
)
css_lines.append(
    "        .showcase-close { width: 1.8rem; height: 1.8rem; border: 1px solid var(--color-gray-700); color: var(--color-gray-400); display: inline-flex; align-items: center; justify-content: center; font-size: 0.85rem; flex-shrink: 0; background: var(--color-gray-800); transition: background 0.15s ease; cursor: pointer; }"
)
css_lines.append("        .showcase-close:hover { background: var(--color-gray-700); }")
css_lines.append("")
css_lines.append(
    "        .stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--spacing-md); }"
)
css_lines.append(
    "        .stat-item { display: flex; align-items: center; gap: var(--spacing-sm); padding: var(--spacing-md); background: var(--color-gray-100); }"
)
css_lines.append("        .dark .stat-item { background: var(--color-gray-800); }")
css_lines.append("        .stat-item i { width: 1rem; height: 1rem; }")
css_lines.append("")
css_lines.append(
    "        .showcase-tabs { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--spacing-sm); padding: var(--spacing-md) 0; }"
)
css_lines.append(
    "        .showcase-tab { min-height: 2.25rem; border: 1px solid var(--color-gray-700); background: var(--color-gray-800); color: var(--color-gray-400); font-size: 0.7rem; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; transition: all 0.15s ease; }"
)
css_lines.append(
    "        .showcase-tab:hover { background: var(--color-gray-700); color: var(--color-gray-300); }"
)
css_lines.append(
    "        .showcase-tab.is-active { background: var(--color-gray-200); color: var(--color-gray-900); border-color: var(--color-gray-300); }"
)
css_lines.append("")
css_lines.append("        .showcase-mode { display: none; }")
css_lines.append("        .showcase-mode.is-active { display: block; }")
css_lines.append(
    "        .showcase-section { margin-bottom: var(--spacing-md); background: var(--color-gray-800); border: 1px solid var(--color-gray-700); }"
)
css_lines.append("")
css_lines.append(
    "        .showcase-gallery { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--spacing-sm); }"
)
css_lines.append(
    "        .showcase-gallery-tile { aspect-ratio: 1 / 1; background: var(--color-gray-800); border: 1px solid var(--color-gray-700); display: flex; align-items: center; justify-content: center; overflow: hidden; text-decoration: none; position: relative; transition: transform 0.2s ease; }"
)
css_lines.append(
    "        .showcase-gallery-tile:hover { transform: translateY(-4px); }"
)
css_lines.append(
    "        .gallery-thumb-container { width: 100%; height: 100%; position: relative; overflow: hidden; }"
)
css_lines.append(
    "        .gallery-thumbnail { width: 100%; height: 100%; object-fit: cover; transition: transform 0.2s ease; }"
)
css_lines.append(
    "        .showcase-gallery-tile:hover .gallery-thumbnail { transform: scale(1.05); }"
)
css_lines.append(
    "        .gallery-fallback { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; background: var(--color-gray-800); }"
)
css_lines.append(
    "        .gallery-filename { color: var(--color-gray-300); font-size: 0.65rem; font-weight: 600; text-align: center; padding: var(--spacing-sm); line-height: 1.3; }"
)
css_lines.append("")
css_lines.append(
    "        .showcase-content { min-height: 0; flex: 1 1 auto; overflow-y: auto; padding-right: var(--spacing-xs); margin-top: var(--spacing-xs); }"
)
css_lines.append("")
css_lines.append(
    "        .sidebar-utility { border: 1px solid var(--color-gray-200); background: var(--color-gray-100); }"
)
css_lines.append(
    "        .dark .sidebar-utility { border-color: var(--color-gray-700); background: var(--color-gray-800); }"
)
css_lines.append(
    "        .sidebar-section-label { display: flex; align-items: center; gap: var(--spacing-sm); padding: var(--spacing-xs) var(--spacing-xs) 0; font-size: 0.58rem; font-weight: 800; letter-spacing: 0.18em; text-transform: uppercase; opacity: 0.9; color: var(--color-gray-500); }"
)
css_lines.append(
    '        .sidebar-section-label::after { content: ""; flex: 1; height: 1px; background: var(--color-gray-200); }'
)
css_lines.append(
    "        .dark .sidebar-section-label::after { background: var(--color-gray-700); }"
)
css_lines.append(
    "        .dark .sidebar-section-label { color: var(--color-gray-400); }"
)
css_lines.append("")
css_lines.append(
    "        .panel-header { min-height: 2.8rem; padding-top: var(--spacing-md); padding-bottom: var(--spacing-md); cursor: pointer; transition: background 0.15s ease; }"
)
css_lines.append(
    "        .panel-header:hover { background: var(--color-gray-200) !important; }"
)
css_lines.append(
    "        .dark .panel-header:hover { background: var(--color-gray-700) !important; }"
)
css_lines.append("        .panel-header-icon { transition: transform 0.3s ease; }")
css_lines.append("")
css_lines.append(
    "        .btn-primary { background: var(--color-gray-900); border: 1px solid var(--color-black); color: var(--color-white); transition: background 0.15s ease; cursor: pointer; }"
)
css_lines.append("        .btn-primary:hover { background: var(--color-gray-700); }")
css_lines.append(
    "        .btn-secondary { background: var(--color-gray-100); border: 1px solid var(--color-gray-200); color: var(--color-gray-700); transition: background 0.15s ease, border-color 0.15s ease; cursor: pointer; }"
)
css_lines.append(
    "        .btn-secondary:hover { background: var(--color-gray-200); border-color: var(--color-gray-300); }"
)
css_lines.append(
    "        .dark .btn-secondary { background: var(--color-gray-800); border-color: var(--color-gray-700); color: var(--color-gray-300); }"
)
css_lines.append(
    "        .dark .btn-secondary:hover { background: var(--color-gray-700); }"
)
css_lines.append("")
css_lines.append(
    "        .toolbar-shell { position: fixed; right: calc(20rem + var(--spacing-lg) + var(--spacing-lg)); bottom: var(--spacing-lg); z-index: 31; transition: right 0.3s ease; }"
)
css_lines.append("        .toolbar-shell.sidebar-open { right: var(--spacing-lg); }")
css_lines.append("")
css_lines.append(
    "        .bottom-right-controls { position: static; transform: none; padding: 0; gap: var(--spacing-xs); background: transparent; border: none; display: flex; align-items: center; }"
)
css_lines.append(
    "        .toolbar-shell .bottom-right-controls button { width: 2.6rem; height: 2.6rem; background: transparent; border: 1px solid transparent; padding: 0; display: flex; align-items: center; justify-content: center; color: var(--color-gray-600); transition: color 0.15s ease, background 0.15s ease, border-color 0.15s ease; cursor: pointer; }"
)
css_lines.append(
    "        .toolbar-shell .bottom-right-controls button:hover { background: var(--color-gray-100); color: var(--color-gray-900); border-color: var(--color-gray-200); }"
)
css_lines.append(
    "        .dark .toolbar-shell .bottom-right-controls button { color: var(--color-gray-400); }"
)
css_lines.append(
    "        .dark .toolbar-shell .bottom-right-controls button:hover { background: var(--color-gray-800); color: var(--color-gray-200); border-color: var(--color-gray-700); }"
)
css_lines.append(
    "        .toolbar-shell .bottom-right-controls button i { width: 1.35rem; height: 1.35rem; }"
)
css_lines.append(
    "        .toolbar-shell .bottom-right-controls button.is-liked { color: var(--color-gray-900); }"
)
css_lines.append(
    "        .toolbar-shell .bottom-right-controls button.is-saved { color: var(--color-gray-900); }"
)
css_lines.append("")
css_lines.append(
    "        .canvas-control-shell { position: fixed; left: var(--spacing-xl); bottom: var(--spacing-lg); z-index: 30; }"
)
css_lines.append("        .info-modal-backdrop { background: rgba(0, 0, 0, 0.7); }")
css_lines.append(
    "        .info-modal-card { width: min(30rem, calc(100vw - 2rem)); border: 1px solid var(--color-gray-200); background: var(--color-white); max-height: 80vh; overflow-y: auto; }"
)
css_lines.append(
    "        .dark .info-modal-card { border-color: var(--color-gray-700); background: var(--color-gray-900); }"
)
css_lines.append(
    "        .info-modal-row { display: grid; grid-template-columns: 1.1rem 1fr; gap: var(--spacing-md); align-items: start; padding: var(--spacing-xs) 0; }"
)
css_lines.append(
    "        .info-modal-chip { display: inline-flex; align-items: center; gap: var(--spacing-xs); padding: var(--spacing-xs) var(--spacing-sm); border: 1px solid var(--color-gray-200); background: var(--color-gray-100); font-size: 0.7rem; font-weight: 600; color: var(--color-gray-700); }"
)
css_lines.append(
    "        .dark .info-modal-chip { border-color: var(--color-gray-700); background: var(--color-gray-800); color: var(--color-gray-300); }"
)
css_lines.append(
    "        .version-card { border: 1px solid var(--color-gray-200); background: var(--color-gray-100); }"
)
css_lines.append(
    "        .dark .version-card { border-color: var(--color-gray-700); background: var(--color-gray-800); }"
)
css_lines.append(
    "        .history-item, .annotation-item { border: 1px solid var(--color-gray-200); background: var(--color-gray-100); }"
)
css_lines.append(
    "        .dark .history-item, .dark .annotation-item { border-color: var(--color-gray-700); background: var(--color-gray-800); }"
)
css_lines.append(
    "        .slicer-side-btn { min-width: 3rem; min-height: 1.55rem; cursor: pointer; }"
)
css_lines.append("")
css_lines.append(
    "        #mobileEditFab { position: fixed; left: 50%; bottom: 5.4rem; transform: translateX(-50%); z-index: 36; display: none; align-items: center; gap: var(--spacing-sm); padding: var(--spacing-md) var(--spacing-lg); border: 1px solid var(--color-gray-200); background: var(--color-gray-100); font-size: 0.82rem; font-weight: 700; color: var(--color-gray-900); cursor: pointer; }"
)
css_lines.append(
    "        .dark #mobileEditFab { border-color: var(--color-gray-700); background: var(--color-gray-800); color: var(--color-gray-200); }"
)
css_lines.append("")
css_lines.append(
    "        #mobileSidebarBackdrop { position: fixed; inset: 0; z-index: 34; background: rgba(0, 0, 0, 0.28); opacity: 0; pointer-events: none; transition: opacity 0.24s ease; }"
)
css_lines.append(
    "        body.mobile-sidebar-open #mobileSidebarBackdrop { opacity: 1; pointer-events: auto; }"
)
css_lines.append("        body.mobile-sidebar-open { overflow: hidden; }")
css_lines.append("")
css_lines.append(
    "        .save-summary { color: var(--color-gray-500); font-size: 0.72rem; line-height: 1.4; }"
)
css_lines.append("        .dark .save-summary { color: var(--color-gray-400); }")
css_lines.append("        .compact-note { display: none !important; }")
css_lines.append("")
css_lines.append("        .model-header { margin-bottom: var(--spacing-md); }")
css_lines.append(
    "        .model-title-row { display: flex; align-items: center; gap: var(--spacing-sm); }"
)
css_lines.append(
    "        .model-title { font-size: 1.1rem; font-weight: 800; line-height: 1.2; color: var(--color-gray-100); margin: 0; }"
)
css_lines.append(
    '        .model-title[contenteditable="true"] { border-bottom: 1px solid var(--color-gray-500); outline: none; }'
)
css_lines.append(
    "        .model-description { margin-top: var(--spacing-sm); font-size: 0.85rem; line-height: 1.6; color: var(--color-gray-400); }"
)
css_lines.append(
    '        .model-description[contenteditable="true"] { border-bottom: 1px solid var(--color-gray-500); outline: none; }'
)
css_lines.append(
    "        .model-edit-actions { display: flex; gap: var(--spacing-sm); margin-top: var(--spacing-md); }"
)
css_lines.append("")
css_lines.append(
    "        .icon-btn { background: transparent; border: 1px solid var(--color-gray-700); color: var(--color-gray-400); padding: var(--spacing-xs) var(--spacing-sm); cursor: pointer; display: flex; align-items: center; justify-content: center; transition: background 0.15s ease, color 0.15s ease; }"
)
css_lines.append(
    "        .icon-btn:hover { background: var(--color-gray-700); color: var(--color-gray-200); }"
)
css_lines.append("        .icon-btn i { width: 1rem; height: 1rem; }")
css_lines.append("")
css_lines.append("        [data-lucide] { width: 1rem; height: 1rem; }")
css_lines.append("")
css_lines.append("        @media (max-width: 1024px) {")
css_lines.append("            #rightSidebar { width: 280px; max-width: 280px; }")
css_lines.append("            .toolbar-shell { right: var(--spacing-lg); }")
css_lines.append("        }")
css_lines.append("")
css_lines.append("        @media (max-width: 640px) {")
css_lines.append(
    "            .top-header { top: var(--spacing-md); left: var(--spacing-md); right: var(--spacing-md); gap: var(--spacing-sm); }"
)
css_lines.append(
    "            .brand-shell { min-width: 0; flex: 1 1 auto; padding: 0; }"
)
css_lines.append("            .brand-mark { font-size: 1.7rem; }")
css_lines.append(
    "            .top-actions .nav-button span, .showcase-nav, .color-picker-container, .portfolio-tagline { display: none !important; }"
)
css_lines.append("            #mobileEditFab { display: inline-flex; }")
css_lines.append(
    "            .showcase-sidebar { top: var(--spacing-md) !important; right: var(--spacing-md) !important; bottom: var(--spacing-md) !important; width: min(24rem, calc(100vw - var(--spacing-2xl))) !important; max-width: min(24rem, calc(100vw - var(--spacing-2xl))) !important; transform: translateX(calc(100% + var(--spacing-lg))); }"
)
css_lines.append(
    "            body.mobile-sidebar-open .showcase-sidebar { transform: translateX(0); }"
)
css_lines.append(
    "            .toolbar-shell { right: var(--spacing-md); bottom: 5.6rem; }"
)
css_lines.append("            #sidebarToggle { display: inline-flex; }")
css_lines.append(
    "            .showcase-collapsed-pill { bottom: 5.6rem; right: var(--spacing-md); }"
)
css_lines.append("        }")
css_lines.append("")
css_lines.append(
    "        .slicer-slider { -webkit-appearance: none; appearance: none; height: 0.375rem; }"
)
css_lines.append(
    "        .slicer-slider::-webkit-slider-thumb { -webkit-appearance: none; width: 1rem; height: 1rem; background: var(--color-gray-900); cursor: pointer; border: 2px solid var(--color-gray-200); }"
)
css_lines.append(
    "        .dark .slicer-slider::-webkit-slider-thumb { background: var(--color-gray-200); border-color: var(--color-gray-700); }"
)
css_lines.append(
    "        .slicer-slider::-moz-range-thumb { width: 1rem; height: 1rem; background: var(--color-gray-900); cursor: pointer; border: 2px solid var(--color-gray-200); }"
)
css_lines.append(
    "        .dark .slicer-slider::-moz-range-thumb { background: var(--color-gray-200); border-color: var(--color-gray-700); }"
)
css_lines.append("")
css_lines.append(
    "        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.7; } }"
)
css_lines.append("        .animate-pulse { animation: pulse 2s ease infinite; }")

new_css = "\n".join(css_lines)

new_content = (
    content[:style_open]
    + "<style>\n"
    + new_css
    + "\n    </style>"
    + content[style_close + len("</style>") :]
)

with open(
    r"C:\Users\syste\Desktop\Melikhan\Web\Web Projeler\web_ar-main\templates\view.html",
    "w",
    encoding="utf-8",
) as f:
    f.write(new_content)

print(f"CSS replaced. New file size: {len(new_content)} chars")
