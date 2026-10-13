/**
 * gist-key-settings.js — the Profile page's "GitHub Gist Key" panel.
 *
 * Lets a student store their own GitHub token so code submissions are created
 * as gists under their account instead of the shared server token. The token
 * is write-only: the server encrypts it and only ever reports whether one exists.
 *
 *   import { initGistKeySettings } from '/assets/js/gist-key-settings.js';
 *   initGistKeySettings(document.getElementById('gistKeySettings'));
 */

import { javaURI, fetchOptions } from '/assets/js/api/config.js';

const ENDPOINT = `${javaURI}/api/gist-key`;

async function requestGistKey(method, body) {
  const res = await fetch(ENDPOINT, {
    ...fetchOptions,
    method,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `Request failed (${res.status})`);
  }
  return data;
}

function describeStatus({ enabled, configured }) {
  if (!enabled) return 'Personal Gist keys are not enabled on this server; submissions use the shared class key.';
  return configured
    ? 'A personal Gist key is saved. Your code submissions are created under your GitHub account.'
    : 'No personal key saved. Submissions use the shared class key, if the server has one.';
}

export function initGistKeySettings(root) {
  if (!root) return;
  const input = root.querySelector('[data-gist-key-input]');
  const saveBtn = root.querySelector('[data-gist-key-save]');
  const removeBtn = root.querySelector('[data-gist-key-remove]');
  const status = root.querySelector('[data-gist-key-status]');

  const render = (state) => {
    status.textContent = describeStatus(state);
    status.dataset.state = 'info';
    input.disabled = saveBtn.disabled = !state.enabled;
    removeBtn.hidden = !state.configured;
  };
  const showError = (err) => {
    status.textContent = err.message;
    status.dataset.state = 'error';
  };

  saveBtn.addEventListener('click', async () => {
    const token = input.value.trim();
    if (!token) {
      showError(new Error('Paste a GitHub token with the "gist" scope first.'));
      return;
    }
    try {
      render(await requestGistKey('PUT', { token }));
      input.value = ''; // never leave the secret sitting in the page
    } catch (err) {
      showError(err);
    }
  });

  removeBtn.addEventListener('click', async () => {
    try {
      render(await requestGistKey('DELETE'));
    } catch (err) {
      showError(err);
    }
  });

  requestGistKey('GET').then(render).catch(showError);
}
