import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../assets/js/pages/runners/core/StorageManager.js", import.meta.url), "utf8");
const { StorageManager, RUNNER_STORAGE_CHANGE_EVENT } = await import(
  `data:text/javascript;charset=utf-8,${encodeURIComponent(source)}`
);

// Node 18 has no global CustomEvent; browsers do.
globalThis.CustomEvent ??= class extends Event {
  constructor(type, options = {}) {
    super(type);
    this.detail = options.detail;
  }
};

const store = new Map();
globalThis.localStorage = {
  getItem: (key) => (store.has(key) ? store.get(key) : null),
  setItem: (key, value) => store.set(key, String(value)),
  removeItem: (key) => store.delete(key),
};
globalThis.window = new EventTarget();

function collectEvents() {
  const keys = [];
  window.addEventListener(RUNNER_STORAGE_CHANGE_EVENT, (event) => keys.push(event.detail.storageKey));
  return keys;
}

test("saving a runner announces the change so the submission form can mark it saved", () => {
  const keys = collectEvents();
  new StorageManager("lesson_runner1").save("print('hi')");
  assert.equal(localStorage.getItem("lesson_runner1"), "print('hi')");
  assert.deepEqual(keys, ["lesson_runner1"]);
});

test("clearing a runner announces the change so the form can mark it unsaved again", () => {
  const keys = collectEvents();
  new StorageManager("lesson_runner2").clear();
  assert.deepEqual(keys, ["lesson_runner2"]);
});

test("a runner without a storage key stores nothing and announces nothing", () => {
  const keys = collectEvents();
  new StorageManager("").save("ignored");
  assert.deepEqual(keys, []);
});
