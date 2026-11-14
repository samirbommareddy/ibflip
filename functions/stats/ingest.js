// POST /stats/ingest — the game server's aggregated counters (bearer secret).
import {
  MAX_INGEST_BYTES,
  MISSING_DB,
  batchWithSchema,
  configured,
  secretMatches,
  text,
  validateBatch,
} from "../_shared/stats.js";

export async function onRequestPost({ request, env }) {
  if (!configured(env.STATS_INGEST_SECRET)) return text(503, "Ingest is not configured.");
  const auth = request.headers.get("Authorization") || "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7) : null;
  if (!(await secretMatches(token, env.STATS_INGEST_SECRET))) return text(401, "Unauthorized.");
  if (!env.STATS_DB) return text(503, MISSING_DB);

  const declared = Number(request.headers.get("Content-Length") || 0);
  if (declared > MAX_INGEST_BYTES) return text(413, "Too large.");
  const raw = await request.text();
  if (raw.length > MAX_INGEST_BYTES) return text(413, "Too large.");

  let batch;
  try {
    batch = validateBatch(JSON.parse(raw));
  } catch (err) {
    return text(400, `Rejected: ${err instanceof SyntaxError ? "invalid JSON" : err.message}`);
  }

  const db = env.STATS_DB;
  const statements = () => {
    const addCounter = db.prepare(
      "INSERT INTO counters (day, metric, dim, n) VALUES (?1, ?2, ?3, ?4) " +
        "ON CONFLICT (day, metric, dim) DO UPDATE SET n = n + excluded.n",
    );
    const raisePeak = db.prepare(
      "INSERT INTO peaks (day, metric, value) VALUES (?1, ?2, ?3) " +
        "ON CONFLICT (day, metric) DO UPDATE SET value = MAX(value, excluded.value)",
    );
    return [
      ...batch.counters.filter((r) => r[3] > 0).map((r) => addCounter.bind(...r)),
      ...batch.peaks.map((r) => raisePeak.bind(...r)),
      db
        .prepare(
          "INSERT INTO meta (key, value) VALUES ('last_ingest', ?1) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        )
        .bind(new Date().toISOString()),
    ];
  };
  try {
    await batchWithSchema(db, statements); // one transaction
  } catch (err) {
    console.error("stats ingest failed", err?.message);
    return text(503, "Storage unavailable.");
  }
  return new Response(null, { status: 204 });
}

export function onRequest() {
  return text(405, "Method not allowed.", { Allow: "POST" });
}
