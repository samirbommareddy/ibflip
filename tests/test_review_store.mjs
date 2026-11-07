import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { openReview } from "../designs/lab/review-store.mjs";

const originals = new Map(
  ["localStorage", "document", "matchMedia", "fetch"].map((key) => [
    key,
    Object.getOwnPropertyDescriptor(globalThis, key),
  ]),
);
afterEach(() => {
  for (const [key, descriptor] of originals) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else delete globalThis[key];
  }
});

function setup() {
  const data = new Map();
  let remote = null;
  let revision = 0;
  let writable = true;
  const writes = [];
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      getItem: (key) => data.get(key) ?? null,
      setItem: (key, value) => {
        if (!writable) throw new Error("Storage unavailable");
        data.set(key, value);
      },
    },
  });
  globalThis.document = { addEventListener() {} };
  globalThis.matchMedia = () => ({ matches: false });
  globalThis.fetch = async (_url, request = {}) => {
    const tag = `"${revision}"`;
    if (request.method !== "PUT") {
      return new Response(JSON.stringify(remote), { headers: { ETag: tag } });
    }
    writes.push(request);
    if (request.headers["If-Match"] !== tag) {
      return new Response(JSON.stringify({ review: remote }), {
        status: 409,
        headers: { ETag: tag },
      });
    }
    remote = JSON.parse(request.body);
    revision += 1;
    return new Response(JSON.stringify(remote), {
      headers: { ETag: `"${revision}"` },
    });
  };
  return {
    writes,
    get remote() {
      return remote;
    },
    changeRemote(change) {
      change(remote);
      revision += 1;
    },
    disableBrowserStorage() {
      writable = false;
    },
  };
}

test("decisions, notes and resume position save and reopen", async () => {
  const server = setup();
  const store = await openReview(["play", "select"], () => {});
  store.update((review) => {
    review.currentId = "select";
    review.generalNote = "Keep it calm.";
    review.decisions.play = {
      option: "arc",
      status: "changes",
      note: "Slower.",
    };
  });
  await store.flush();
  const reopened = await openReview(["play", "select"], () => {});
  assert.deepEqual(reopened.value, server.remote);
  assert.equal(reopened.value.decisions.play.note, "Slower.");
  assert.equal(reopened.value.currentId, "select");
});

test("a conflicting draft survives reload without overwriting another session", async () => {
  const server = setup();
  const statuses = [];
  const store = await openReview(["play"], (status) => statuses.push(status));
  store.update((review) => {
    review.generalNote = "Original";
  });
  await store.flush();
  server.changeRemote((review) => {
    review.generalNote = "Other session";
  });
  store.update((review) => {
    review.generalNote = "Unsynced draft";
  });
  await store.flush();
  assert.equal(statuses.at(-1), "conflict");
  assert.equal(server.remote.generalNote, "Other session");
  const count = server.writes.length;
  const reloadedStatuses = [];
  const reloaded = await openReview(["play"], (status) =>
    reloadedStatuses.push(status),
  );
  assert.equal(reloaded.value.generalNote, "Unsynced draft");
  assert.equal(reloadedStatuses.at(-1), "conflict");
  await reloaded.flush();
  assert.equal(server.writes.length, count);
  assert.equal(await reloaded.acceptServer(), true);
  assert.equal(reloaded.value.generalNote, "Other session");
});

test("large feedback uses ordinary requests instead of the keepalive body budget", async () => {
  const server = setup();
  const ids = Array.from({ length: 20 }, (_, i) => `moment-${i}`);
  const store = await openReview(ids, () => {});
  store.update((review) => {
    for (const id of ids) {
      review.decisions[id] = {
        option: "arc",
        status: "changes",
        note: "x".repeat(4000),
      };
    }
  });
  await store.flush();
  assert.equal(server.writes.at(-1).keepalive, false);
  assert.equal(Object.keys(server.remote.decisions).length, 20);
});

test("saving on MSI does not claim browser persistence when storage fails", async () => {
  const server = setup();
  server.disableBrowserStorage();
  const statuses = [];
  const store = await openReview(["play"], (status) => statuses.push(status));
  store.update((review) => {
    review.generalNote = "Still save on MSI.";
  });
  await store.flush();
  assert.equal(server.remote.generalNote, "Still save on MSI.");
  assert.equal(statuses.at(-1), "msi");
});
