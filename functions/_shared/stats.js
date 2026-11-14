// Shared helpers for the private /stats Functions (see docs/usage-stats.md).
// This module exports no onRequest handlers, so Pages does not route it.

export const MIN_SECRET_LENGTH = 16;
export const MAX_INGEST_BYTES = 64 * 1024;
export const MAX_ROWS = 2000;
export const MAX_DAYS = 90;

const LEVELS = ["easy", "medium", "hard"];
const SHAPE = /^[2-5]p-[0-5]h$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

// The same allow-list as src/ibflip_web/stats.py: metric -> dimension check.
export const COUNTER_METRICS = {
  rooms_created: (d) => d === "solo" || d === "friends",
  games_started: (d) => SHAPE.test(d),
  games_finished: (d) => SHAPE.test(d),
  games_unattended: (d) => SHAPE.test(d),
  games_abandoned: (d) => SHAPE.test(d),
  game_seconds: (d) => SHAPE.test(d),
  bot_seats: (d) => LEVELS.includes(d),
  bot_mix: (d) => d === "none" || (d.length <= 20 && d.split("+").every((x) => LEVELS.includes(x))),
  game_duration: (d) => ["lt5m", "5-10m", "10-20m", "20-40m", "40m+"].includes(d),
  new_players: (d) => d === "",
};
export const PEAK_METRICS = ["peak_rooms", "peak_active_rooms", "peak_players"];

// Headers on every /stats response, including 401s and errors.
export const PRIVATE_HEADERS = {
  "Cache-Control": "private, no-store, max-age=0",
  "X-Robots-Tag": "noindex, nofollow, noarchive",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

export function withHeaders(response, extra = {}) {
  const out = new Response(response.body, response);
  for (const [k, v] of Object.entries({ ...PRIVATE_HEADERS, ...extra })) out.headers.set(k, v);
  return out;
}

export function text(status, body, headers = {}) {
  return new Response(body, { status, headers: { "Content-Type": "text/plain; charset=utf-8", ...PRIVATE_HEADERS, ...headers } });
}

export function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...PRIVATE_HEADERS },
  });
}

const encoder = new TextEncoder();

// Constant-time comparison: hash both sides to equal length, then timingSafeEqual.
export async function secretMatches(given, expected) {
  if (typeof given !== "string" || typeof expected !== "string" || expected.length < MIN_SECRET_LENGTH) return false;
  const [a, b] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(given)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  return crypto.subtle.timingSafeEqual(a, b);
}

export function configured(secret) {
  return typeof secret === "string" && secret.length >= MIN_SECRET_LENGTH;
}

export function utcDay(date = new Date()) {
  return date.toISOString().slice(0, 10);
}

function dayOffset(day, today) {
  return Math.round((Date.parse(`${day}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86400000);
}

const isCount = (n, max) => Number.isSafeInteger(n) && n >= 0 && n <= max;

// Validate an ingest batch. Returns {counters, peaks} or throws Error(message).
export function validateBatch(body, today = utcDay()) {
  if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error("body must be an object");
  const keys = Object.keys(body);
  if (body.v !== 1 || keys.some((k) => !["v", "counters", "peaks"].includes(k))) throw new Error("unknown version or field");
  const counters = body.counters ?? [];
  const peaks = body.peaks ?? [];
  if (!Array.isArray(counters) || !Array.isArray(peaks) || counters.length + peaks.length > MAX_ROWS) {
    throw new Error("bad or oversized lists");
  }
  // Only the recent past (a batch may straddle midnight, a game may expire hours later).
  const recent = (day) => typeof day === "string" && DAY.test(day) && dayOffset(day, today) >= -2 && dayOffset(day, today) <= 1;
  for (const row of counters) {
    if (!Array.isArray(row) || row.length !== 4) throw new Error("bad counter row");
    const [day, metric, dim, n] = row;
    const check = Object.hasOwn(COUNTER_METRICS, metric) ? COUNTER_METRICS[metric] : null;
    if (!recent(day) || !check || typeof dim !== "string" || !check(dim)) throw new Error("counter not allowed");
    if (!isCount(n, metric === "game_seconds" ? 1e9 : 1e6)) throw new Error("bad count");
  }
  for (const row of peaks) {
    if (!Array.isArray(row) || row.length !== 3) throw new Error("bad peak row");
    const [day, metric, value] = row;
    if (!recent(day) || !PEAK_METRICS.includes(metric) || !isCount(value, 1e5)) throw new Error("peak not allowed");
  }
  return { counters, peaks };
}

export const MISSING_DB = "Stats storage is not configured (STATS_DB binding).";

// Keep in sync with migrations/0001_stats.sql (the canonical schema). Applied
// lazily when a query fails with "no such table", so a fresh or local database
// works without a separate migration step.
const SCHEMA = [
  "CREATE TABLE IF NOT EXISTS counters (day TEXT NOT NULL, metric TEXT NOT NULL, dim TEXT NOT NULL DEFAULT '', n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, metric, dim)) WITHOUT ROWID",
  "CREATE TABLE IF NOT EXISTS peaks (day TEXT NOT NULL, metric TEXT NOT NULL, value INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, metric)) WITHOUT ROWID",
  "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID",
];

export async function batchWithSchema(db, makeStatements) {
  try {
    return await db.batch(makeStatements());
  } catch (err) {
    if (!/no such table/i.test(String(err?.message ?? err))) throw err;
    await db.batch(SCHEMA.map((sql) => db.prepare(sql)));
    return await db.batch(makeStatements());
  }
}
