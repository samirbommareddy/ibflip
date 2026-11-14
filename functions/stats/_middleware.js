// Every /stats route is private by default: HTTP Basic auth against the
// STATS_DASHBOARD_PASSWORD Pages secret. Fails closed when it is not set.
// /stats/ingest is the one exception; it checks its own bearer secret.
import { configured, secretMatches, text, withHeaders } from "../_shared/stats.js";

const REALM = 'Basic realm="IB-Flip stats", charset="UTF-8"';

function basicPassword(request) {
  const header = request.headers.get("Authorization") || "";
  const match = /^Basic\s+([A-Za-z0-9+/=]+)$/i.exec(header);
  if (!match) return null;
  try {
    const decoded = new TextDecoder().decode(Uint8Array.from(atob(match[1]), (c) => c.charCodeAt(0)));
    const colon = decoded.indexOf(":");
    return colon < 0 ? null : decoded.slice(colon + 1); // any user name; the password is what counts
  } catch {
    return null;
  }
}

export async function onRequest({ request, env, next }) {
  const { pathname } = new URL(request.url);
  if (pathname === "/stats/ingest") return withHeaders(await next());

  if (!configured(env.STATS_DASHBOARD_PASSWORD)) {
    return text(503, "The stats dashboard is not configured.");
  }
  if (!(await secretMatches(basicPassword(request), env.STATS_DASHBOARD_PASSWORD))) {
    return text(401, "Authentication required.", { "WWW-Authenticate": REALM });
  }
  if (request.method !== "GET") {
    return text(405, "Method not allowed.", { Allow: "GET" });
  }
  return withHeaders(await next());
}
