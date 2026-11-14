// GET /stats/data?days=30 — daily aggregates for the dashboard (behind _middleware auth).
import { MAX_DAYS, MISSING_DB, batchWithSchema, json, text, utcDay } from "../_shared/stats.js";

export async function onRequestGet({ request, env }) {
  if (!env.STATS_DB) return text(503, MISSING_DB);
  const asked = Number.parseInt(new URL(request.url).searchParams.get("days") || "30", 10);
  const days = Math.min(MAX_DAYS, Math.max(1, Number.isFinite(asked) ? asked : 30));
  const today = utcDay();
  const from = utcDay(new Date(Date.parse(`${today}T00:00:00Z`) - (days - 1) * 86400000));
  try {
    const [counters, peaks, meta] = await batchWithSchema(env.STATS_DB, () => [
      env.STATS_DB.prepare("SELECT day, metric, dim, n FROM counters WHERE day >= ?1 ORDER BY day").bind(from),
      env.STATS_DB.prepare("SELECT day, metric, value FROM peaks WHERE day >= ?1 ORDER BY day").bind(from),
      env.STATS_DB.prepare("SELECT value FROM meta WHERE key = 'last_ingest'"),
    ]);
    return json({
      from,
      to: today,
      days,
      last_ingest: meta.results[0]?.value ?? null,
      counters: counters.results.map((r) => [r.day, r.metric, r.dim, r.n]),
      peaks: peaks.results.map((r) => [r.day, r.metric, r.value]),
    });
  } catch (err) {
    console.error("stats query failed", err?.message);
    return text(503, "Storage unavailable (has the schema been applied?).");
  }
}
