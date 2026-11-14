// GET /stats — the private dashboard page (auth in _middleware.js).
// The page (markup, styles and its one inline script) lives in ../_shared/dashboard.html;
// the CSP allows exactly that script by hash. Nothing in it is a secret.
import PAGE from "../_shared/dashboard.html";

let csp = null;

async function policy() {
  if (csp) return csp;
  const script = /<script>([\s\S]*?)<\/script>/.exec(PAGE)[1];
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(script));
  const hash = btoa(String.fromCharCode(...new Uint8Array(digest)));
  csp = [
    "default-src 'none'",
    `script-src 'sha256-${hash}'`,
    "style-src 'unsafe-inline'",
    "connect-src 'self'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'none'",
  ].join("; ");
  return csp;
}

export async function onRequestGet() {
  return new Response(PAGE, {
    headers: { "Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": await policy() },
  });
}
