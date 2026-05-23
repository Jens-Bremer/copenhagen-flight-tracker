# frontend/

| File | Type | Description |
|------|------|-------------|
| `app.js` | source | Vanilla JS IIFE (1289 lines). Manages state, renders all panels. Edit here for JS changes. |
| `styles.css` | source | All CSS with design tokens, airline colours, responsive layout. Edit here for style changes. |
| `index.html.template` | source | HTML skeleton with `${PLACEHOLDER}` strings filled by the generator at build time. Edit here for structural changes. |
| `vendor/chart.min.js` | vendored | Chart.js 4.4.3, committed in the repo. Inlined into the HTML at build time. |
| `index.html` | **generated** | The output — **never edit by hand**. Regenerated nightly at 23:46. |

### Workflow

1. Edit `app.js`, `styles.css`, or `index.html.template`.
2. Run `python scripts/generate_html.py` to rebuild `index.html`.
3. Open `frontend/index.html` in a browser.

See `docs/FRONTEND.md` for the full data contract and extension recipes.
