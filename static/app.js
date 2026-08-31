let currentState = { state: "signed_out" };
let authMode = "register";
let activeLiveViewSource = null;
let pendingLiveView = null;
let settingsArtifacts = [];

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

const onboardingController = window.CordiaOnboarding.createController({
  root: byId("onboarding"),
  api,
  onComplete: (state) => render(state),
});

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

function adjustmentControls(responseId) {
  return `
    <div class="message-actions">
      <button type="button" data-helpful>Helpful</button>
      <button type="button" data-adjust-toggle>Adjust response</button>
    </div>
    <div class="adjustment-panel" hidden>
      <strong>What should Cordia change?</strong>
      <p>Choose the direction that would make this response more useful.</p>
      <div class="adjustment-row"><span>Prompt context</span><div>
        <button type="button" data-axis="context" data-target="-1">Use only what I said</button>
        <button type="button" data-axis="context" data-target="1">Use more context</button>
      </div></div>
      <div class="adjustment-row"><span>Level of detail</span><div>
        <button type="button" data-axis="scope" data-target="-1">Focus on the details</button>
        <button type="button" data-axis="scope" data-target="1">Show the bigger picture</button>
      </div></div>
      <div class="adjustment-row"><span>Communication style</span><div>
        <button type="button" data-axis="directness" data-target="-1">Use a measured tone</button>
        <button type="button" data-axis="directness" data-target="1">Be more direct</button>
      </div></div>
      <div class="adjustment-row"><span>Type of response</span><div>
        <button type="button" data-axis="implementation" data-target="-1">Explain the reasoning</button>
        <button type="button" data-axis="implementation" data-target="1">Give me the implementation</button>
      </div></div>
    </div>`;
}

function renderMessages(messages = [], allowAdjustments = false) {
  const container = byId("messages");
  container.innerHTML = messages.map((message) => {
    const controls = allowAdjustments && message.role === "assistant" && message.kind === "agent"
      ? adjustmentControls(message.id)
      : "";
    return `<div class="message-block ${escapeHtml(message.role)}" data-response-id="${escapeHtml(message.id)}">
      <div class="message ${escapeHtml(message.role)}">${escapeHtml(message.content)}</div>
      ${controls}
    </div>`;
  }).join("");
  container.scrollTop = container.scrollHeight;
}

function renderPendingMessage(message) {
  const pendingMessages = [
    ...(currentState.messages || []),
    { id: "pending-user", role: "user", kind: "chat", content: message },
  ];
  renderMessages(pendingMessages, false);
  const container = byId("messages");
  container.insertAdjacentHTML("beforeend", `
    <div class="message-block assistant cordia-pending" role="status" aria-label="Cordia is working">
      <div class="cordia-working" aria-hidden="true">∞</div>
    </div>`);
  container.scrollTop = container.scrollHeight;
}

function renderSetupCard(card) {
  const container = byId("setup-card");
  if (!card) {
    container.hidden = true;
    container.innerHTML = "";
    return;
  }
  const credentialFields = (card.fields || []).map((field) => `
    <label>${escapeHtml(field.label)}
      <input name="${escapeHtml(field.name)}" type="${escapeHtml(field.type)}" ${field.required ? "required" : ""} autocomplete="off">
    </label>`).join("");
  const action = card.type === "credential_form"
    ? `<form class="credential-form" data-connector-form data-connector-id="${escapeHtml(card.connector_id)}" data-submit-url="${escapeHtml(card.submit_url)}">
        ${credentialFields}
        <button type="submit">Verify and connect</button>
      </form>`
    : card.action_url
      ? `<a href="${escapeHtml(card.action_url)}">Continue securely</a>`
      : `<span class="status-pill">${escapeHtml(String(card.status || "Setup required").replaceAll("_", " "))}</span>`;
  container.innerHTML = `
    <div class="setup-copy"><small>CONNECTOR SETUP</small><h2>${escapeHtml(card.title)}</h2><p>${escapeHtml(card.message)}</p></div>
    ${action}`;
  container.hidden = false;
}

function renderArtifact(artifact, options = {}) {
  const rowAction = artifact.row_action;
  const headings = (artifact.columns || []).map((column) => `<th>${escapeHtml(column)}</th>`).join("")
    + (rowAction ? "<th>Use</th>" : "");
  const rows = (artifact.rows || []).map((row) => {
    const cells = row.map((value, index) => {
      const safe = escapeHtml(value);
      return index === row.length - 1 && /^https:\/\//.test(String(value))
        ? `<td><a href="${safe}" target="_blank" rel="noopener">Open</a></td>`
        : `<td>${safe}</td>`;
    }).join("");
    if (!rowAction) return `<tr>${cells}</tr>`;
    const value = String(row[rowAction.value_column] ?? "");
    const selectable = !rowAction.allowed_values || rowAction.allowed_values.includes(value);
    if (!selectable) return `<tr>${cells}<td><span class="model-unavailable">Unavailable</span></td></tr>`;
    const active = value === String(artifact.active_value ?? "");
    const button = `<button type="button" class="model-select" data-model-select
      data-endpoint="${escapeHtml(rowAction.endpoint)}" data-connector-id="${escapeHtml(artifact.source)}"
      data-value="${escapeHtml(value)}" ${active ? "disabled" : ""}>${active ? "Active" : escapeHtml(rowAction.label)}</button>`;
    return `<tr>${cells}<td>${button}</td></tr>`;
  }).join("");
  const liveView = artifact.live_view || {};
  const isLive = !options.settings && activeLiveViewSource === artifact.source;
  const logo = liveView.logo
    ? `<img class="connector-logo" src="${escapeHtml(liveView.logo)}" alt="${escapeHtml(artifact.connector_name || artifact.source)} logo">`
    : "";
  const liveViewButton = !options.settings && liveView.status && liveView.status !== "unsupported"
    ? `<button type="button" class="live-view-button" data-live-view data-connector-id="${escapeHtml(artifact.source)}" aria-pressed="${isLive}">${isLive ? "Live View on" : "Live View"}</button>`
    : "";
  return `<article class="artifact-window${isLive ? " live-view-active" : ""}" data-artifact-source="${escapeHtml(artifact.source)}">
    <div class="artifact-title"><div class="artifact-identity">${logo}<strong>${escapeHtml(artifact.title)}</strong></div>${liveViewButton}</div>
    <div class="artifact-body"><table><thead><tr>${headings}</tr></thead><tbody>${rows}</tbody></table></div>
  </article>`;
}

function renderArtifacts(artifacts = []) {
  const container = byId("artifact-grid");
  settingsArtifacts = artifacts.filter((artifact) => artifact.surface === "workspace_settings");
  const visibleArtifacts = artifacts.filter((artifact) => artifact.surface !== "workspace_settings");
  container.innerHTML = visibleArtifacts.length
    ? visibleArtifacts.map((artifact) => renderArtifact(artifact)).join("")
    : `<article class="artifact-window"><div class="artifact-title"><strong>Your first artifact will appear here</strong></div><div class="artifact-body"><p class="artifact-empty">Ask Cordia to connect a service or organize part of your work.</p></div></article>`;
  renderWorkspaceSettings();
}

function renderWorkspaceSettings() {
  const runtime = currentState.agent_runtime;
  byId("workspace-runtime").textContent = runtime
    ? `Cordia Agent is using ${runtime.provider} · ${runtime.model}.`
    : "No agent model has been selected yet.";
  byId("workspace-models").innerHTML = settingsArtifacts.length
    ? settingsArtifacts.map((artifact) => renderArtifact(artifact, { settings: true })).join("")
    : `<p class="settings-summary">Connect a model provider to manage it here.</p>`;
}

function renderSelectedApplications(applications = []) {
  const container = byId("selected-applications");
  const statuses = { requested: "Requested", planned: "Planned", setup_required: "Setup required", verified: "Verified", needs_attention: "Needs attention" };
  container.hidden = !applications.length;
  container.innerHTML = applications.length ? `
    <h2 id="selected-applications-title">Selected applications</h2>
    <p>Planning context. Setup required and planned applications are not connected.</p>
    ${applications.map((application) => `<div class="selected-application-row"><strong>${escapeHtml(application.name)}</strong><span class="application-status">${escapeHtml(statuses[application.status] || "Requested")}</span></div>`).join("")}` : "";
}

function openLiveViewPermission(artifact) {
  const liveView = artifact.live_view;
  pendingLiveView = { connectorId: artifact.source };
  byId("live-view-logo").src = liveView.logo;
  byId("live-view-logo").alt = `${artifact.connector_name || artifact.source} logo`;
  byId("live-view-title").textContent = `Open ${artifact.connector_name || "connector"} Live View`;
  byId("live-view-summary").textContent = liveView.permission.summary;
  byId("live-view-data").innerHTML = liveView.permission.data.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  byId("live-view-actions").innerHTML = liveView.permission.actions.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  byId("live-view-revocation").textContent = liveView.permission.revocation;
  byId("live-view-permission").querySelector("[data-live-view-confirm]").textContent = liveView.status === "granted"
    ? "Open Live View"
    : liveView.permission.authorize_label || "Continue securely";
  byId("live-view-permission").showModal();
}

async function activateLiveView(connectorId) {
  const state = await api("/api/connectors/live-view", {
    method: "POST",
    body: JSON.stringify({ connector_id: connectorId }),
  });
  if (state.setup_card) {
    if (state.setup_card.action_url) {
      sessionStorage.setItem("cordia-live-view-return", connectorId);
      location.assign(state.setup_card.action_url);
      return;
    }
    render(state, state);
    const notice = byId("notice");
    notice.textContent = state.setup_card.message || "This connector needs configuration before Live View can open.";
    notice.hidden = false;
    return;
  }
  if (!state.artifact) throw new Error("Live View returned no provider artifact.");
  activeLiveViewSource = connectorId;
  render(state, state);
  const notice = byId("notice");
  notice.textContent = "Live View is open with fresh provider data.";
  notice.hidden = false;
}

function render(state, transient = {}) {
  currentState = state;
  const signedOut = state.state === "signed_out";
  const isOnboarding = state.state === "onboarding";
  document.querySelector(".topbar").hidden = isOnboarding;
  byId("auth-panel").hidden = !signedOut;
  byId("app-shell").hidden = signedOut || isOnboarding;
  byId("account").hidden = signedOut || isOnboarding;
  const agentRuntime = state.agent_runtime;
  byId("status-pill").textContent = signedOut
    ? "Signed out"
    : isOnboarding
      ? "Surveyor"
      : agentRuntime
        ? `Agent online · ${agentRuntime.provider} · ${agentRuntime.model}`
        : "Agent online";
  if (signedOut) { onboardingController.hide(); return; }
  if (isOnboarding) {
    onboardingController.show(state.onboarding).catch((error) => { byId("onboarding-error").textContent = error.message; });
    return;
  }
  onboardingController.hide();

  renderMessages(state.messages, state.state === "workspace");
  renderArtifacts(state.artifacts);
  renderSelectedApplications(state.selected_applications);
  renderSetupCard(transient.setup_card || state.setup_card || null);
  byId("operator").textContent = state.operator || "Cordia is still learning how you work.";
  byId("message-input").placeholder = "Message Cordia…";
  const nameMatch = (state.operator || "").match(/## Name\s+([^#\n][^\n]*)/);
  byId("workspace-title").textContent = nameMatch ? `${nameMatch[1]}'s workspace` : "Your workspace";
  byId("account-initial").textContent = nameMatch ? nameMatch[1].trim().charAt(0).toUpperCase() : "∞";
  const params = new URLSearchParams(location.search);
  const notice = byId("notice");
  if (params.get("connected")) {
    const updateStatus = params.get("workspace_update");
    notice.textContent = updateStatus === "updated"
      ? "Connector verified. Cordia updated your workspace automatically."
      : updateStatus === "failed"
        ? "Connector verified, but its first workspace view could not be loaded yet."
        : "Connector verified and ready.";
    notice.hidden = false;
    const resumeLiveView = sessionStorage.getItem("cordia-live-view-return");
    if (resumeLiveView) {
      sessionStorage.removeItem("cordia-live-view-return");
      queueMicrotask(() => activateLiveView(resumeLiveView).catch((error) => {
        notice.textContent = error.message;
        notice.hidden = false;
      }));
    }
  } else if (params.get("error")) {
    sessionStorage.removeItem("cordia-live-view-return");
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
    document.querySelectorAll("[data-auth-mode]").forEach((item) => {
      item.classList.toggle("active", item === button);
      item.setAttribute("aria-pressed", String(item === button));
    });
    byId("auth-title").textContent = authMode === "register" ? "Create account" : "Sign in";
    byId("password").autocomplete = authMode === "register" ? "new-password" : "current-password";
    byId("password-help").hidden = authMode !== "register";
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

const composer = byId("composer");
const messageInput = byId("message-input");

messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    composer.requestSubmit();
  }
});

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = messageInput;
  const message = input.value.trim();
  if (!message || input.disabled) return;
  input.value = "";
  input.disabled = true;
  renderPendingMessage(message);
  try {
    const state = await api("/api/chat", { method: "POST", body: JSON.stringify({ message }) });
    render(state, state);
  } catch (error) {
    render(error.payload || currentState);
    const notice = byId("notice");
    notice.textContent = error.message;
    notice.hidden = false;
  } finally { input.disabled = false; input.focus(); }
});

byId("messages").addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const block = button.closest(".message-block");
  if (!block) return;
  if (button.hasAttribute("data-helpful")) {
    button.textContent = "Thanks — noted";
    button.disabled = true;
    return;
  }
  const panel = block.querySelector(".adjustment-panel");
  if (button.hasAttribute("data-adjust-toggle")) {
    panel.hidden = !panel.hidden;
    button.setAttribute("aria-expanded", String(!panel.hidden));
    return;
  }
  if (!button.dataset.axis) return;
  panel.querySelectorAll("button").forEach((item) => { item.disabled = true; });
  const notice = byId("notice");
  notice.textContent = "Updating your operator profile and revising the response…";
  notice.hidden = false;
  try {
    const state = await api(`/api/responses/${block.dataset.responseId}/adjust`, {
      method: "POST",
      body: JSON.stringify({ axis: button.dataset.axis, target: Number(button.dataset.target) }),
    });
    render(state, state);
    const updatedNotice = byId("notice");
    updatedNotice.textContent = "Preference updated. Cordia revised the response.";
    updatedNotice.hidden = false;
  } catch (error) {
    render(error.payload || currentState);
    const errorNotice = byId("notice");
    errorNotice.textContent = error.message;
    errorNotice.hidden = false;
  }
});

byId("setup-card").addEventListener("submit", async (event) => {
  const form = event.target.closest("[data-connector-form]");
  if (!form) return;
  event.preventDefault();
  const credentials = Object.fromEntries(new FormData(form).entries());
  const controls = form.querySelectorAll("input, button");
  controls.forEach((control) => { control.disabled = true; });
  const notice = byId("notice");
  notice.textContent = "Verifying the connector directly with the provider…";
  notice.hidden = false;
  try {
    const state = await api(form.dataset.submitUrl || "/api/connectors/setup", {
      method: "POST",
      body: JSON.stringify({ connector_id: form.dataset.connectorId, credentials }),
    });
    form.reset();
    render(state);
    const successNotice = byId("notice");
    successNotice.textContent = state.workspace_update?.status === "updated"
      ? "Connector verified. Cordia updated your workspace automatically."
      : state.workspace_update?.status === "failed"
        ? "Connector verified, but its first workspace view could not be loaded yet."
        : "Connector verified and ready.";
    successNotice.hidden = false;
  } catch (error) {
    render(error.payload || currentState);
    const errorNotice = byId("notice");
    errorNotice.textContent = error.message;
    errorNotice.hidden = false;
  } finally {
    controls.forEach((control) => { control.disabled = false; });
  }
});

byId("artifact-grid").addEventListener("click", async (event) => {
  const liveViewButton = event.target.closest("[data-live-view]");
  if (liveViewButton) {
    const connectorId = liveViewButton.dataset.connectorId;
    if (activeLiveViewSource === connectorId) {
      activeLiveViewSource = null;
      render(currentState);
      return;
    }
    const artifact = (currentState.artifacts || []).find((item) => item.source === connectorId);
    if (artifact?.live_view) openLiveViewPermission(artifact);
    return;
  }
  const button = event.target.closest("[data-model-select]");
  if (!button) return;
  button.disabled = true;
  const notice = byId("notice");
  notice.textContent = `Verifying ${button.dataset.value} with the provider…`;
  notice.hidden = false;
  try {
    const state = await api(button.dataset.endpoint || "/api/connectors/select", {
      method: "POST",
      body: JSON.stringify({
        connector_id: button.dataset.connectorId,
        value: button.dataset.value,
      }),
    });
    render(state);
    const successNotice = byId("notice");
    successNotice.textContent = `${state.selection.value} is now powering your Cordia Agent.`;
    successNotice.hidden = false;
  } catch (error) {
    render(error.payload || currentState);
    const errorNotice = byId("notice");
    errorNotice.textContent = error.message;
    errorNotice.hidden = false;
  }
});

byId("workspace-models").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-model-select]");
  if (!button) return;
  button.disabled = true;
  try {
    const state = await api(button.dataset.endpoint || "/api/connectors/select", {
      method: "POST",
      body: JSON.stringify({ connector_id: button.dataset.connectorId, value: button.dataset.value }),
    });
    render(state);
    byId("workspace-runtime").textContent = `${state.selection.value} is now powering your Cordia Agent.`;
  } catch (error) {
    button.disabled = false;
    byId("workspace-runtime").textContent = error.message;
  }
});

const accountMenuButton = byId("account-menu-button");
const accountMenu = byId("account-menu");
function setAccountMenu(open) {
  accountMenu.hidden = !open;
  accountMenuButton.setAttribute("aria-expanded", String(open));
}
accountMenuButton.addEventListener("click", (event) => {
  event.stopPropagation();
  setAccountMenu(accountMenu.hidden);
});
document.addEventListener("click", (event) => {
  if (!byId("account").contains(event.target)) setAccountMenu(false);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") setAccountMenu(false);
});
accountMenu.addEventListener("click", async (event) => {
  if (event.target.closest("[data-workspace-settings]")) {
    setAccountMenu(false);
    renderWorkspaceSettings();
    byId("workspace-settings").showModal();
  }
  if (!event.target.closest("[data-signout]")) return;
  await api("/api/signout", { method: "POST", body: "{}" });
  location.href = "/";
});

byId("live-view-permission").addEventListener("click", (event) => {
  if (event.target.closest("[data-live-view-cancel]")) {
    pendingLiveView = null;
    byId("live-view-permission").close();
  }
});
byId("live-view-permission").querySelector("[data-live-view-confirm]").addEventListener("click", async (event) => {
  if (!pendingLiveView) return;
  const confirmButton = event.currentTarget;
  confirmButton.disabled = true;
  try {
    const connectorId = pendingLiveView.connectorId;
    pendingLiveView = null;
    byId("live-view-permission").close();
    await activateLiveView(connectorId);
  } catch (error) {
    byId("live-view-permission").close();
    const notice = byId("notice");
    notice.textContent = error.message;
    notice.hidden = false;
  } finally {
    confirmButton.disabled = false;
  }
});
byId("workspace-settings").querySelector("[data-settings-close]").addEventListener("click", () => {
  byId("workspace-settings").close();
});

refresh();
