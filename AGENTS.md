# AGENTS.md

## Purpose

This project provides a local stock-price alert web app using FastAPI, SQLite, yfinance, and a single-page HTML UI.

## Project Scope

- Backend API and monitoring loop: `main.py`
- Stock search and price lookup: `stock_api.py`
- SQLite schema and queries: `database.py`
- Web UI: `static/index.html`
- Service deployment: `systemd/stock-alert-web.service`
- Do not manually edit `alerts.db` unless the user explicitly asks for data repair or migration.
- Ignore `.git/`, `__pycache__/`, and generated Python bytecode during normal searches and reviews.

## Search Autocomplete Rules

- Keep search behavior consistent for stock names, complete tickers, and Korean numeric ticker codes with omitted leading zeroes.
- Numeric Korean ticker queries of up to six digits must be normalized to six digits before lookup. For example, `5930` should match `005930`.
- Re-run the current query when a non-empty search input receives focus so an existing value restores its preview.
- When results are shown, select the first result by default.
- Support `ArrowUp` and `ArrowDown` to move the preview selection.
- Support `Tab` and `Enter` to complete the selected result, and `Escape` to close the preview.
- Keep mouse hover, mouse click, and keyboard selection synchronized through the same selected-index state.
- Show visible keyboard guidance for arrow-key selection and Tab completion.
- Preserve combobox/listbox ARIA state when changing autocomplete behavior.

## UI Color Rules

- Reuse colors already defined in the Tailwind configuration or existing project classes.
- Do not reference an undefined Tailwind shade such as `brand-950` when the local `brand` palette does not define it.
- Selected autocomplete results must be visibly distinct in both light and dark themes using a matching background and border/ring.
- Keep selected-state colors aligned with the existing blue `brand` accent used by inputs, buttons, and badges.
- Do not rely on hover styling alone to communicate keyboard selection.

## Verification

After changing stock search or autocomplete behavior:

1. Check the inline JavaScript syntax.
2. Verify a shortened numeric query such as `5930` returns `005930.KS`.
3. Verify the first preview result is selected by default.
4. Verify arrow keys change the selected result.
5. Verify `Tab` completes the selected result and fills name, ticker, and exchange fields.
6. Verify refocusing a non-empty search input restores its preview.
7. Inspect the selected preview visually in both light and dark themes.

Do not consider the UI change complete from class-name inspection alone; confirm that the selected background and border are actually rendered.
