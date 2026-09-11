const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");


class Element {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = {};
    this.className = "";
    this.hidden = false;
    this._text = "";
  }

  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }

  get textContent() {
    return this._text + this.children.map((child) => child.textContent).join("");
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this._text = "";
    this.children = [...children];
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  querySelectorAll(selector) {
    const wanted = selector.toUpperCase();
    const found = [];
    for (const child of this.children) {
      if (child.tagName === wanted) found.push(child);
      found.push(...child.querySelectorAll(selector));
    }
    return found;
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  getContext() {
    if (this.tagName !== "CANVAS") return null;
    return {
      beginPath() {},
      moveTo() {},
      lineTo() {},
      stroke() {},
      arc() {},
      fill() {},
      fillText() {},
      clearRect() {},
      set strokeStyle(value) {},
      set fillStyle(value) {},
      set lineWidth(value) {},
      set font(value) {},
    };
  }
}


function loadRenderer() {
  const document = { createElement: (tagName) => new Element(tagName) };
  const window = {};
  vm.runInNewContext(
    fs.readFileSync("static/survey-results.js", "utf8"),
    { window, document },
  );
  return { document, window };
}


function resultsFixture() {
  return {
    status: { label: "Workspace coming soon", detail: "Saved." },
    plot: {
      x: {
        title: "Execution autonomy",
        score: 54,
        label: "Shared execution",
        references: [{ title: "Requested control", score: 33, weight: 2 }],
      },
      y: {
        title: "Communication context",
        score: 75,
        label: "High-context collaboration",
        references: [{ title: "Context preference", score: 100, weight: 2 }],
      },
      z: {
        title: "Workflow complexity",
        score: 48,
        label: "Connected workflow",
        references: [{ title: "Workflow breadth", score: 20, weight: 2 }],
      },
    },
    direct_findings: [
      { title: "Outcome", statement: "<img src=x>", detail: "User supplied.", plot_axis: "z" },
    ],
    connector_plans: [
      {
        name: "Slack",
        status: "Setup required",
        auth_method: "OAuth",
        current_activities: "Team messages",
        desired_activities: "Send approved updates",
        inputs_outputs: "Project status in, message out",
        control: "Perform approved actions",
        setup_note: "Sign-in required.",
      },
    ],
    indirect_findings: [
      {
        title: "Execution style",
        statement: "Act first.",
        evidence: ["Direct", "Answer/action-first"],
        confidence: "high",
        cordia_behavior: "Return the result first.",
      },
    ],
    unknowns: [
      {
        title: "Failure recovery",
        statement: "Not enough evidence to choose recovery behavior.",
      },
    ],
  };
}


test("survey results render bounded sections without HTML interpolation", () => {
  const { document, window } = loadRenderer();
  const root = document.createElement("main");

  window.CordiaSurveyResults.render(root, resultsFixture());

  assert.match(root.textContent, /Workspace coming soon/);
  assert.match(root.textContent, /Slack/);
  assert.match(root.textContent, /Not enough evidence/);
  assert.match(root.textContent, /<img src=x>/);
  assert.equal(root.querySelector("img"), null);
  assert.equal(root.querySelectorAll("canvas").length, 1);
  assert.equal(root.querySelectorAll("dl").length, 1);
  assert.match(root.textContent, /X · Execution autonomy/);
  assert.match(root.textContent, /Requested control · 33\/100 · 2× weight/);
  assert.match(root.textContent, /Z reference/);
});


test("survey results expose a visible but unavailable workspace builder", () => {
  const { document, window } = loadRenderer();
  const root = document.createElement("main");

  window.CordiaSurveyResults.render(root, resultsFixture());

  const buildButton = root.querySelectorAll("button").find(
    (button) => button.textContent === "Build workspace",
  );
  assert.ok(buildButton);
  assert.equal(buildButton.disabled, true);
  assert.equal(buildButton.attributes["aria-disabled"], "true");
});


test("missing plot renders saved status without drawing invented coordinates", () => {
  const { document, window } = loadRenderer();
  const root = document.createElement("main");
  const results = resultsFixture();
  results.plot = null;

  window.CordiaSurveyResults.render(root, results);

  assert.match(root.textContent, /Saved/);
  assert.equal(root.querySelector("canvas"), null);
});


test("results activation shows only the results surface", () => {
  const { document, window } = loadRenderer();
  const surfaces = {
    auth: document.createElement("section"),
    onboarding: document.createElement("section"),
    workspace: document.createElement("main"),
    results: document.createElement("main"),
  };
  for (const surface of Object.values(surfaces)) surface.hidden = false;

  const handled = window.CordiaSurveyResults.activate(
    surfaces,
    { state: "results", survey_results: resultsFixture() },
  );

  assert.equal(handled, true);
  assert.equal(surfaces.auth.hidden, true);
  assert.equal(surfaces.onboarding.hidden, true);
  assert.equal(surfaces.workspace.hidden, true);
  assert.equal(surfaces.results.hidden, false);
  assert.match(surfaces.results.textContent, /How Cordia will work with you/);
});
