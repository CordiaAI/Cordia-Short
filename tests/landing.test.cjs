const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor() {
    this.hidden = false;
    this.attributes = {};
    this.events = {};
    this.focused = false;
  }

  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener(type, handler) { (this.events[type] ||= []).push(handler); }
  fire(type) { for (const handler of this.events[type] || []) handler({ preventDefault() {} }); }
  focus() { this.focused = true; }
}

function setup(initialMode) {
  const landing = new Element();
  const auth = new Element();
  const email = new Element();
  const close = new Element();
  auth.querySelector = selector => selector === "[data-auth-close]" ? close : selector === "input" ? email : null;
  const modes = [];
  const window = {};
  vm.runInNewContext(fs.readFileSync("static/landing.js", "utf8"), { window });
  const controller = window.CordiaLanding.createController({
    landing,
    auth,
    onMode: mode => modes.push(mode),
    initialMode,
  });
  return { landing, auth, email, close, modes, controller };
}

test("signed-out visitors see the public landing page before authentication", () => {
  const ui = setup();
  ui.controller.setSignedOut(true);
  assert.equal(ui.landing.hidden, false);
  assert.equal(ui.auth.hidden, true);
});

test("a new workspace-entry tab opens its requested authentication mode", () => {
  const ui = setup("register");
  ui.controller.setSignedOut(true);
  assert.equal(ui.landing.hidden, true);
  assert.equal(ui.auth.hidden, false);
  assert.deepEqual(ui.modes, ["register"]);
  assert.equal(ui.email.focused, true);

  ui.close.fire("click");
  assert.equal(ui.landing.hidden, false);
  assert.equal(ui.auth.hidden, true);
});

test("a cached authenticated session ignores workspace-entry authentication intent", () => {
  const ui = setup("register");
  ui.controller.setSignedOut(false);
  assert.equal(ui.landing.hidden, true);
  assert.equal(ui.auth.hidden, true);
  assert.deepEqual(ui.modes, []);
});
