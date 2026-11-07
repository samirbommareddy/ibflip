const KEY = "ibflip:motion-review:v1";
const SYNC_KEY = `${KEY}:sync`;
const STATUSES = new Set(["pending", "approved", "rejected", "changes"]);

export function cleanReview(value, ids) {
  if (!value || value.version !== 1 || typeof value !== "object") return null;
  const decisions = {};
  for (const id of ids) {
    const d = value.decisions?.[id];
    if (!d || typeof d !== "object") continue;
    decisions[id] = {
      option: typeof d.option === "string" ? d.option.slice(0, 80) : null,
      status: STATUSES.has(d.status) ? d.status : "pending",
      note: typeof d.note === "string" ? d.note.slice(0, 5000) : "",
    };
  }
  return {
    version: 1,
    updatedAt: Number.isFinite(Date.parse(value.updatedAt))
      ? value.updatedAt
      : new Date(0).toISOString(),
    currentId: ids.includes(value.currentId) ? value.currentId : ids[0],
    decisions,
    generalNote:
      typeof value.generalNote === "string"
        ? value.generalNote.slice(0, 10000)
        : "",
    theme: value.theme === "dark" ? "dark" : "light",
  };
}

export async function openReview(ids, onSaveStatus) {
  const empty = () => ({
    version: 1,
    updatedAt: new Date(0).toISOString(),
    currentId: ids[0],
    decisions: {},
    generalNote: "",
    theme: matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light",
  });
  let local = null;
  let meta = {};
  let localAvailable = true;
  try {
    local = cleanReview(JSON.parse(localStorage.getItem(KEY)), ids);
    meta = JSON.parse(localStorage.getItem(SYNC_KEY)) || {};
  } catch (_) {
    localAvailable = false;
  }
  if (!meta || typeof meta !== "object") meta = {};
  let value = local || empty();
  let serverAvailable = false;
  let conflict = meta.conflict === true;
  let etag = typeof meta.etag === "string" ? meta.etag : null;
  let timer;
  let saving = false;
  let queued = false;
  const status = (kind) =>
    onSaveStatus(
      conflict
        ? "conflict"
        : kind ||
            (timer || queued || saving
              ? "saving"
              : serverAvailable
                ? localAvailable
                  ? "saved"
                  : "msi"
                : localAvailable
                  ? "browser"
                  : "unsaved"),
    );
  const writeLocal = () => {
    try {
      localStorage.setItem(KEY, JSON.stringify(value));
      localStorage.setItem(SYNC_KEY, JSON.stringify(meta));
      localAvailable = true;
    } catch (_) {
      localAvailable = false;
    }
  };
  const markConflict = () => {
    conflict = true;
    meta.conflict = true;
    writeLocal();
    status();
  };
  const getServer = async () => {
    try {
      const response = await fetch("/api/review", {
        signal: AbortSignal.timeout(3500),
        cache: "no-store",
      });
      if (!response.ok || !response.headers.get("ETag")) return null;
      const body = await response.json();
      const review = body === null ? null : cleanReview(body, ids);
      if (body !== null && !review) return null;
      return { review, etag: response.headers.get("ETag") };
    } catch (_) {
      return null;
    }
  };
  const initial = await getServer();
  if (initial) {
    serverAvailable = true;
    const dirty = local && local.updatedAt !== meta.syncedUpdatedAt;
    if (conflict || (dirty && etag && etag !== initial.etag)) {
      markConflict();
    } else if (
      dirty &&
      !etag &&
      initial.review &&
      local.updatedAt !== initial.review.updatedAt
    ) {
      // A browser draft with no sync history must not overwrite another reviewer.
      markConflict();
    } else if (dirty) {
      etag = initial.etag;
      // Retain the original last-synced revision until a PUT succeeds.
    } else {
      value = initial.review || local || empty();
      etag = initial.etag;
      meta = { etag, syncedUpdatedAt: value.updatedAt, conflict: false };
    }
  }
  writeLocal();
  status();

  const send = async () => {
    clearTimeout(timer);
    timer = null;
    if (conflict) return;
    queued = true;
    if (saving) return;
    saving = true;
    while (queued && !conflict) {
      queued = false;
      if (!serverAvailable || !etag) {
        const remote = await getServer();
        if (!remote) {
          serverAvailable = false;
          break;
        }
        if (
          (etag && remote.etag !== etag) ||
          (!etag &&
            remote.review &&
            remote.review.updatedAt !== value.updatedAt)
        ) {
          markConflict();
          break;
        }
        etag = remote.etag;
      }
      const snapshotValue = structuredClone(value);
      const snapshot = JSON.stringify(snapshotValue);
      try {
        const response = await fetch("/api/review", {
          method: "PUT",
          headers: { "Content-Type": "application/json", "If-Match": etag },
          body: snapshot,
          signal: AbortSignal.timeout(5000),
          keepalive: new TextEncoder().encode(snapshot).byteLength < 60000,
        });
        if (response.status === 409) {
          markConflict();
          break;
        }
        if (!response.ok || !response.headers.get("ETag"))
          throw new Error("Save failed");
        etag = response.headers.get("ETag");
        serverAvailable = true;
        meta = {
          etag,
          syncedUpdatedAt: snapshotValue.updatedAt,
          conflict: false,
        };
        writeLocal();
      } catch (_) {
        serverAvailable = false;
      }
    }
    saving = false;
    status();
  };
  if (
    local &&
    initial &&
    !conflict &&
    value.updatedAt !== meta.syncedUpdatedAt
  ) {
    status("saving");
    void send();
  }
  document.addEventListener("visibilitychange", () => {
    if (document.hidden && timer) {
      clearTimeout(timer);
      void send();
    }
  });
  return {
    get value() {
      return value;
    },
    update(change) {
      change(value);
      value.updatedAt = new Date().toISOString();
      writeLocal();
      status("saving");
      clearTimeout(timer);
      if (!conflict) timer = setTimeout(send, 450);
    },
    async acceptServer() {
      const remote = await getServer();
      if (!remote) return false;
      clearTimeout(timer);
      value = remote.review || empty();
      etag = remote.etag;
      serverAvailable = true;
      conflict = false;
      meta = { etag, syncedUpdatedAt: value.updatedAt, conflict: false };
      writeLocal();
      status();
      return true;
    },
    flush: send,
  };
}
