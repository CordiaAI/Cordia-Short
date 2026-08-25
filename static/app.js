let currentState = { state: "signed_out" };
let authMode = "register";

const byId = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json();
  if (!response.ok) throw Object.assign(new Error(payload.error || "Request failed"), { payload });
  return payload;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

function renderMessages(messages = []) {
  const container = byId("messages");
  container.innerHTML = messages.map((message) =>
    `<div class="message ${escapeHtml(message.role)}">${escapeHtml(message.content)}</div>`
  ).join("");
  container.scrollTop = container.scrollHeight;
}

function renderSetupCard(card) {
  const container = byId("setup-card");
  if (!card) {
    container.hidden = true;
    container.innerHTML = "";
    return;
  }
  const action = card.action_url
    ? `<a href="${escapeHtml(card.action_url)}">Continue securely</a>`
    : `<span class="status-pill">${escapeHtml(card.status)}</span>`;
  container.innerHTML = `
    <div class="assistant-mark">C</div>
    <div class="setup-copy"><small>CONNECTOR SETUP</small><h2>${escapeHtml(card.title)}</h2><p>${escapeHtml(card.message)}</p></div>
    ${action}`;
  container.hidden = false;
}

function renderArtifact(artifact) {
  const headings = (artifact.columns || []).map((column) => `<th>${escapeHtml(column)}</th>`).join("");
  const rows = (artifact.rows || []).map((row) =>
    `<tr>${row.map((value, index) => {
      const safe = escapeHtml(value);
      return index === row.length - 1 && /^https:\/\//.test(String(value))
        ? `<td><a href="${safe}" target="_blank" rel="noopener">Open</a></td>`
        : `<td>${safe}</td>`;
    }).join("")}</tr>`
  ).join("");
  return `<article class="artifact-window">
    <div class="artifact-title"><strong>${escapeHtml(artifact.title)}</strong><span>${escapeHtml(artifact.source)}</span></div>
    <div class="artifact-body"><table><thead><tr>${headings}</tr></thead><tbody>${rows}</tbody></table></div>
  </article>`;
}

function renderArtifacts(artifacts = []) {
  const container = byId("artifact-grid");
  container.innerHTML = artifacts.length
    ? artifacts.map(renderArtifact).join("")
    : `<article class="artifact-window"><div class="artifact-title"><strong>Your first artifact will appear here</strong><span>READY</span></div><div class="artifact-body"><p style="padding:18px;color:var(--muted)">Ask Cordia to connect a service or organize part of your work.</p></div></article>`;
}

function render(state, transient = {}) {
  currentState = state;
  const signedOut = state.state === "signed_out";
  byId("auth-panel").hidden = !signedOut;
  byId("app-shell").hidden = signedOut;
  byId("signout-button").hidden = signedOut;
  byId("status-pill").textContent = signedOut ? "Signed out" : state.state === "survey" ? "Surveyor" : "Agent online";
  if (signedOut) return;

  renderMessages(state.messages);
  renderArtifacts(state.artifacts);
  renderSetupCard(transient.setup_card || null);
  byId("memory").textContent = state.memory || "Cordia is still learning your workspace.";
  const survey = state.survey;
  byId("survey-prompt").hidden = !survey;
  byId("survey-prompt").textContent = survey ? survey.question : "";
  byId("message-input").placeholder = survey ? "Answer Surveyor…" : "Message Cordia…";
  const nameMatch = (state.memory || "").match(/## Name\s+([^#\n][^\n]*)/);
  byId("workspace-title").textContent = nameMatch ? `${nameMatch[1]}'s workspace` : "Your workspace";
  const params = new URLSearchParams(location.search);
  const notice = byId("notice");
  if (params.get("connected")) {
    notice.textContent = "Connector verified. Ask Cordia to use it.";
    notice.hidden = false;
  } else if (params.get("error")) {
    notice.textContent = "The connector was not verified. Return to chat and try again.";
    notice.hidden = false;
  }
}

async function refresh() {
  try { render(await api("/api/state")); }
  catch (error) { byId("status-pill").textContent = "Unavailable"; }
}

document.querySelectorAll("[data-auth-mode]").forEach((button) => {
  button.addEventListener("click", () => {
    authMode = button.dataset.authMode;
    document.querySelectorAll("[data-auth-mode]").forEach((item) => item.classList.toggle("active", item === button));
    byId("auth-submit").textContent = authMode === "register" ? "Create workspace" : "Sign in";
    byId("auth-error").textContent = "";
  });
});

byId("auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  byId("auth-error").textContent = "";
  try {
    const state = await api(`/api/${authMode}`, {
      method: "POST",
      body: JSON.stringify({ email: byId("email").value, password: byId("password").value }),
    });
    render(state);
  } catch (error) { byId("auth-error").textContent = error.message; }
});

byId("composer").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = byId("message-input");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  input.disabled = true;
  try {
    const path = currentState.state === "survey" ? "/api/survey" : "/api/chat";
    const body = currentState.state === "survey" ? { answer: message } : { message };
    const state = await api(path, { method: "POST", body: JSON.stringify(body) });
    render(state, state);
  } catch (error) {
    render(error.payload || currentState);
    const notice = byId("notice");
    notice.textContent = error.message;
    notice.hidden = false;
  } finally { input.disabled = false; input.focus(); }
});

byId("signout-button").addEventListener("click", async () => {
  await api("/api/signout", { method: "POST", body: "{}" });
  location.href = "/";
});

refresh();
