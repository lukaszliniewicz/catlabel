# Frontend architecture

The React application lives in `frontend/src`. Zustand owns editor state and actions, while Konva renders interactive canvas items. HTML page content is rendered as a separate sanitized layer and composited with Konva for preview, clean AI captures, local batch rendering, and headless API rendering.

## Document model

A project canvas has one physical width and height and one or more pages:

- `items` contains visual elements. Every element belongs to `pageIndex` (legacy elements without it are page 0).
- `pageLayouts` contains `{ pageIndex, htmlContent, activeTemplate }` for pages with HTML or a managed template.
- `currentPage` is editor UI state; it does not create inherited content.
- The canonical page list is the sorted union of item pages, layout pages, and the current page. A page reads only its exact items and exact layout.

Project hydration is atomic. It validates collection shapes, migrates legacy single-page HTML/templates, clamps batch/copy limits, rebuilds managed template markup at the loaded dimensions, clears selection, and can reset undo history when opening another project.

The checked-in TypeScript document contract is generated from the backend schema.
External saved revisions produce a reload notice without replacing a dirty canvas
or resetting its undo history. Managed images load through the authenticated API
client and release temporary blob URLs after decoding.

## Safety boundaries

- API calls use the shared client in `utils/apiClient.ts`, which checks HTTP status, applies request timeouts, preserves structured backend errors, and can validate decoded payloads.
- User/project HTML is sanitized immediately before every DOM insertion. The application CSP provides a second browser-enforced boundary.
- Batch records, matrix/sequence generation, print copies, total jobs, and total decoded render pixels have explicit limits.
- Local and headless rendering propagate failures and use timeouts; print preparation always leaves its busy state on success or failure.
- Printer and default-DPI changes preserve physical millimetre dimensions by scaling canvas geometry and elements together.

## Performance and UI

Store consumers use selectors instead of subscribing to the complete store. Canvas snap guides remain local to the editor and canvas nodes are memoized. The AI assistant, icon catalog, formatters, infrequent modals, and barcode/QR engines load on demand.

Dialogs trap focus, restore prior focus, support Escape where dismissal is valid, and expose dialog semantics. Project-tree rows and action menus are keyboard operable. The side panels can collapse, and the properties panel becomes an overlay on narrower screens.

## Quality checks

Run these commands from `frontend/`:

```sh
npm run lint
npm test
npm run build
```

`npm run check` runs all three. Tests cover document/page isolation, history reset, AI setter contracts, hydration validation, batch/CSV limits, API errors and timeouts, and HTML sanitization.

The editor registers browser site tools when `document.modelContext` is available, falling back to older `navigator.modelContext` implementations.
Schemas come from the backend MCP registry, and calls return its original content
and structured results. Page teardown removes only registrations owned by this
editor. Successful design changes refresh project summaries; saved revisions
still require an explicit reload before replacing the current canvas. The
connection drawer is loaded on demand.
