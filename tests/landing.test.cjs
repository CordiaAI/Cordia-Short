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

function setup() {
  const landing = new Element();
  const auth = new Element();
  const email = new Element();
  const register = new Element();
  const signin = new Element();
  const close = new Element();
  register.setAttribute("data-auth-open", "register");
  signin.setAttribute("data-auth-open", "signin");
  landing.querySelectorAll = selector => selector === "[data-auth-open]" ? [register, signin] : [];
  auth.querySelector = selector => selector === "[data-auth-close]" ? close : selector === "input" ? email : null;
  const modes = [];
  const window = {};
  vm.runInNewContext(fs.readFileSync("static/landing.js", "utf8"), { window });
  const controller = window.CordiaLanding.createController({
    landing,
    auth,
    onMode: mode => modes.push(mode),
  });
  return { landing, auth, email, register, signin, close, modes, controller };
}

test("signed-out visitors see the public landing page before authentication", () => {
  const ui = setup();
  ui.controller.setSignedOut(true);
  assert.equal(ui.landing.hidden, false);
  assert.equal(ui.auth.hidden, true);
});

test("landing calls to action open the requested existing authentication mode", () => {
  const ui = setup();
  ui.controller.setSignedOut(true);
  ui.signin.fire("click");
  assert.equal(ui.landing.hidden, true);
  assert.equal(ui.auth.hidden, false);
  assert.deepEqual(ui.modes, ["signin"]);
  assert.equal(ui.email.focused, true);

  ui.close.fire("click");
  assert.equal(ui.landing.hidden, false);
  assert.equal(ui.auth.hidden, true);
});

test("authenticated visitors cannot reopen the public authentication surface", () => {
  const ui = setup();
  ui.controller.setSignedOut(false);
  ui.register.fire("click");
  assert.equal(ui.landing.hidden, true);
  assert.equal(ui.auth.hidden, true);
  assert.deepEqual(ui.modes, []);
});
