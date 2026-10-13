// Fired on window whenever a runner's saved code changes, so page widgets such as
// the submission form's "saved / not saved yet" list can refresh instead of
// showing what was true at page load.
export const RUNNER_STORAGE_CHANGE_EVENT = 'runner-storage-change';

function announceChange(storageKey) {
  window.dispatchEvent(new CustomEvent(RUNNER_STORAGE_CHANGE_EVENT, { detail: { storageKey } }));
}

export class StorageManager {
  constructor(storageKey = '') {
    this.storageKey = storageKey;
  }

  get(fallback = '') {
    if (!this.storageKey) return fallback;
    const storedValue = localStorage.getItem(this.storageKey);
    return storedValue !== null ? storedValue : fallback;
  }

  save(value = '') {
    if (this.storageKey) {
      localStorage.setItem(this.storageKey, value);
      announceChange(this.storageKey);
    }
    return value;
  }

  clear() {
    if (this.storageKey) {
      localStorage.removeItem(this.storageKey);
      announceChange(this.storageKey);
    }
  }
}

export default StorageManager;
