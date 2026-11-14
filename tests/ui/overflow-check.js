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
  // The part of an element actually on screen: clipped by every ancestor
  // that hides or scrolls its overflow.
  const shownRect = (el) => {
    let r = el.getBoundingClientRect();
    let { left, top, right, bottom } = r;
    for (let e = el.parentElement; e && e !== document.body; e = e.parentElement) {
      const o = getComputedStyle(e);
      if (o.overflowX === "visible" && o.overflowY === "visible") continue;
      const c = e.getBoundingClientRect();
      left = Math.max(left, c.left); top = Math.max(top, c.top);
      right = Math.min(right, c.right); bottom = Math.min(bottom, c.bottom);
    }
    return { left, top, right, bottom };
  };
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
        const cs = getComputedStyle(el);
        // Regions that clip or scroll sideways must not hide content.
        if (cs.overflowX !== "visible" && !el.classList.contains("card") && cs.textOverflow !== "ellipsis" && el.scrollWidth > el.clientWidth + 1) {
          add("hidden-overflow", el, `${el.scrollWidth} > ${el.clientWidth}`);
        }
        if (!ownText(el)) continue;
        if (el.scrollWidth > el.clientWidth + 1 && cs.textOverflow !== "ellipsis" && cs.display !== "inline" && cs.overflowX !== "visible") {
          add("clipped", el, `${el.scrollWidth} > ${el.clientWidth}`);
        }
        const fs = parseFloat(cs.fontSize);
        if (fs < (phone ? 13 : 14) - 0.01) add("small-text", el, `${fs.toFixed(1)}px "${el.textContent.trim().slice(0, 18)}"`);
      }
    }
    if (screen?.id === "game") {
      const zones = [
        ...document.querySelectorAll("#game .hud, #game .seat, #game .pile-col, #game .turn-order, #game .narration.show, #game .prompt, #game #mySlots .slot, #game #hand, #game #actionBar .btn, #game #meBadge"),
      ].filter(visible);
      for (let i = 0; i < zones.length; i++) for (let j = i + 1; j < zones.length; j++) {
        if (zones[i].contains(zones[j]) || zones[j].contains(zones[i])) continue;
        if (overlap(shownRect(zones[i]), shownRect(zones[j]))) add("collision", `${describe(zones[i])} x ${describe(zones[j])}`);
      }
    }
    // Not an offender: how far the table area has to scroll to show it all.
    const wrap = document.querySelector("#game.active .table-wrap");
    const scroll = wrap ? Math.max(0, wrap.scrollHeight - wrap.clientHeight) : 0;
    return { count: out.length, offenders: out, scroll };
  };
})();
