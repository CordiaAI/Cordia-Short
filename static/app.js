let currentState = { state: "signed_out" };
let authMode = "register";
let settingsArtifacts = [];
let agentRequestActive = false;
let hiddenArtifactIds = new Set();

try {
  hiddenArtifactIds = new Set(JSON.parse(window.sessionStorage?.getItem("cordia-hidden-artifacts") || "[]"));
} catch (_error) {
  hiddenArtifactIds = new Set();
}

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

function compactAssistantMessage(value) {
  const clean = String(value || "")
    .replace(/\[([^\]]+)\]\(https?:\/\/[^)]+\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "")
    .replace(/\s+/g, " ")
    .trim();
  const parts = clean.split(/(?<=[.!?])\s+|\s+-\s+/);
  for (let part of parts) {
    part = part.replace(/^\s*[-*]\s+/, "").trim();
    if (!part || /^(evidence|permalink|trace|provider ids?|source ids?)\s*:/i.test(part)) continue;
    part = part.replace(/^(?:result\s*:|done|completed|finished)\s*(?:[.:—-]\s*)?/i, "").trim();
    part = part.replace(/^I\s+/i, "");
    if (!part) continue;
    if (part.length > 160) part = `${part.slice(0, 157).replace(/\s+\S*$/, "")}…`;
    part = part.charAt(0).toUpperCase() + part.slice(1);
    return /[.!?…]$/.test(part) ? part : `${part}.`;
  }
  return "Cordia could not summarize the result.";
}

function visibleMessages(messages) {
  return messages.reduce((visible, message) => {
    const content = message.role === "assistant"
      ? compactAssistantMessage(message.content)
      : String(message.content || "");
    const previous = visible[visible.length - 1];
    if (message.role === "assistant" && previous?.role === "assistant" && previous.content === content) return visible;
    visible.push({ ...message, content });
    return visible;
  }, []);
}

function renderMessages(messages = []) {
  const container = byId("messages");
  container.innerHTML = visibleMessages(messages).map((message) => `
    <div class="message-block ${escapeHtml(message.role)}" data-response-id="${escapeHtml(message.id)}">
      <div class="message ${escapeHtml(message.role)}">${escapeHtml(message.content)}</div>
    </div>`).join("");
  container.scrollTop = container.scrollHeight;
}

function renderPendingMessage(message) {
  const pendingMessages = [
    ...(currentState.messages || []),
    { id: "pending-user", role: "user", kind: "chat", content: message },
  ];
  renderMessages(pendingMessages);
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
    container.classList.remove("action-approval-card");
    container.removeAttribute("role");
    container.removeAttribute("aria-labelledby");
    return;
  }
  const isApproval = card.type === "action_approval";
  container.classList.toggle("action-approval-card", isApproval);
  if (isApproval) {
    const details = (card.details || []).slice(0, 3).map((detail) => `
      <div><dt>${escapeHtml(detail.label)}</dt><dd>${escapeHtml(detail.value)}</dd></div>`).join("");
    const logo = card.application_logo
      ? `<img class="approval-logo" src="${escapeHtml(card.application_logo)}" alt="">`
      : `<span class="approval-logo-fallback material-symbols-outlined" aria-hidden="true">approval</span>`;
    container.innerHTML = `
      <div class="approval-summary">
        ${logo}
        <div class="setup-copy">
          <small>APPROVAL REQUIRED</small>
          <h2 id="approval-title">${escapeHtml(card.title || "Approve action")}</h2>
          <p>${escapeHtml(card.message || "Review the details before Cordia acts.")}</p>
        </div>
      </div>
      ${details ? `<dl class="approval-details">${details}</dl>` : ""}
      <div class="approval-actions">
        <button type="button" data-action-approval="true" data-connector-id="${escapeHtml(card.connector_id)}">${escapeHtml(card.confirm_label || "Approve")}</button>
        <button type="button" class="quiet-button" data-action-approval="false" data-connector-id="${escapeHtml(card.connector_id)}">Cancel</button>
      </div>`;
    container.setAttribute("role", "region");
    container.setAttribute("aria-labelledby", "approval-title");
    container.hidden = false;
    return;
  }
  container.removeAttribute("role");
  container.removeAttribute("aria-labelledby");
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
    ${action}
    <button type="button" data-connector-cancel data-connector-id="${escapeHtml(card.connector_id)}">Cancel setup</button>`;
  container.hidden = false;
}

function renderArtifact(artifact, options = {}) {
  const application = applicationForArtifact(artifact);
  const displayName = application?.name || artifact.connector_name || artifact.title || "Workspace view";
  const logoUrl = application?.logo || artifact.live_view?.logo;
  const logo = logoUrl
    ? `<img class="connector-logo" src="${escapeHtml(logoUrl)}" alt="">`
    : `<span class="connector-logo-fallback material-symbols-outlined" aria-hidden="true">widgets</span>`;
  const columns = artifactColumns(artifact);
  const rowAction = artifact.row_action;
  const contextId = /^\d+$/.test(String(artifact.id || "")) ? artifact.id : "";
  const keyValue = columns.length === 2
    && String(columns[0].label).toLowerCase() === "field"
    && String(columns[1].label).toLowerCase() === "value";
  const headings = columns.map(({ label }) => `<th>${escapeHtml(humanize(label))}</th>`).join("")
    + (rowAction ? "<th>Use</th>" : "");
  const sourceRows = (artifact.rows || []).filter((row) =>
    !(keyValue && (
      isTechnicalField(row[columns[0].index])
      || isOpaqueIdentifier(row[columns[1].index])
    ))
  );
  const rows = sourceRows.slice(0, 8).map((row) => {
    const cells = columns.map(({ index }) => `<td>${renderCell(row[index])}</td>`).join("");
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
  const actions = options.settings ? [] : artifactActions(artifact, application);
  const actionButtons = actions.length
    ? `<div class="artifact-actions" aria-label="${escapeHtml(displayName)} actions">${actions.map((action) => {
      const starter = action.isStarter
        ? ` data-action-id="${escapeHtml(action.id)}" data-connector-id="${escapeHtml(action.connectorId)}"`
        : "";
      return `<button type="button" data-artifact-action data-artifact-id="${escapeHtml(contextId)}" data-prompt="${escapeHtml(action.prompt)}"${starter}>${escapeHtml(action.label)}</button>`;
    }).join("")}</div>`
    : "";
  const operation = artifact.summary || humanize(artifact.operation_id || "Connected workspace data");
  const totalRows = sourceRows.length;
  const receipt = keyValue ? sourceRows.slice(0, 6).map((row) => {
    const rawLabel = String(row[columns[0].index] || "Detail");
    const rawValue = row[columns[1].index];
    const isStatus = rawLabel.toLowerCase() === "ok";
    const label = isStatus ? "Status" : humanize(rawLabel);
    const value = isStatus ? (rawValue === true ? "Completed" : "Needs attention") : rawValue;
    const linkLabel = /^https:\/\//.test(String(rawValue || "")) ? `Open in ${displayName}` : "Open";
    return `<div><span>${escapeHtml(label)}</span><strong>${renderCell(value, linkLabel)}</strong></div>`;
  }).join("") : "";
  const body = artifact.type === "metric"
    ? `<div class="artifact-metric">${escapeHtml(artifact.value)}</div>`
    : artifact.type === "summary" || artifact.type === "list"
      ? `<div class="artifact-items">${(artifact.items || []).slice(0, 10).map((item) => `<div><span>${escapeHtml(item.label || "")}</span><strong>${renderCell(item.value ?? item)}</strong></div>`).join("")}</div>`
      : receipt
        ? `<div class="artifact-items artifact-receipt">${receipt}</div>`
      : rows
        ? `<table><thead><tr>${headings}</tr></thead><tbody>${rows}</tbody></table>${totalRows > 8 ? `<p class="artifact-count">Showing 8 of ${totalRows}</p>` : ""}`
        : `<p class="artifact-empty">Cordia connected this source. Ask for the first useful view below.</p>`;
  const tools = options.settings ? "" : `<div class="artifact-tools">
      <button type="button" class="artifact-icon-button" data-artifact-refresh data-artifact-id="${escapeHtml(contextId)}" data-artifact-name="${escapeHtml(displayName)}" aria-label="Refresh ${escapeHtml(displayName)}" title="Refresh window"><span class="material-symbols-outlined" aria-hidden="true">refresh</span></button>
      <button type="button" class="artifact-icon-button" data-artifact-hide data-artifact-key="${escapeHtml(artifactKey(artifact))}" aria-label="Hide ${escapeHtml(displayName)}" title="Hide window"><span class="material-symbols-outlined" aria-hidden="true">close</span></button>
    </div>`;
  const prompt = options.settings ? "" : `<form class="artifact-composer" data-artifact-prompt data-artifact-id="${escapeHtml(contextId)}" data-artifact-name="${escapeHtml(displayName)}">
      <label class="sr-only" for="artifact-input-${escapeHtml(artifactKey(artifact))}">Ask Cordia to work with ${escapeHtml(displayName)}</label>
      <div class="voice-field">
        <input id="artifact-input-${escapeHtml(artifactKey(artifact))}" name="artifact_prompt" type="text" maxlength="4000" placeholder="Ask Cordia in ${escapeHtml(displayName)}…" autocomplete="off">
        <button class="voice-button" type="button" data-voice-target="artifact-input-${escapeHtml(artifactKey(artifact))}" aria-label="Speak a ${escapeHtml(displayName)} request" title="Speak request"><span class="material-symbols-outlined" aria-hidden="true">mic</span></button>
        <span class="voice-status sr-only" aria-live="polite"></span>
      </div>
      <button class="artifact-send" type="submit" aria-label="Send ${escapeHtml(displayName)} request" title="Send request"><span class="material-symbols-outlined" aria-hidden="true">arrow_upward</span></button>
    </form>`;
  return `<article class="artifact-window${options.settings ? " settings-artifact" : ""}" data-artifact-source="${escapeHtml(artifact.source)}" data-artifact-id="${escapeHtml(artifact.id)}">
    <div class="artifact-title"><div class="artifact-identity">${logo}<div><strong>${escapeHtml(displayName)}</strong><small>${escapeHtml(operation)}</small></div></div>${tools}</div>
    ${actionButtons}
    <div class="artifact-body">${body}</div>
    ${prompt}
  </article>`;
}

function renderArtifacts(artifacts = []) {
  const container = byId("artifact-grid");
  settingsArtifacts = artifacts.filter((artifact) => artifact.surface === "workspace_settings");
  const workspaceArtifacts = artifacts.filter((artifact) => artifact.surface !== "workspace_settings");
  const representedSources = new Set(workspaceArtifacts.map((artifact) => artifact.source).filter(Boolean));
  const connectorShells = (currentState.selected_applications || [])
    .filter((application) => application.status === "verified"
      && (application.registry_id || application.application_id)
      && !representedSources.has(application.registry_id || application.application_id))
    .map((application) => ({
      id: `connector:${application.registry_id || application.application_id}`,
      type: "connector",
      title: application.name,
      connector_name: application.name,
      source: application.registry_id || application.application_id,
      operation_id: "",
      summary: "Connected",
      columns: [],
      rows: [],
      actions: application.actions || [],
    }));
  const visibleArtifacts = [...workspaceArtifacts, ...connectorShells];
  const displayed = visibleArtifacts.filter((artifact) => !hiddenArtifactIds.has(artifactKey(artifact)));
  const hiddenCount = visibleArtifacts.length - displayed.length;
  container.innerHTML = displayed.length
    ? displayed.map((artifact) => renderArtifact(artifact)).join("")
    : `<article class="artifact-window artifact-placeholder"><div class="artifact-title"><div class="artifact-identity"><span class="connector-logo-fallback material-symbols-outlined" aria-hidden="true">dashboard</span><strong>Your first workspace window</strong></div></div><div class="artifact-body"><p class="artifact-empty">Cordia is preparing the first useful view from your Surveyor plan.</p></div></article>`;
  if (hiddenCount) {
    container.insertAdjacentHTML("beforeend", `<button class="restore-artifacts" type="button" data-artifacts-restore>Restore ${hiddenCount} hidden window${hiddenCount === 1 ? "" : "s"}</button>`);
  }
  window.CordiaVoice?.enhanceAll(container);
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

function humanize(value) {
  return String(value || "")
    .replace(/^.*?-/, "")
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function artifactKey(artifact) {
  return String(artifact.id || `${artifact.source || "workspace"}:${artifact.operation_id || artifact.title}`);
}

function saveHiddenArtifacts() {
  try {
    window.sessionStorage?.setItem("cordia-hidden-artifacts", JSON.stringify([...hiddenArtifactIds]));
  } catch (_error) {
    // Hiding a window is still useful when browser storage is unavailable.
  }
}

function applicationForArtifact(artifact) {
  return (currentState.selected_applications || []).find((application) =>
    [application.registry_id, application.application_id].includes(artifact.source)
  ) || null;
}

function isTechnicalField(value) {
  return /(^id$|_id$|^is_|^has_|created|updated|deleted|metadata|auth|token|scope|secret|password|color|^tz$|locale|profile|timestamp|^ts$|^type$)/i.test(String(value || ""));
}

function isOpaqueIdentifier(value) {
  const text = String(value ?? "").trim();
  return /^[A-Z][A-Z0-9]{8,}$/.test(text)
    || /^\d{9,}(?:\.\d+)?$/.test(text)
    || /^[0-9a-f]{8}-(?:[0-9a-f-]{27,})$/i.test(text);
}

function compactValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value !== "string") return String(value);
  const clean = value.trim();
  if (!/^[{\[]/.test(clean)) return clean;
  try {
    const parsed = JSON.parse(clean);
    if (Array.isArray(parsed)) return `${parsed.length} item${parsed.length === 1 ? "" : "s"}`;
    if (parsed && typeof parsed === "object") {
      const primary = ["text", "message", "title", "name", "status"]
        .map((key) => parsed[key])
        .find((item) => typeof item === "string" && item.trim());
      if (primary) return primary.trim();
      const details = Object.entries(parsed)
        .filter(([key, item]) => !isTechnicalField(key) && ["string", "number", "boolean"].includes(typeof item))
        .slice(0, 2)
        .map(([key, item]) => `${humanize(key)}: ${item}`);
      return details.join(" · ") || "Details available";
    }
  } catch (_error) {
    return clean;
  }
  return clean;
}

function renderCell(value, linkLabel = "Open") {
  const compact = compactValue(value);
  return /^https:\/\//.test(compact)
    ? `<a href="${escapeHtml(compact)}" target="_blank" rel="noopener">${escapeHtml(linkLabel)}</a>`
    : escapeHtml(compact);
}

function artifactColumns(artifact) {
  const columns = (artifact.columns || []).map((label, index) => ({ label, index }));
  const useful = columns.filter(({ label }) => !isTechnicalField(label));
  return (useful.length ? useful : columns).slice(0, 4);
}

function artifactActions(artifact, application) {
  const connectorId = application?.registry_id || application?.application_id || artifact.source || "";
  const applicationActions = (application?.actions || []).map((action) => ({
    ...action,
    connectorId,
    isStarter: true,
  }));
  const actions = [...applicationActions, ...(artifact.actions || [])]
    .filter((action) => action && typeof action.prompt === "string" && action.prompt.trim())
    .map((action) => ({
      id: action.id || "",
      label: action.label || humanize(action.id || "Run action"),
      prompt: action.prompt.trim(),
      connectorId: action.connectorId || "",
      isStarter: action.isStarter === true,
    }));
  return actions
    .filter((action, index, all) => all.findIndex((candidate) => candidate.label.toLowerCase() === action.label.toLowerCase()) === index)
    .slice(0, 5);
}

function render(state, transient = {}) {
  currentState = state;
  const params = new URLSearchParams(location.search);
  if (window.opener && (params.get("connected") || params.get("error"))) {
    window.opener.postMessage({ type: "cordia-connector-return" }, location.origin);
    window.close();
    return;
  }
  const signedOut = state.state === "signed_out";
  const isOnboarding = state.state === "onboarding";
  document.querySelector(".topbar").hidden = isOnboarding;
  byId("account").hidden = signedOut || isOnboarding;
  const agentRuntime = state.agent_runtime;
  byId("status-pill").textContent = signedOut
    ? "Signed out"
    : isOnboarding
      ? "Surveyor"
      : state.state === "results"
        ? "Profile saved"
      : agentRuntime
        ? `Agent online · ${agentRuntime.provider} · ${agentRuntime.model}`
        : "Agent online";
  if (window.CordiaSurveyResults.activate({
    auth: byId("auth-panel"),
    onboarding: byId("onboarding"),
    workspace: byId("app-shell"),
    results: byId("survey-results"),
  }, state)) {
    onboardingController.hide();
    return;
  }
  byId("survey-results").hidden = true;
  byId("auth-panel").hidden = !signedOut;
  byId("app-shell").hidden = signedOut || isOnboarding;
  if (signedOut) { onboardingController.hide(); return; }
  if (isOnboarding) {
    onboardingController.show(state.onboarding).catch((error) => { byId("onboarding-error").textContent = error.message; });
    return;
  }
  onboardingController.hide();

  renderMessages(state.messages);
  renderArtifacts(state.artifacts);
  renderSetupCard(transient.setup_card || state.setup_card || null);
  byId("message-input").placeholder = "Message Cordia…";
  const nameMatch = (state.operator || "").match(/## Name\s+([^#\n][^\n]*)/);
  byId("workspace-title").textContent = "My Workspace";
  byId("account-initial").textContent = nameMatch ? nameMatch[1].trim().charAt(0).toUpperCase() : "∞";
  const notice = byId("notice");
  notice.textContent = "";
  notice.hidden = true;
  if (state.build_error) {
    notice.textContent = state.build_error;
    notice.hidden = false;
  } else if (params.get("connected")) {
    const updateStatus = params.get("workspace_update");
    notice.textContent = updateStatus === "updated"
      ? "Connector verified. Cordia updated your workspace automatically."
      : updateStatus === "failed"
        ? "Connector verified. Cordia saved the available workspace view."
        : "Connector verified and ready.";
    notice.hidden = false;
    window.history.replaceState({}, "", location.pathname);
  } else if (params.get("error")) {
    notice.textContent = "The connector was not verified. Return to chat and try again.";
    notice.hidden = false;
    window.history.replaceState({}, "", location.pathname);
  }
}

async function refresh() {
  try { render(await api("/api/state")); }
  catch (error) { byId("status-pill").textContent = "Unavailable"; }
}

window.addEventListener?.("message", (event) => {
  if (event.origin === location.origin && event.data?.type === "cordia-connector-return") refresh();
});

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
window.CordiaVoice?.enhance(messageInput, byId("message-voice"));

async function sendAgentMessage(message, { input = null, artifactId = null, actionStarter = null } = {}) {
  const clean = String(message || "").trim();
  if (!clean || agentRequestActive) return;
  agentRequestActive = true;
  if (input) input.value = "";
  document.querySelectorAll(".composer input, .composer textarea, .composer button, .artifact-composer input, .artifact-composer button")
    .forEach((control) => { control.disabled = true; });
  byId("notice").hidden = true;
  renderPendingMessage(clean);
  try {
    const body = artifactId ? { message: clean, artifact_id: artifactId } : { message: clean };
    if (actionStarter) body.action_starter = actionStarter;
    const state = await api("/api/chat", { method: "POST", body: JSON.stringify(body) });
    render(state, state);
  } catch (error) {
    render(error.payload || currentState);
    const notice = byId("notice");
    notice.textContent = error.message;
    notice.hidden = false;
  } finally {
    agentRequestActive = false;
    document.querySelectorAll(".composer input, .composer textarea, .composer button, .artifact-composer input, .artifact-composer button")
      .forEach((control) => { control.disabled = false; });
    if (input?.isConnected) input.focus();
  }
}

messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    composer.requestSubmit();
  }
});

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!messageInput.disabled) await sendAgentMessage(messageInput.value, { input: messageInput });
});

byId("setup-card").addEventListener("click", async (event) => {
  const approval = event.target.closest("[data-action-approval]");
  if (approval && approval.dataset.actionApproval !== undefined && !approval.disabled) {
    approval.parentElement.querySelectorAll("button").forEach((item) => { item.disabled = true; });
    try {
      const state = await api("/api/agent/approval", {
        method: "POST",
        body: JSON.stringify({ connector_id: approval.dataset.connectorId, approved: approval.dataset.actionApproval === "true" }),
      });
      render(state, state);
    } catch (approvalError) {
      approval.parentElement.querySelectorAll("button").forEach((item) => { item.disabled = false; });
      byId("notice").textContent = approvalError.message;
      byId("notice").hidden = false;
    }
    return;
  }
  const button = event.target.closest("[data-connector-cancel]");
  if (!button || button.disabled) return;
  button.disabled = true;
  try {
    render(await api("/api/connectors/cancel", {
      method: "POST", body: JSON.stringify({ connector_id: button.dataset.connectorId }),
    }));
    byId("notice").textContent = "Setup cancelled. You can ask Cordia to connect it again whenever you’re ready.";
  } catch (error) {
    button.disabled = false;
    byId("notice").textContent = error.message;
  }
  byId("notice").hidden = false;
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
  const restore = event.target.closest("[data-artifacts-restore]");
  if (restore) {
    hiddenArtifactIds.clear();
    saveHiddenArtifacts();
    renderArtifacts(currentState.artifacts || []);
    return;
  }
  const hide = event.target.closest("[data-artifact-hide]");
  if (hide) {
    hiddenArtifactIds.add(hide.dataset.artifactKey);
    saveHiddenArtifacts();
    renderArtifacts(currentState.artifacts || []);
    return;
  }
  const action = event.target.closest("[data-artifact-action]");
  if (action) {
    const actionStarter = action.dataset.actionId && action.dataset.connectorId
      ? { action_id: action.dataset.actionId, connector_id: action.dataset.connectorId }
      : null;
    await sendAgentMessage(action.dataset.prompt, {
      artifactId: action.dataset.artifactId,
      actionStarter,
    });
    return;
  }
  const refreshButton = event.target.closest("[data-artifact-refresh]");
  if (refreshButton) {
    await sendAgentMessage(`Refresh the ${refreshButton.dataset.artifactName} workspace window from its connected source.`, {
      artifactId: refreshButton.dataset.artifactId,
    });
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

byId("artifact-grid").addEventListener("submit", async (event) => {
  const form = event.target.closest("[data-artifact-prompt]");
  if (!form) return;
  event.preventDefault();
  const input = form.querySelector('[name="artifact_prompt"]');
  if (!input?.disabled) await sendAgentMessage(input.value, { input, artifactId: form.dataset.artifactId });
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

byId("workspace-settings").querySelector("[data-settings-close]").addEventListener("click", () => {
  byId("workspace-settings").close();
});

refresh();
