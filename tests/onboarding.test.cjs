// Controller tests use a small DOM boundary double; visual/browser QA is separate.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');
const path = require('node:path');

const fixture = JSON.parse(execFileSync(process.env.CORDIA_TEST_PYTHON || path.resolve('../../.venv/Scripts/python.exe'), ['-c', `
import json
from tests.test_survey import valid_stages
from cordia.survey import STAGE_ORDER, public_stage_schema, conditional_discovery_fields
from cordia.onboarding import score_profile, normalize_applications
from cordia.connectors import CONNECTORS
stages = valid_stages()
answers = {key: value['answers'] for key, value in stages.items()}
cases = [{}, {'inputs':'Notes', 'control_level':'suggest_actions_only'}, {'current_workflow':'Our team reviews every week before a deadline'}, {'control_level':'automate_low_risk','sensitive_data':['financial'],'environment':['company_network']}, {'environment':['web']}]
print(json.dumps({'schema_version':2, 'current_stage':'workspace_review', 'completed_stages':list(stages), 'answers':answers, 'profile':score_profile(stages), 'review':{'workspace_discovery':answers['workspace_discovery']}, 'application_catalog':[{'id':v['id'],'name':v['name']} for v in CONNECTORS.values()], 'selected_applications':normalize_applications(answers['workspace_discovery']['applications'], CONNECTORS, {}), 'stage_schemas':{s:public_stage_schema(s, answers) for s in STAGE_ORDER}, 'conditional_cases':[[value,conditional_discovery_fields(value)] for value in cases]}))
`], { encoding: 'utf8' }));
const clone = value => JSON.parse(JSON.stringify(value));

class Element {
  constructor(tag, document) { this.tagName = tag.toUpperCase(); this.ownerDocument = document; this.children = []; this.attributes = {}; this.events = {}; this.value = ''; this.hidden = false; this.disabled = false; this._text = ''; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  setAttribute(name, value) { this.attributes[name] = String(value); if (name === 'id') this.id = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  append(...children) { for (const child of children) { child.parentElement = this; this.children.push(child); } }
  replaceChildren(...children) { this._text = ''; this.children = []; this.append(...children); }
  remove() { this.parentElement.children = this.parentElement.children.filter(child => child !== this); }
  addEventListener(type, handler) { (this.events[type] ||= []).push(handler); }
  async fire(type) { if (this.disabled) return; for (const handler of this.events[type] || []) await handler({ preventDefault() {}, target: this, currentTarget: this }); }
  focus() { this.ownerDocument.activeElement = this; }
  scrollTo() {}
  matches(selector) {
    if (selector.startsWith('#')) return this.id === selector.slice(1);
    const attr = selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
    if (attr) return this.getAttribute(attr[1]) !== null && (attr[2] === undefined || this.getAttribute(attr[1]) === attr[2]);
    return this.tagName.toLowerCase() === selector;
  }
  querySelectorAll(selector) { const matches = []; for (const child of this.children) { if (selector.split(',').some(part => child.matches(part.trim()))) matches.push(child); matches.push(...child.querySelectorAll(selector)); } return matches; }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

function setup(stage = 'assessment_part_1', handler) {
  const document = { activeElement: null, createElement(tag) { return new Element(tag, this); } };
  const root = document.createElement('section');
  for (const [id, tag] of [['onboarding-progress','p'], ['onboarding-title','h1'], ['onboarding-instructions','p'], ['onboarding-form','form']]) { const node = document.createElement(tag); node.id = id; root.append(node); }
  for (const [id, tag] of [['onboarding-fields','div'], ['onboarding-error','p'], ['onboarding-back','button'], ['onboarding-continue','button']]) { const node = document.createElement(tag); node.id = id; root.querySelector('form').append(node); }
  const window = {};
  const sourcePath = path.resolve('static/onboarding.js');
  assert.ok(fs.existsSync(sourcePath), 'onboarding controller is missing');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), { window, document });
  const calls = [], completions = [];
  const state = clone(fixture); state.current_stage = stage;
  if (stage === 'assessment_part_1') { state.completed_stages = []; state.answers = {}; }
  const api = async (url, options) => {
    calls.push({ url, options, body: options?.body ? JSON.parse(options.body) : undefined });
    if (handler) return handler(url, options, calls);
    return { onboarding: clone(state) };
  };
  const controller = window.CordiaOnboarding.createController({ root, api, onComplete: value => completions.push(value) });
  controller.show(state);
  return { root, document, state, calls, completions, controller, get: id => root.querySelector(`#${id}`) };
}
const group = (ui, field) => ui.root.querySelector(`[data-field="${field}"]`);
const buttons = node => node.querySelectorAll('button');
const choose = (ui, field, value) => {
  const button = buttons(group(ui, field)).find(node => node.getAttribute('data-value') === String(value));
  assert.ok(button, `${field} option ${value} missing`); return button.fire('click');
};
const input = async (ui, field, value) => { const node = ui.root.querySelector(`[name="${field}"]`); assert.ok(node, field); node.value = value; await node.fire('input'); return node; };
const submit = ui => ui.get('onboarding-form').fire('submit');

test('all twenty ratings serialize as integer answers and advance with focused heading', async () => {
  const ui = setup();
  assert.equal(ui.root.querySelectorAll('[data-field]').length, 20);
  for (let number = 1; number <= 20; number++) await choose(ui, `p1_${String(number).padStart(2, '0')}`, 4);
  await submit(ui);
  assert.equal(ui.calls[0].url, '/api/onboarding/assessment_part_1');
  assert.equal(ui.calls[0].options.method, 'PUT');
  assert.equal(Object.keys(ui.calls[0].body.answers).length, 20);
  assert.equal(ui.calls[0].body.answers.p1_20, 4);
  assert.equal(ui.get('onboarding-title').textContent, 'Part 2 of 4: Your domains');
  assert.equal(ui.document.activeElement, ui.get('onboarding-title'));
});

test('Continue gates all twenty ratings and programmatic incomplete submits do not save', async () => {
  const ui = setup();
  assert.equal(ui.get('onboarding-continue').disabled, true);
  await submit(ui);
  assert.equal(ui.calls.length, 0);
  for (let number = 1; number < 20; number++) await choose(ui, `p1_${String(number).padStart(2, '0')}`, 3);
  assert.equal(ui.get('onboarding-continue').disabled, true);
  await choose(ui, 'p1_20', 3);
  assert.equal(ui.get('onboarding-continue').disabled, false);
});

test('Continue requires domain ratings and every term; work needs only a self-rating', async () => {
  const ui = setup('assessment_part_2');
  ui.state.answers.assessment_part_2 = {};
  ui.controller.show(ui.state);
  assert.equal(ui.get('onboarding-continue').disabled, true);
  await choose(ui, 'domains', 'work_professional');
  assert.equal(ui.get('onboarding-continue').disabled, true);
  await choose(ui, 'rating:work_professional', 3);
  assert.equal(ui.get('onboarding-continue').disabled, false);
  await choose(ui, 'domains', 'technology_software');
  await choose(ui, 'rating:technology_software', 4);
  for (const term of fixture.stage_schemas.assessment_part_2.domains.technology_software.terms.slice(0, -1)) await choose(ui, `technology_software:${term}`, 'familiar');
  assert.equal(ui.get('onboarding-continue').disabled, true);
  await choose(ui, 'technology_software:API', 'not_familiar');
  assert.equal(ui.get('onboarding-continue').disabled, false);
  await choose(ui, 'domains', 'work_professional');
  await choose(ui, 'domains', 'technology_software');
  assert.equal(ui.get('onboarding-continue').disabled, true);
});

test('Continue requires every communication choice and distinct MOST/LEAST', async () => {
  const ui = setup('assessment_part_3');
  ui.state.answers.assessment_part_3 = {};
  ui.controller.show(ui.state);
  assert.equal(ui.get('onboarding-continue').disabled, true);
  for (const [field, answer] of Object.entries(fixture.answers.assessment_part_3)) if (field !== 'least') await choose(ui, field, answer);
  await choose(ui, 'least', 'logical');
  assert.equal(ui.get('onboarding-continue').disabled, true);
  await choose(ui, 'least', 'practical');
  assert.equal(ui.get('onboarding-continue').disabled, false);
});

test('Continue rejects blank or overlength requests and honors optional third request', async () => {
  const ui = setup('assessment_part_4');
  assert.equal(ui.get('onboarding-continue').disabled, false);
  await input(ui, 'request_2', '   ');
  assert.equal(ui.get('onboarding-continue').disabled, true);
  await submit(ui);
  assert.equal(ui.calls.length, 0);
  await input(ui, 'request_2', 'Review my notes.');
  assert.equal(ui.get('onboarding-continue').disabled, false);
  await input(ui, 'request_3', 'x'.repeat(2001));
  assert.equal(ui.get('onboarding-continue').disabled, true);
  await input(ui, 'request_3', '');
  assert.equal(ui.get('onboarding-continue').disabled, false);
});

test('Continue checks discovery core, application details, removal and active optional text', async () => {
  const ui = setup('workspace_discovery');
  assert.equal(ui.get('onboarding-continue').disabled, false);
  await input(ui, 'outcome', ' ');
  assert.equal(ui.get('onboarding-continue').disabled, true);
  await input(ui, 'outcome', 'Review source notes');
  await input(ui, 'application-0-desired_activities', '');
  assert.equal(ui.get('onboarding-continue').disabled, true);
  await input(ui, 'application-0-desired_activities', 'Prepare report');
  assert.equal(ui.get('onboarding-continue').disabled, false);
  await choose(ui, 'sensitive_data', 'financial');
  await input(ui, 'sensitive_data_details', 'x'.repeat(4001));
  assert.equal(ui.get('onboarding-continue').disabled, true);
  await choose(ui, 'sensitive_data', 'financial');
  assert.equal(ui.get('onboarding-continue').disabled, false, 'hidden stale details are omitted');
  await ui.root.querySelector('[aria-label="Remove Google Drive"]').fire('click');
  assert.equal(ui.get('onboarding-continue').disabled, false);
  await ui.root.querySelector('[aria-label="Remove Team Notes"]').fire('click');
  assert.equal(ui.get('onboarding-continue').disabled, true);
  await input(ui, 'application_search', 'My notes');
  await ui.root.querySelector('[data-add-manual]').fire('click');
  assert.equal(ui.get('onboarding-continue').disabled, true);
  for (const field of ['current_activities', 'desired_activities', 'inputs_outputs']) await input(ui, `application-0-${field}`, 'Notes');
  assert.equal(ui.get('onboarding-continue').disabled, false);
});

test('server errors preserve text and busy state prevents duplicate submission and Back', async () => {
  let reject;
  const ui = setup('assessment_part_4', () => new Promise((resolve, fail) => { reject = fail; }));
  await input(ui, 'request_1', 'Keep this unsaved request');
  const pending = submit(ui);
  assert.equal(ui.get('onboarding-back').disabled, true);
  assert.equal(ui.get('onboarding-continue').disabled, true);
  await submit(ui);
  assert.equal(ui.calls.length, 1);
  reject(new Error('Request 2 is required'));
  await pending;
  assert.equal(ui.get('onboarding-error').textContent, 'Request 2 is required');
  assert.equal(ui.root.querySelector('[name="request_1"]').value, 'Keep this unsaved request');
  assert.equal(ui.get('onboarding-continue').disabled, false);
});

test('domains enforce maximum two, allow deselection, omit inactive ratings and familiarity', async () => {
  const ui = setup('assessment_part_2');
  await choose(ui, 'domains', 'money_finance');
  await choose(ui, 'domains', 'health_wellness');
  assert.match(ui.get('onboarding-error').textContent, /2/);
  await choose(ui, 'domains', 'technology_software');
  await choose(ui, 'domains', 'work_professional');
  await choose(ui, 'rating:work_professional', 5);
  await choose(ui, 'rating:money_finance', 3);
  for (const term of fixture.stage_schemas.assessment_part_2.domains.money_finance.terms) await choose(ui, `money_finance:${term}`, 'not_familiar');
  await submit(ui);
  assert.deepEqual(ui.calls[0].body.domains, ['money_finance', 'work_professional']);
  assert.equal(ui.calls[0].body.ratings.technology_software, undefined);
  assert.deepEqual(ui.calls[0].body.familiarity.work_professional, {});
});

test('MOST and LEAST remain distinct, with visible independent labeled controls', async () => {
  const ui = setup('assessment_part_3');
  await choose(ui, 'most', 'practical');
  await choose(ui, 'least', 'practical');
  assert.match(ui.get('onboarding-error').textContent, /different/);
  await submit(ui);
  assert.equal(ui.calls[0].body.most, 'practical');
  assert.equal(ui.calls[0].body.least, 'imaginative');
});

test('resume and Back use saved answers without requests; snapshot Continue does not save computed data', async () => {
  const ui = setup('profile_snapshot');
  assert.equal(ui.root.querySelectorAll('[data-axis]').length, 3);
  assert.equal(ui.root.querySelectorAll('meter').length, 5);
  await ui.get('onboarding-back').fire('click');
  assert.equal(ui.root.querySelector('[name="request_1"]').value, 'Help me plan today.');
  assert.equal(ui.calls.length, 0);
  await submit(ui);
  assert.equal(ui.get('onboarding-title').textContent, 'Profile snapshot');
  await submit(ui);
  assert.equal(ui.get('onboarding-title').textContent, 'Workspace Discovery');
  assert.equal(ui.calls.length, 1);
});

test('discovery uses shared server conditions and never serializes inactive stale details', async () => {
  const ui = setup('workspace_discovery');
  await choose(ui, 'sensitive_data', 'financial');
  await input(ui, 'sensitive_data_details', '<img src=x onerror=alert(1)>');
  await choose(ui, 'sensitive_data', 'financial');
  assert.equal(group(ui, 'sensitive_data_details').hidden, true);
  await choose(ui, 'environment', 'company_network');
  await input(ui, 'environment_policy', 'Private network only');
  await choose(ui, 'environment', 'company_network');
  await submit(ui);
  assert.equal(ui.calls[0].body.sensitive_data_details, undefined);
  assert.equal(ui.calls[0].body.environment_policy, undefined);
  assert.deepEqual(ui.calls[0].body.sensitive_data, []);
  assert.equal(ui.root.querySelector('img'), null);
});

test('browser visibility agrees with server rules for core and trigger combinations', () => {
  for (const [answers, active] of fixture.conditional_cases) {
    const ui = setup('workspace_discovery');
    ui.state.answers.workspace_discovery = answers;
    ui.controller.show(ui.state);
    const schema = fixture.stage_schemas.workspace_discovery.conditional_fields;
    for (const [field, metadata] of Object.entries(schema)) {
      if (!metadata.when_any) continue;
      assert.equal(group(ui, field).hidden, !active.includes(field), `${field}: ${JSON.stringify(answers)}`);
    }
  }
});

test('first slice is an editable suggestion from outputs; no invented action or model request', async () => {
  const ui = setup('workspace_discovery');
  delete ui.state.answers.workspace_discovery.first_workspace;
  ui.controller.show(ui.state);
  assert.equal(ui.root.querySelector('[name="first_workspace"]').value, 'A status report.');
  await input(ui, 'first_workspace', 'Only collect source notes');
  await input(ui, 'outputs', 'Different output');
  await submit(ui);
  assert.equal(ui.calls[0].body.first_workspace, 'Only collect source notes');
});

test('application search/manual add uses catalog, captures use and control, has no connection actions', async () => {
  const ui = setup('workspace_discovery');
  await input(ui, 'application_search', 'openai');
  const results = ui.root.querySelector('[data-application-results]');
  assert.ok(results.textContent.includes('OpenAI API'));
  assert.ok(!results.textContent.includes('Google Drive'));
  await buttons(results).find(node => node.textContent.includes('OpenAI API')).fire('click');
  await input(ui, 'application_search', '<script>My planning app</script>');
  await ui.root.querySelector('[data-add-manual]').fire('click');
  for (const index of [2, 3]) for (const field of ['current_activities', 'desired_activities', 'inputs_outputs']) await input(ui, `application-${index}-${field}`, 'Project notes');
  await submit(ui);
  const known = ui.calls[0].body.applications.find(app => app.application_id === 'openai_api');
  const manual = ui.calls[0].body.applications.at(-1);
  assert.equal(known.name, 'OpenAI API');
  assert.equal(manual.application_id, null);
  assert.equal(manual.name, '<script>My planning app</script>');
  assert.equal(manual.wants_added, true);
  assert.equal(manual.control_level, 'suggest_actions_only');
  assert.equal(ui.root.querySelector('script'), null);
  assert.ok(ui.calls.every(call => !call.url.includes('/connectors/')));
});

test('review uses normalized statuses, completion only invokes callback for workspace state', async () => {
  let success = false;
  const ui = setup('workspace_review', () => success ? { state: 'workspace', selected_applications: [] } : { state: 'onboarding' });
  assert.ok(ui.get('onboarding-fields').textContent.includes('Setup required'));
  assert.ok(ui.get('onboarding-fields').textContent.includes('Planned'));
  assert.equal(ui.get('onboarding-continue').textContent, 'Build my workspace');
  await submit(ui);
  assert.equal(ui.completions.length, 0);
  assert.ok(ui.get('onboarding-error').textContent);
  success = true;
  await submit(ui);
  assert.equal(ui.completions.length, 1);
  assert.equal(ui.calls[0].url, '/api/onboarding/complete');
  assert.equal(ui.calls[0].options.method, 'POST');
});

test('show can load the server resume endpoint and hide closes the layer', async () => {
  const ui = setup('assessment_part_2');
  await ui.controller.show();
  assert.equal(ui.calls[0].url, '/api/onboarding');
  assert.equal(ui.root.hidden, false);
  ui.controller.hide();
  assert.equal(ui.root.hidden, true);
});

test('saved stage navigation preserves disabled catalog selections on the new screen', async () => {
  const ui = setup('assessment_part_4');
  await submit(ui);
  await submit(ui);
  const catalog = ui.root.querySelector('[data-application-results]');
  const selected = buttons(catalog).find(button => button.textContent === 'Google Drive');
  assert.equal(selected.disabled, true);
  assert.equal(selected.getAttribute('aria-pressed'), 'true');
});

test('failed discovery save keeps selected catalog entries disabled and safe user text intact', async () => {
  const ui = setup('workspace_discovery', () => { throw new Error('outcome is required'); });
  const text = '<img src=x onerror=alert(1)> & unusual <words>';
  await input(ui, 'outcome', text);
  await submit(ui);
  assert.equal(ui.root.querySelector('[name="outcome"]').value, text);
  assert.equal(ui.root.querySelector('img'), null);
  assert.equal(buttons(ui.root.querySelector('[data-application-results]')).find(button => button.textContent === 'Google Drive').disabled, true);
});

test('application use, activity, control and removal serialize the exact application contract', async () => {
  const ui = setup('workspace_discovery');
  await choose(ui, 'application-0-use', 'wants_added');
  await choose(ui, 'application-0-control_level', 'perform_approved_actions');
  await input(ui, 'application-0-current_activities', 'Read source notes');
  const remove = ui.root.querySelector('[aria-label="Remove Team Notes"]');
  await remove.fire('click');
  await submit(ui);
  assert.equal(ui.calls[0].body.applications.length, 1);
  assert.deepEqual(ui.calls[0].body.applications[0], {
    application_id: 'google_drive', name: 'Google Drive', already_uses: true, wants_added: false,
    current_activities: 'Read source notes', desired_activities: 'Collect the source notes.',
    inputs_outputs: 'Notes in, report draft out.', control_level: 'perform_approved_actions',
  });
});

test('app integration hides workspace and background navigation during onboarding, then restores workspace statuses safely', () => {
  const ui = setup('assessment_part_1');
  const elements = {};
  const html = fs.readFileSync('static/index.html', 'utf8');
  for (const match of html.matchAll(/id="([^"]+)"/g)) elements[match[1]] = ui.document.createElement('div');
  elements.onboarding = ui.root;
  const topbar = ui.document.createElement('header');
  ui.document.getElementById = id => elements[id];
  ui.document.querySelector = selector => selector === '.topbar' ? topbar : null;
  ui.document.querySelectorAll = () => [];
  ui.document.addEventListener = () => {};
  for (const [id, attribute] of [['live-view-permission','data-live-view-confirm'], ['workspace-settings','data-settings-close']]) {
    const button = ui.document.createElement('button'); button.setAttribute(attribute, ''); elements[id].append(button);
  }
  const window = {};
  vm.runInNewContext(fs.readFileSync('static/onboarding.js', 'utf8'), { window });
  const context = vm.createContext({ window, document: ui.document, URLSearchParams, location: { search: '' }, fetch: () => new Promise(() => {}) });
  vm.runInContext(fs.readFileSync('static/app.js', 'utf8'), context);
  context.render({ state: 'onboarding', onboarding: ui.state });
  assert.equal(elements['app-shell'].hidden, true);
  assert.equal(elements.account.hidden, true);
  assert.equal(topbar.hidden, true, 'background navigation must not remain keyboard-reachable');
  context.render({ state: 'workspace', messages: [], artifacts: [], selected_applications: [{ name: '<img src=x>', status: 'planned' }] });
  assert.equal(ui.root.hidden, true);
  assert.equal(topbar.hidden, false);
  assert.equal(elements['app-shell'].hidden, false);
  assert.equal(elements.account.hidden, false);
  assert.ok(elements['selected-applications'].innerHTML.includes('&lt;img src=x&gt;'));
  assert.ok(elements['selected-applications'].innerHTML.includes('Planned'));
  context.render({ state: 'signed_out' });
  assert.equal(elements['app-shell'].hidden, true);
  assert.equal(elements.account.hidden, true);
  assert.equal(elements['auth-panel'].hidden, false);
  assert.equal(ui.root.hidden, true);
});
