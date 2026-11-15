#!/usr/bin/env bash
# Run the layout checker across viewport sizes, zoom levels, text sizes and
# board states. Needs a local server (see docs/local-development.md) and
# agent-browser. Usage: scripts/ui-overflow-matrix.sh [url] [--verbose]
set -euo pipefail
URL="${1:-http://127.0.0.1:8000/}"
VERBOSE="${2:-}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
AB=(npx --yes agent-browser@0.43.0)
"${AB[@]}" open "$URL" --args "--no-sandbox" >/dev/null
# Bypass the HTTP cache so the run always checks the files on disk.
"${AB[@]}" eval 'Promise.all(["./", "./styles.css", "./app.js"].map((u) => fetch(u, { cache: "reload" }))).then(() => 1)' >/dev/null
"${AB[@]}" open "$URL" >/dev/null
"${AB[@]}" eval "$(cat "$HERE/tests/ui/board-fixtures.js" "$HERE/tests/ui/overflow-check.js")" >/dev/null
# label width height root-font-px. Browser zoom Z on a WxH screen is a
# viewport of (W/Z)x(H/Z) CSS px; text-size settings raise the root font.
CONFIGS=(
  "1440x900 1440 900 16" "2000x1300 2000 1300 16" "1280x720 1280 720 16"
  "390x844 390 844 16" "360x640 360 640 16"
  "1440@125% 1152 720 16" "1440@150% 960 600 16" "1440@175% 823 514 16" "1440@200% 720 450 16"
  "390@125% 312 675 16" "390@150% 260 563 16"
  "1440+font20 1440 900 20" "1440+font24 1440 900 24" "390+font20 390 844 20" "390+font24 390 844 24"
  "640x360 640 360 16" "683x320 683 320 16" "1366x640 1366 640 16" "820x1180 820 1180 16"
)
total=0
for cfg in "${CONFIGS[@]}"; do
  read -r label w h fs <<<"$cfg"
  "${AB[@]}" set viewport "$w" "$h" >/dev/null
  res=$("${AB[@]}" eval "(async () => { document.documentElement.style.fontSize='${fs}px'; const rows = []; for (const t of ['dark','light']) { document.documentElement.dataset.theme = t; for (const f of __FIXTURES) { await __fixture(f); const r = __overflowCheck(); const kinds = {}; r.offenders.forEach((o) => (kinds[o.kind] = (kinds[o.kind] || 0) + 1)); rows.push([t, f, r.count, kinds, r.offenders.slice(0, 40), r.scroll]); } } document.documentElement.style.fontSize=''; return JSON.stringify(rows); })()")
  python3 - "$label" "$res" "$VERBOSE" <<'PY'
import json, sys
label, raw, verbose = sys.argv[1], sys.argv[2], sys.argv[3]
rows = json.loads(json.loads(raw))
for theme, fixture, count, kinds, offenders, scroll in rows:
    if theme != "dark" and not verbose:
        continue
    extra = f"  (table scrolls {scroll}px)" if scroll else ""
    print(f"{label:12} {theme:5} {fixture:10} {count:4}  " + " ".join(f"{k}={v}" for k, v in sorted(kinds.items())) + extra)
    if verbose:
        for o in offenders[:40]:
            print(f"    {o['kind']:10} {o['what']} {o['detail']}")
PY
done
