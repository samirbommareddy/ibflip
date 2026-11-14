# Private game-activity stats

An anonymous, daily-aggregated record of how IB-Flip is played. The owner
reads it at `https://ibflip.com/stats` after logging in. The game server never
waits on it. With no configuration it is completely off.

## Architecture

```
Render (FastAPI)                         Cloudflare Pages project "ibflip"
src/ibflip_web/stats.py                  functions/stats/*  (Pages Functions)
  in-memory daily counters  ── POST ──▶  /stats/ingest   bearer secret ──▶ D1 "ibflip-stats"
  flush every 60 s + on shutdown         /stats          dashboard HTML ◀──┘
                                         /stats/data     JSON (both behind Basic auth)
```

- **Collect (backend).** `src/ibflip_web/stats.py` holds counters in memory,
  keyed by UTC day, metric and dimension. Rooms and the API call it
  (`rooms.py`: game start/end, room expiry; `main.py`: room create/join,
  shutdown). Every 60 s, and only if something changed, one JSON batch goes to
  the ingest URL from a worker thread with a 5 s timeout. A last flush runs
  when Render stops the instance. Failed batches are dropped and never retried,
  because a retry after a timed-out success would double-count. Every public
  method catches its own exceptions, so tracking can never raise into game
  code. Recording is plain in-memory work under a `threading.Lock`, because bot
  moves (and so game over) run in worker threads.
- **Store.** The Cloudflare D1 free tier holds three tables (see
  `migrations/0001_stats.sql`): `counters(day, metric, dim, n)`,
  `peaks(day, metric, value)` and `meta` (the last ingest time). Ingest is an
  upsert (`n = n + excluded.n`, `value = MAX(...)`) in one batch transaction.
  The functions create the tables on first use if they are missing.
- **Show.** `/stats` serves a self-contained page
  (`functions/_shared/dashboard.html`). It has KPI tiles, daily stacked bars
  with hover tooltips, breakdown tables and a daily detail table for the last
  7, 30 or 90 days. It follows the site's Blue tokens, light and dark, and
  works at phone width. Its only inline script is allowed by a CSP hash.
- **Routing cost.** Wrangler generates `_routes.json` with
  `include: ["/stats", "/stats/*"]`, which was checked with
  `wrangler pages functions build`. Every other request stays a free static
  request and does not count toward the Functions quota.
- **Why not Render?** The Render free plan has no persistent disk, and the
  server restarts often. D1 plus Pages Functions run on the existing
  Cloudflare project with no new service.

### What is tracked

| Metric | Dimension | Meaning |
| --- | --- | --- |
| `rooms_created` | `solo` / `friends` | Room created with bots / without bots |
| `games_started` | `{seats}p-{humans}h` | Game started, e.g. `4p-1h` = 1 human + 3 bots |
| `bot_seats` | `easy` / `medium` / `hard` | Bot seats in started games (Rookie/Regular/Shark) |
| `bot_mix` | `none`, `easy+hard`, ... | Difficulty levels present per started game |
| `games_finished` | shape | Game over with a human still at the table |
| `games_unattended` | shape | Every human had left; bots/autopilot finished it ("left early") |
| `games_abandoned` | shape | Room expired or the server stopped mid-game |
| `game_seconds` | shape | Summed length of finished games (average = seconds / finished) |
| `game_duration` | `lt5m` ... `40m+` | Length histogram of finished games |
| `new_players` | none | First-seen players today (approximate, see below) |
| `peak_rooms`, `peak_active_rooms`, `peak_players` | none | Daily maximum of open rooms, rooms with a connected human, and connected humans (sampled every 60 s and on activity) |

A human whose connection drops at the moment of game over makes that game count
as "left early". Unattended and abandoned games together are the "did not
finish" signal.

## Privacy contract

- **Never collected or sent:** names, IP addresses, user agents, room codes,
  seat tokens, chat, emotes, card or move data. The payload is limited to the
  allow-listed metrics and dimension formats above. It is enforced twice: in
  `stats.py` and again in `functions/_shared/stats.js` (`validateBatch`). The
  ingest function rejects any other field, metric or dimension, days more than
  2 days old, and oversized counts or bodies, and it uses bound SQL parameters
  only. `tests/test_stats.py` plays real games and asserts that the payload
  contains no codes, tokens, names or client address.
- **Unique players:** the backend computes
  `HMAC-SHA256(daily_key, client address)[:16]`. `daily_key` is 32 random
  bytes that exist only in the process's memory and are replaced at each UTC
  midnight. The hashes stay in memory; only the count of newly seen hashes
  (`new_players`) is sent. Nothing stored anywhere can be linked back to an
  address, even by the owner. The trade-off: every server restart (Render
  sleeps after about 15 minutes idle) starts a fresh key, so the same person
  can be counted again later that day. Treat the number as an upper-bound
  estimate. Summed over days, it counts player-days, not distinct people.
- **Retention:** only daily aggregates exist. Nothing is per person or per
  room, so the rows carry no personal data. To clear history:
  `DELETE FROM counters WHERE day < 'YYYY-MM-DD'` in the D1 console.
- **Logs:** a failed flush logs only `stats: dropped a batch (HTTP 401)`, at
  most once every 10 minutes. Secrets are never logged.

## Access control

**Decision: an in-function HTTP Basic auth check is the protection, and it
fails closed.** `functions/stats/_middleware.js` guards every `/stats*` route.
It checks the password against the `STATS_DASHBOARD_PASSWORD` Pages secret
(any user name is accepted). The comparison hashes both sides with SHA-256 and
uses `crypto.subtle.timingSafeEqual`. If the secret is missing or shorter than
16 characters, the route returns 503 and no data. Only `GET` is allowed. Every
response, 401s included, carries `Cache-Control: private, no-store`,
`X-Robots-Tag: noindex`, `Referrer-Policy: no-referrer` and
`X-Frame-Options: DENY`. `/stats/ingest` is the only exception: it requires
`Authorization: Bearer <STATS_INGEST_SECRET>` instead. The dashboard and
ingest secrets are separate. No secret is ever in `static/` or in the page.

**Cloudflare Access was not adopted.** Zero Trust onboarding requires
"selecting a subscription plan and entering your payment details. If you chose
the Zero Trust Free plan, this step is still needed but you will not be
charged."
([Cloudflare One setup](https://developers.cloudflare.com/cloudflare-one/setup/#2-create-a-zero-trust-organization)).
Putting a payment method on file breaks the project's free-hosting rule, so
nothing here relies on Access. If the owner ever has a Zero Trust organization
anyway, an Access application for `ibflip.com/stats*` with an email
one-time-PIN policy can sit on top of this. Keep the Basic auth either way.
Access would also block the backend's ingest unless the application covers only
the dashboard paths or a service token is used, so point ingest at
`ibflip.pages.dev` (below).

If the free Functions quota were ever exhausted, Pages "fail open" serves only
static assets for `/stats*`. The data exists only in D1 and is reachable only
through the function, so nothing leaks.

## Free-tier budget

| Resource (Workers Free) | Limit | Expected use |
| --- | --- | --- |
| Pages Functions / Workers requests | 100,000 / day (shared across the account) | ≤ 1,440 ingests/day (one per minute while the server is awake and something changed) + a few dashboard views |
| Functions CPU | 10 ms / request | Validation + one SHA-256 compare; well under |
| D1 rows written | 100,000 / day | ≈ 5–30 rows per ingest → typically < 5,000/day even when busy |
| D1 rows read | 5 million / day | One dashboard load reads ≈ days × (≤ 60) rows: ≤ 5,400 for 90 days |
| D1 storage | 5 GB total, 10 databases | A few KB per day |

Sources: [Workers/D1 pricing](https://developers.cloudflare.com/workers/platform/pricing/),
[Pages Functions pricing](https://developers.cloudflare.com/pages/functions/pricing/).
Since 2026-09-01, D1 free-tier queries fail once a daily limit is reached;
nothing is billed. The game is unaffected either way, because ingest failures
are silently dropped.

## Configuration

| Where | Name | Value |
| --- | --- | --- |
| Render (backend) | `STATS_INGEST_URL` | `https://ibflip.pages.dev/stats/ingest` (the pages.dev host avoids zone-level bot protection on `ibflip.com`) |
| Render (backend) | `STATS_INGEST_SECRET` | random, ≥ 32 chars |
| Pages secret (Production) | `STATS_INGEST_SECRET` | same value as Render |
| Pages secret (Production) | `STATS_DASHBOARD_PASSWORD` | random, ≥ 16 chars (24+ recommended) |
| Pages binding (Production) | `STATS_DB` | D1 database `ibflip-stats` |

Tracking is off unless **both** backend variables are set. Leave Preview
deployments without secrets and bindings: their `/stats*` routes then return
503 or 401.

## Local development

```bash
cp .env.example .env && chmod 600 .env   # if you do not have one yet
# In .env set (random values; never commit them):
#   STATS_INGEST_URL='http://127.0.0.1:8788/stats/ingest'
#   STATS_INGEST_SECRET='<random 32+ chars>'
#   STATS_DASHBOARD_PASSWORD='<random 16+ chars>'
./scripts/with-env ./scripts/stats-dev          # static site + Functions + local D1 on :8788
./scripts/with-env uv run --locked uvicorn ibflip_web.main:app --host 127.0.0.1 --port 8000
```

`scripts/stats-dev` writes only the two stats secrets to the Git-ignored
`.dev.vars` and runs the pinned `wrangler@4.154.0 pages dev static` with a
local D1 (`--d1 STATS_DB=ibflip-stats-local`, stored under `.wrangler/`). Open
`http://127.0.0.1:8788/stats` and log in with any user name and the dashboard
password. Batches arrive within about 60 s, or right away when you stop the
backend with Ctrl-C. Leaving the stats variables empty disables tracking; the
tests need no credentials.

Tests: `uv run --locked python -m pytest -q` (`tests/test_stats.py`) and
`node --test tests/test_stats_functions.mjs` (the ingest allow-list).

## Owner setup checklist

Do these when releasing. Nothing below has been done in the live account.

1. **Create the database** (Cloudflare dashboard → Storage & Databases → D1 →
   Create): name `ibflip-stats`, Workers Free plan. The current API token
   (Pages Edit, DNS Edit, Zone Read) cannot create D1. Use the dashboard, or a
   token with *Account → D1 → Edit*, with
   `npx wrangler@4.154.0 d1 create ibflip-stats`.
2. **Apply the schema:** D1 → `ibflip-stats` → Console, then paste
   `migrations/0001_stats.sql` and run it. This step is optional, because the
   functions create the tables on first use, but it is good to see them.
3. **Bind it to Pages:** Workers & Pages → `ibflip` → Settings → Bindings →
   Add → D1 database, variable name `STATS_DB`, database `ibflip-stats`, for
   **Production** only.
4. **Generate two secrets locally** without echoing them into shared logs, for
   example `openssl rand -base64 32` (ingest) and `openssl rand -base64 24`
   (dashboard password). Keep them in a password manager. If you like, also
   put them in the local `.env`.
5. **Pages secrets (Production):** Workers & Pages → `ibflip` → Settings →
   Variables and Secrets → add `STATS_INGEST_SECRET` and
   `STATS_DASHBOARD_PASSWORD` as type *Secret*. The CLI alternative is
   `npx wrangler@4.154.0 pages secret put STATS_DASHBOARD_PASSWORD --project-name ibflip`
   (it prompts for the value, and the token needs Pages Edit).
6. **Deploy the frontend** by merging to `main`. `.github/workflows/pages.yml`
   now also triggers on `functions/**` and runs from the repository root, so
   `functions/` is compiled and uploaded. Bindings and secrets take effect on
   the next deployment, so deploy after steps 3–5. Check:
   `curl -I https://ibflip.com/stats` → `401`, and
   `curl -I https://ibflip.com/` → `200`.
7. **Render environment** (Dashboard → `ibflip` service → Environment): add
   `STATS_INGEST_URL=https://ibflip.pages.dev/stats/ingest` and
   `STATS_INGEST_SECRET=<same as step 5>`. Saving redeploys the service, which
   drops the in-memory rooms, so do it at a quiet moment.
8. **Verify the pipeline:** play a game on ibflip.com. Within about a minute,
   `https://ibflip.com/stats` should show today's numbers, and the header line
   "last data from the game server" should change. If it stays at "never",
   check the Render logs for `stats: dropped a batch (HTTP …)`: 401 means the
   secrets do not match, 503 means a binding or secret is missing, and 403
   means a bot or WAF rule is in front of the ingest host.
9. **Optional:** Access. Not recommended, because it requires a payment method
   on file (see above).
