# XLIFF Editor (baseline)

Standalone CAT-like XLIFF editor designed around one continuous, virtualized document. The DOM is a view only: `Document XML → SQLite document model → React editor state → TanStack Virtual rows`. A 20,000-segment document is held in the model, while roughly the viewport plus 12 rows per side are mounted.

## Run

Requires Python 3.12+ and Node 20+.

```powershell
cd xliff-editor
py -3.12 -m venv .venv
.venv\Scripts\pip install -r backend\requirements.txt
.venv\Scripts\uvicorn app.main:app --app-dir backend --port 8001 --reload
cd frontend
npm install
npm run dev
```

Open the Vite URL (usually `http://127.0.0.1:5173`). Upload an `.xlf`/`.xliff` file. The frontend proxy forwards `/api` to FastAPI.

## Design notes

- SQLite tables: `documents`, `files`, `units`, `segments`, `notes`; segment indexes cover document/file/unit/index/state. Import uses batched inserts.
- The original XML is retained. Segment paths identify target nodes during export, so source nodes, IDs, unknown elements, attributes and extensions outside changed target content round-trip. Inline elements in source/target are represented as XML fragments and displayed as non-executable CAT tags.
- Active target only becomes a `textarea` when clicked. Undo/redo stores target-change commands, not document copies. Search/filter operate on model arrays, then pass `visibleSegmentIds` semantics to the virtualizer.
- This is an independent frontend module; its API client is the integration seam for an iframe, Web Component wrapper, or another host app later.

## Tests and performance fixture

```powershell
cd xliff-editor
$env:PYTHONPATH='backend'; .venv\Scripts\python -m unittest discover -s backend\tests
.venv\Scripts\python tools\generate_demo_xliff.py
$env:PYTHONPATH='backend'; .venv\Scripts\python backend\tests\performance_import.py
cd frontend; npm run build
```

Performance budget: parse/import 20k segments without per-row DB queries; the UI mounts only virtual rows, measures variable heights, and supports `scrollToIndex` for direct segment jumps. Browser smoothness should be profiled in Chrome DevTools on the deployment hardware.
