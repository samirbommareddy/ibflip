/* Layout checker for the playable client (dev-only; see docs/frontend.md).
   window.__overflowCheck() inspects the visible screen and returns
   { count, offenders: [{ kind, what, detail }] } where kind is one of:
   - "viewport": a visible element extends outside the viewport
   - "clipped": text overflows its own box without an ellipsis
   - "collision": two board zones (HUD, seats, piles, prompt, your area) overlap
   - "small-text": visible text below 14px (desktop) or 13px (width <= 760px)
   - "page-scroll": the document itself scrolls horizontally */
(() => {
  const describe = (el) => {
    const id = el.id ? `#${el.id}` : "";
    const cls = typeof el.className === "string" && el.className.trim() ? `.${el.className.trim().split(/\s+/).slice(0, 2).join(".")}` : "";
    const seat = el.closest?.(".seat")?.dataset.seat;
    return `${el.tagName.toLowerCase()}${id}${cls}${seat !== undefined ? ` (seat ${seat})` : ""}`;
  };
  function visible(el) {
    for (let e = el; e && e !== document.documentElement; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.display === "none" || cs.visibility === "hidden" || Number(cs.opacity) < 0.05) return false;
    }
    const r = el.getBoundingClientRect();
    return r.width > 0.5 && r.height > 0.5;
  }
  // Content inside a scrolling region is allowed to extend past the viewport.
  const inScroller = (el) => {
    for (let e = el.parentElement; e && e !== document.body; e = e.parentElement) {
      const o = getComputedStyle(e);
      if (/(auto|scroll)/.test(o.overflowX + o.overflowY)) return true;
    }
    return false;
  };
  const ownText = (el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
  const overlap = (a, b) => Math.min(a.right, b.right) - Math.max(a.left, b.left) > 2 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 2;

  window.__overflowCheck = () => {
    const out = [];
    const add = (kind, el, detail = "") => out.push({ kind, what: typeof el === "string" ? el : describe(el), detail });
    const W = innerWidth, H = innerHeight, phone = W <= 760;
    const doc = document.scrollingElement;
    if (doc.scrollWidth > W + 1) add("page-scroll", "document", `${doc.scrollWidth} > ${W}`);
    const screen = document.querySelector(".screen.active");
    const roots = [screen, ...document.querySelectorAll(".overlay:not(.hidden)"), document.querySelector(".seen-pop:not([hidden])")].filter(Boolean);
    for (const root of roots) {
      for (const el of [root, ...root.querySelectorAll("*")]) {
        if (el.closest("#fx, .fly, svg, .sr-only, canvas, option")) continue;
        if (!visible(el)) continue;
        const r = el.getBoundingClientRect();
        if (!inScroller(el) && (r.left < -1 || r.top < -1 || r.right > W + 1 || r.bottom > H + 1)) {
          add("viewport", el, `${Math.round(r.left)},${Math.round(r.top)} ${Math.round(r.width)}x${Math.round(r.height)}`);
        }
        if (!ownText(el)) continue;
        const cs = getComputedStyle(el);
        if (el.scrollWidth > el.clientWidth + 1 && cs.textOverflow !== "ellipsis" && cs.display !== "inline" && cs.overflowX !== "visible") {
          add("clipped", el, `${el.scrollWidth} > ${el.clientWidth}`);
        }
        const fs = parseFloat(cs.fontSize);
        if (fs < (phone ? 13 : 14) - 0.01) add("small-text", el, `${fs.toFixed(1)}px "${el.textContent.trim().slice(0, 18)}"`);
      }
    }
    if (screen?.id === "game") {
      const zones = [
        ...document.querySelectorAll("#game .hud, #game .seat, #game .pile-col, #game .turn-order, #game .prompt, #game #mySlots, #game #hand, #game #actionBar, #game #meBadge"),
      ].filter(visible);
      for (let i = 0; i < zones.length; i++) for (let j = i + 1; j < zones.length; j++) {
        if (zones[i].contains(zones[j]) || zones[j].contains(zones[i])) continue;
        if (overlap(zones[i].getBoundingClientRect(), zones[j].getBoundingClientRect())) add("collision", `${describe(zones[i])} x ${describe(zones[j])}`);
      }
    }
    return { count: out.length, offenders: out };
  };
})();
