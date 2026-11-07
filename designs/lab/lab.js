import { DEMOS } from "./animations.mjs";
import { openReview } from "./review-store.mjs";

const GROUPS = [
  {
    label: "The everyday",
    ids: [
      "select",
      "play",
      "opp",
      "draw",
      "reflow",
      "pickup",
      "reveal",
      "pace",
    ],
  },
  {
    label: "A change of plan",
    ids: ["turn", "attack", "nine", "flip", "bigpickup", "illegal", "blind"],
  },
  {
    label: "The big moments",
    ids: ["finish", "win", "unlucky", "eights", "emote"],
  },
];
const COPY = {
  select: [
    "Selecting a card",
    "A small signal that this is the card you’re about to play.",
  ],
  play: [
    "Playing your card",
    "Follow your card from your hand to the middle of the table.",
  ],
  opp: ["An opponent plays", "See who played, and where their card lands."],
  draw: ["Drawing a card", "A new card joins your hand after you play."],
  reflow: [
    "Your hand settles",
    "The remaining cards close the space a played card leaves behind.",
  ],
  pickup: [
    "Picking up the pile",
    "The pile comes back to you when you can’t play.",
  ],
  reveal: [
    "Turning the top card",
    "The deck reveals a card. The reveal should be easy to follow.",
  ],
  pace: [
    "Room to breathe",
    "Watch three bot moves. Find a pace you can comfortably follow.",
  ],
  turn: [
    "Following the turn",
    "Watch play move around the table, then reverse direction.",
  ],
  attack: [
    "A four lands",
    "A four changes what the next player can play. How much emphasis does it need?",
  ],
  nine: [
    "A nine finds a card",
    "A random card is drawn from the discard. Make the surprise feel right.",
  ],
  flip: ["Four of a kind", "Four matching ranks flip the live pile away."],
  bigpickup: [
    "A very big pickup",
    "Twelve cards are coming your way. A little drama, or keep it simple?",
  ],
  illegal: [
    "That card won’t play",
    "A gentle response when someone tries a move the rules don’t allow.",
  ],
  blind: [
    "The face-down gamble",
    "Pick a hidden card and discover what you’ve played.",
  ],
  finish: [
    "Someone goes out",
    "An opponent plays their last card and takes their place.",
  ],
  win: [
    "You finish first",
    "Your last card lands legally. Choose how to celebrate.",
  ],
  unlucky: [
    "An unlucky finish",
    "The last card gives another turn, so the finish doesn’t count.",
  ],
  eights: [
    "The four-eights surprise",
    "A rare ending with four eights. This can have its own personality.",
  ],
  emote: [
    "A little table talk",
    "Three playful reactions. Preview each and say which ones you want to keep.",
  ],
};
const START = {
  select: "grow",
  play: "thump",
  opp: "arcFlip",
  draw: "flyFlip",
  reflow: "spring",
  pickup: "stream",
  reveal: "smooth",
  pace: "steady",
  turn: "dashes",
  attack: "slam",
  nine: "plaque",
  flip: "square",
  bigpickup: "avalanche",
  illegal: "bounce",
  blind: "peek",
  finish: "fromPile",
  win: "squares",
  unlucky: "strike",
  eights: "blackout",
  emote: "throw",
};
const catalog = GROUPS.flatMap((g) =>
  g.ids.map((id) => ({ ...DEMOS.find((d) => d.id === id), group: g.label })),
);
const ids = catalog.map((d) => d.id);
document.querySelectorAll("[data-play-game]").forEach((link) => {
  link.href = `http://${location.hostname}:8000/`;
});
const $ = (selector) => document.querySelector(selector);
const escape = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const saveLabels = {
  saving: "Saving…",
  saved: "Saved on MSI + in this browser",
  msi: "Saved on MSI · browser storage unavailable",
  browser: "Saved in this browser · MSI unavailable",
  conflict:
    "Another review changed on MSI · download yours before loading latest",
  unsaved: "Couldn’t save · download your review",
};
let store;
let current;
let previewOption;
let previewFrame;
let toastTimer;
let ready = false;
document.querySelectorAll("button,textarea").forEach((el) => {
  el.disabled = true;
});

function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.hidden = true;
  }, 3000);
}
function decision() {
  return (
    store.value.decisions[current.id] || {
      option: null,
      status: "pending",
      note: "",
    }
  );
}
function optionName(id, option) {
  return DEMOS.find((d) => d.id === id)?.options[option]?.[0] || "No option";
}
function statusName(status) {
  return (
    {
      approved: "Chosen",
      changes: "Needs work",
      rejected: "No animation",
      pending: "Not reviewed",
    }[status] || "Not reviewed"
  );
}
function updateProgress() {
  const done = ids.filter((id) =>
    ["approved", "changes", "rejected"].includes(
      store.value.decisions[id]?.status,
    ),
  ).length;
  $("#progress-count").textContent = `${done} / ${ids.length}`;
  $("#progress-fill").style.width = `${(done / ids.length) * 100}%`;
  $("#overview-progress").textContent =
    `${done} of ${ids.length} moments reviewed`;
  const d = decision();
  const chosen =
    d.option && current.options[d.option]
      ? optionName(current.id, d.option)
      : null;
  $("#choice-summary").textContent =
    d.status === "pending"
      ? "No decision yet. Try the options, then choose."
      : d.status === "rejected"
        ? "You prefer no animation for this moment."
        : `${statusName(d.status)}: ${chosen || "your feedback"}`;
  $("#choice-summary").dataset.status = d.status;
  $("#approve").classList.toggle(
    "is-chosen",
    d.status === "approved" && d.option === previewOption,
  );
  $("#needs-work").setAttribute(
    "aria-pressed",
    d.status === "changes" && d.option === previewOption,
  );
  $("#reject").setAttribute("aria-pressed", d.status === "rejected");
  document.querySelectorAll(".option-button").forEach((b) => {
    b.classList.toggle(
      "chosen",
      d.status === "approved" && d.option === b.dataset.option,
    );
    b.querySelector(".option-marker").textContent =
      d.status === "approved" && d.option === b.dataset.option
        ? "✓ Chosen"
        : "";
  });
}
function showPreview(play = false) {
  const option = current.options[previewOption];
  $("#preview-label").textContent = option[0];
  $("#playback-status").textContent = play
    ? "Playing preview…"
    : "Press Replay to watch this option.";
  const frame = document.createElement("iframe");
  frame.title = `${COPY[current.id][0]} — ${option[0]} preview`;
  frame.src = `frame.html?${new URLSearchParams({ moment: current.id, option: previewOption, theme: store.value.theme, play: play ? "1" : "0" })}`;
  // Replacing the entire document cancels all its animations, timers, and flyers.
  $("#preview-host").replaceChildren(frame);
  previewFrame = frame;
}
function choosePreview(key) {
  previewOption = key;
  document
    .querySelectorAll(".option-button")
    .forEach((b) => b.setAttribute("aria-pressed", b.dataset.option === key));
  updateProgress();
  showPreview(true);
}
function renderCurrent({ focus = false } = {}) {
  current = catalog.find((d) => d.id === store.value.currentId) || catalog[0];
  const d = decision();
  previewOption = current.options[d.option]
    ? d.option
    : START[current.id] || Object.keys(current.options)[0];
  const index = ids.indexOf(current.id);
  $("#moment-category").textContent = current.group.toUpperCase();
  $("#moment-title").textContent = COPY[current.id][0];
  $("#moment-description").textContent = COPY[current.id][1];
  $("#step-counter").innerHTML =
    `${String(index + 1).padStart(2, "0")} <span>/ ${ids.length}</span>`;
  $("#options").innerHTML = Object.entries(current.options)
    .map(
      ([key, [name, note]]) =>
        `<button class="option-button" data-option="${key}" aria-pressed="${key === previewOption}"><span class="option-title">${escape(name)}<span class="option-marker"></span></span><span class="option-note">${escape(note)}</span><span class="option-play" aria-hidden="true">▷</span></button>`,
    )
    .join("");
  $("#moment-note").value = d.note;
  $("#previous").disabled = index === 0;
  $("#next").innerHTML =
    index === ids.length - 1
      ? 'Review your choices <span aria-hidden="true">↗</span>'
      : 'Next moment <span aria-hidden="true">→</span>';
  updateProgress();
  showPreview(false);
  if (focus) {
    $("#moment-title").tabIndex = -1;
    $("#moment-title").focus({ preventScroll: true });
    $(".review").scrollIntoView({
      block: "start",
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
    });
  }
}
function navigate(id) {
  store.update((value) => {
    value.currentId = id;
  });
  renderCurrent({ focus: true });
}
function setDecision(status) {
  store.update((value) => {
    value.decisions[current.id] = {
      ...decision(),
      option: previewOption,
      status,
    };
  });
  updateProgress();
  toast(
    status === "approved"
      ? "Option chosen. You can change it anytime."
      : status === "changes"
        ? "Marked for another pass. Add a note below."
        : "Marked: keep this moment still.",
  );
}
function renderOverview() {
  $("#overview-list").innerHTML = GROUPS.map(
    (group) =>
      `<section class="overview-group"><h3>${escape(group.label)}</h3>${group.ids
        .map((id) => {
          const d = store.value.decisions[id];
          return `<button class="overview-item" data-jump="${id}"><span class="overview-number">${String(ids.indexOf(id) + 1).padStart(2, "0")}</span><span class="overview-item-title">${escape(COPY[id][0])}${d?.note ? '<span class="has-note">With feedback</span>' : ""}</span><span class="status-pill ${d?.status || "pending"}">${statusName(d?.status)}</span><span aria-hidden="true">→</span></button>`;
        })
        .join("")}</section>`,
  ).join("");
  updateProgress();
}
function openOverview() {
  renderOverview();
  $("#overview-dialog").showModal();
}
function summaryText() {
  const value = store.value;
  return [
    "IB-FLIP · MOTION REVIEW",
    ...catalog.map((item) => {
      const d = value.decisions[item.id];
      return `\n${COPY[item.id][0]} — ${statusName(d?.status)}${d?.option ? ": " + optionName(item.id, d.option) : ""}${d?.note ? "\n" + d.note : ""}`;
    }),
    "\nOverall feedback\n" + (value.generalNote || "No overall feedback yet."),
  ].join("\n");
}
function downloadReview() {
  const value = { ...store.value };
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = `ibflip-motion-review-${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast("Review downloaded, including all feedback.");
}

window.addEventListener("message", (event) => {
  if (
    !ready ||
    event.origin !== location.origin ||
    event.source !== previewFrame?.contentWindow ||
    event.data?.source !== "ibflip-motion-preview"
  )
    return;
  $("#playback-status").textContent =
    {
      ready: "Press Replay to watch this option.",
      playing: "Playing preview…",
      finished: "Preview finished. Replay, or try another feel.",
      error: "Preview couldn’t finish. Try Replay.",
    }[event.data.state] || "";
});
$("#options").addEventListener("click", (event) => {
  const button = event.target.closest("[data-option]");
  if (button) choosePreview(button.dataset.option);
});
$("#replay").addEventListener("click", () => showPreview(true));
$("#approve").addEventListener("click", () => setDecision("approved"));
$("#needs-work").addEventListener("click", () => setDecision("changes"));
$("#reject").addEventListener("click", () => setDecision("rejected"));
$("#moment-note").addEventListener("input", (event) => {
  store.update((value) => {
    value.decisions[current.id] = { ...decision(), note: event.target.value };
  });
});
$("#general-note").addEventListener("input", (event) =>
  store.update((value) => {
    value.generalNote = event.target.value;
  }),
);
$("#previous").addEventListener("click", () =>
  navigate(ids[Math.max(0, ids.indexOf(current.id) - 1)]),
);
$("#next").addEventListener("click", () =>
  ids.indexOf(current.id) === ids.length - 1
    ? openOverview()
    : navigate(ids[ids.indexOf(current.id) + 1]),
);
$("#open-overview").addEventListener("click", openOverview);
$("#close-overview").addEventListener("click", () =>
  $("#overview-dialog").close(),
);
$("#continue-review").addEventListener("click", () => {
  $("#overview-dialog").close();
  const pending = ids.find(
    (id) =>
      !store.value.decisions[id] ||
      store.value.decisions[id].status === "pending",
  );
  if (pending) navigate(pending);
});
$("#overview-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-jump]");
  if (button) {
    $("#overview-dialog").close();
    navigate(button.dataset.jump);
  }
});
$("#overview-dialog").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) $("#overview-dialog").close();
});
$("#theme-toggle").addEventListener("click", () => {
  store.update((value) => {
    value.theme = value.theme === "dark" ? "light" : "dark";
  });
  applyTheme();
  showPreview(false);
});
function applyTheme() {
  document.documentElement.dataset.theme = store.value.theme;
  $("#theme-toggle").setAttribute(
    "aria-label",
    `Switch to ${store.value.theme === "dark" ? "light" : "dark"} mode`,
  );
}
$("#export-review").addEventListener("click", downloadReview);
$("#copy-review").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(summaryText());
    toast("Review summary copied.");
  } catch (_) {
    toast("Clipboard unavailable. Download your review instead.");
  }
});
$("#load-latest").addEventListener("click", async () => {
  if (
    !confirm(
      "Replace this browser’s unsynced review with the latest MSI copy? Download your review first if you want to keep both.",
    )
  )
    return;
  if (await store.acceptServer()) {
    applyTheme();
    $("#general-note").value = store.value.generalNote;
    renderCurrent();
    toast("Loaded the latest MSI review.");
  } else toast("MSI is unavailable. Your browser review is still here.");
});

try {
  store = await openReview(ids, (kind) => {
    $("#save-status").textContent = saveLabels[kind];
    $("#save-status").dataset.state = kind;
    $("#load-latest").hidden = kind !== "conflict";
  });
  applyTheme();
  $("#general-note").value = store.value.generalNote;
  $("#reduced-motion").textContent = matchMedia(
    "(prefers-reduced-motion: reduce)",
  ).matches
    ? "Reduced motion is on"
    : "";
  ready = true;
  document.querySelectorAll("button,textarea").forEach((el) => {
    el.disabled = false;
  });
  renderCurrent();
} catch (_) {
  $("#save-status").textContent = "Review couldn’t open. Please reload.";
}
