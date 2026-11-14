# Frontend and design review

Blue is the active visual direction. The previous studies and thumbnails are
archived outside the checkout; do not reintroduce them into the review gallery.

## Playable client

`static/index.html`, `static/styles.css`, and `static/app.js` are the existing
no-build game client. The visual replacement preserves the engine, websocket
protocol, action IDs, and gameplay controls. Theme state is a browser preference.
The local-only Design review link leads to the MSI review server on port 8080.

## Motion studio

The single review entry is `designs/index.html`, which opens `designs/lab/`.

| File | Responsibility |
| --- | --- |
| `lab/index.html` and `lab/lab.css` | Review interface and responsive layout |
| `lab/lab.js` | Scenario navigation, previews, explicit decisions, notes, overview, and export |
| `lab/review-store.mjs` | Browser storage, local API synchronization, and conflict handling |
| `lab/animations.mjs` | Motion catalog, stage markup, and animation execution |
| `lab/frame.html`, `lab/frame.mjs`, and `lab/effects.css` | Isolated preview document |
| `blue/` and `shared/` | Blue layout reference and shared card/table primitives |

Each preview runs inside a disposable iframe. Replaying, switching options, or
changing moments replaces that iframe, which disposes of its animations and
timers. Previewing an option never approves it. The 20 moments are arranged in
three groups, accessible through the overview rather than displayed together.

Motion review is a decision tool. Choosing a variant records a preference;
it does not patch the playable game's animation code automatically.

## Feedback contract

Run `.venv/bin/python scripts/design_review.py`. It binds to loopback and serves
only `designs/`. `GET /api/review` returns the current document (or null) and an
ETag. `PUT /api/review` requires that ETag in `If-Match`. A stale session receives
409 instead of replacing newer notes. Local drafts remain available for export;
loading the latest MSI copy explicitly replaces the browser's unsynced draft.

The private, Git-ignored `.local/design-review.json` contains version 1, an ISO
update time, current moment, theme, overall feedback, and decisions keyed by
moment ID. Each decision has an option, note, and one of these statuses:

- `pending`: no explicit decision yet. Previewing or writing a note is not approval.
- `approved`: the owner chose this option.
- `changes`: the owner wants another pass; read the note before implementing.
- `rejected`: the owner prefers no animation for that moment.

Read this file before implementing a feedback round. Do not commit feedback or
use test decisions as owner approval. Browser verification should use a review
server with a temporary feedback path, so smoke tests do not populate the
owner's actual review. Local storage and JSON download remain fallbacks when
the MSI server is unavailable; the interface reports where saving succeeded.

## Layout and overflow checks

The table keeps every zone in normal flow: opponents sit in one wrapping row
(in turn order after you), then the turn-order indicator, the piles and the
line saying what just happened. Text on the board is at least 14px on
desktop and 13px on phones. When space runs out, opponents wrap and then
collapse to one line each, and the table area scrolls on its own; the page
never scrolls horizontally.

`scripts/ui-overflow-matrix.sh [url] [--verbose]` checks this. It needs a
local server and `agent-browser`, injects the dev-only files under
`tests/ui/` (they are never served to players), and renders synthetic table
states (2-player, 5-player, stress: 16+ seen cards, 18-card hands, stacked
face-up slots, long names; and 4-player setup) at desktop, phone, 125-200%
browser zoom and 20/24px text sizes. `tests/ui/overflow-check.js` reports
elements outside the viewport, clipped text without an ellipsis, overlapping
board zones and text below the minimum size. Every row should report 0.

`tests/test_client_rules_table.py` keeps the "What can go on what" table in
`static/app.js` identical to `src/ibflip/rules.py`.
