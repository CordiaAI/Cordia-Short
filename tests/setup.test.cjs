// Controller tests with a DOM/fetch double; native browser checks are separate.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function app() {
  const nodes = new Map();
  const node = (id) => {
    if (!nodes.has(id)) nodes.set(id, {
      listeners: {}, hidden: false, innerHTML: '', textContent: '',
      addEventListener(name, callback) { this.listeners[name] = callback; },
      setAttribute() {}, querySelector() { return node(id + '-child'); },
      querySelectorAll() { return []; },
    });
    return nodes.get(id);
  };
  const requests = [];
  const context = vm.createContext({
    document: { getElementById: node, querySelector: node, querySelectorAll: () => [], addEventListener() {} },
    window: { CordiaOnboarding: { createController: () => ({ hide() {} }) } },
    location: { search: '' }, URLSearchParams,
    fetch: async (url, options) => {
      requests.push({ url, options });
      return { ok: true, json: async () => ({ state: 'workspace', messages: [], artifacts: [] }) };
    },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8'), context);
  return { node, context, requests };
}

test('connector setup can be cancelled through its authenticated endpoint', async () => {
  const { node, context, requests } = app();
  await new Promise(setImmediate);
  vm.runInContext("renderSetupCard({connector_id:'openai_api', type:'credential_form', title:'OpenAI', fields:[]})", context);
  assert.match(node('setup-card').innerHTML, /data-connector-cancel/);
  const button = { dataset: { connectorId: 'openai_api' }, disabled: false };
  await node('setup-card').listeners.click({ target: { closest: () => button } });
  const sent = requests.find((item) => item.url === '/api/connectors/cancel');
  assert.equal(sent.options.method, 'POST');
  assert.deepEqual(JSON.parse(sent.options.body), { connector_id: 'openai_api' });
  assert.equal(node('setup-card').hidden, true);
  assert.match(node('notice').textContent, /cancelled/i);
});

test('failed cancellation remains retryable and displays the server error', async () => {
  const { node, context } = app();
  await new Promise(setImmediate);
  vm.runInContext("fetch = async () => ({ok:false,json:async()=>({error:'This workspace already has a request running'})})", context);
  const button = { dataset: { connectorId: 'openai_api' }, disabled: false };
  await node('setup-card').listeners.click({ target: { closest: () => button } });
  assert.equal(button.disabled, false);
  assert.match(node('notice').textContent, /already has a request running/);
  assert.equal(node('notice').hidden, false);
});
