# arvision — Design System

The design language used by the viewer (`templates/view.html`), extracted as a
reusable reference. Shared implementation lives in `static/css/arvision.css`.

**Character:** minimalist, monochrome (no accent color), sharp corners
(border-radius ≈ 0), system fonts, light/dark themable, compact spacing, fast
subtle transitions.

## Color tokens (`:root`)
Pure grayscale — there is **no** accent/brand color.

| Token | Value | Use |
|-------|-------|-----|
| `--color-black` | `#000000` | borders on primary buttons |
| `--color-gray-900` | `#111111` | primary text (light), primary button bg, dark page bg |
| `--color-gray-800` | `#1a1a1a` | dark panel/input bg |
| `--color-gray-700` | `#333333` | dark borders |
| `--color-gray-600` | `#555555` | muted |
| `--color-gray-500` | `#777777` | secondary text / labels |
| `--color-gray-400` | `#999999` | tertiary text / descriptions |
| `--color-gray-300` | `#cccccc` | light borders |
| `--color-gray-200` | `#eeeeee` | light text (on dark), light hover bg |
| `--color-gray-100` | `#f5f5f5` | light panel bg |
| `--color-white` | `#ffffff` | page bg (light) |

Error signalling (functional only): `#dc2626` (light) / `#ef4444` (dark).

## Spacing scale
`--spacing-xs .25rem` · `sm .5rem` · `md .75rem` · `lg 1rem` · `xl 1.25rem` · `2xl 1.5rem` · `3xl 2rem`

## Typography
- Font: system stack — `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif`. **No web fonts.**
- Headings: weight 600, `line-height 1.3`, `letter-spacing -0.02em`.
- Brand (`.brand-mark`): `2.1rem` / weight `800` / `letter-spacing -0.04em`.
- Kicker / labels: small (`0.6–0.72rem`), `text-transform: uppercase`, wide `letter-spacing 0.12–0.18em`, gray-500.
- Tagline: `2rem` / weight `300`.

## Theming
- `.dark` class on `<html>` (`document.documentElement`), persisted in `localStorage.theme` (`'light'|'dark'`).
- Apply the class **before paint** (inline `<head>` script) to avoid a flash.
- Light: white bg, gray-900 text. Dark: gray-900 bg, gray-200 text.

## Components (see `arvision.css`)
- **Header:** `.top-header` (fixed top, space-between), `.brand-mark` ("arvision"), nav links `.showcase-nav-link` (gray-500 → gray-900 on hover, underline), icon button `.av-icon-btn`.
- **Card / panel:** 1px solid border + grayscale bg, **no radius**. `.av-card`.
- **Buttons:** `.btn-primary` (gray-900 bg / white text → gray-700 hover; dark: gray-200/gray-900), `.btn-secondary` (gray-100 bg).
- **Inputs:** `.av-input` / `.av-select` / number / color — gray-100 (light) / gray-800 (dark) bg, 1px border, focus = gray-500 border.
- **Toggle switch:** `.av-switch` — track gray-300/700 → gray-900/200 when checked; square-ish knob.
- **Range slider:** thin track (2px) + small grayscale thumb.
- **Tagline:** `.portfolio-tagline` bottom-left, blinking cursor (`@keyframes blink`).
- **Icons:** Lucide, pinned `lucide@1.17.0`, default `1rem`.

## Rules of thumb
- No border-radius (sharp). No drop shadows except subtle modal/sidebar.
- Transitions `0.12–0.2s`.
- Monochrome only; reserve red strictly for error states.
- Compact padding; uppercase wide-tracked labels for section headers.
