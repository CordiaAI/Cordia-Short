window.CordiaOnboarding = (() => {
  const stages = ["assessment_part_1", "assessment_part_2", "assessment_part_3", "assessment_part_4", "profile_snapshot", "workspace_discovery", "workspace_review"];
  const statusLabels = { requested: "Requested", setup_required: "Setup required", planned: "Planned", verified: "Verified", needs_attention: "Needs attention" };
  const copy = (value) => JSON.parse(JSON.stringify(value));

  function createController({ root, api, onComplete }) {
    const document = root.ownerDocument;
    const get = (id) => root.querySelector(`#onboarding-${id}`);
    const form = get("form"), fields = get("fields"), error = get("error");
    let onboarding = null, viewedStage = null, drafts = {}, busy = false;

    function node(tag, text, className) {
      const element = document.createElement(tag);
      if (text !== undefined) element.textContent = text;
      if (className) element.className = className;
      return element;
    }

    function question(parent, id, label) {
      const group = node("fieldset", undefined, "onboarding-question");
      group.setAttribute("data-field", id);
      group.append(node("legend", label));
      parent.append(group);
      return group;
    }

    function choices(parent, id, label, options, initial, change, { multiple = false, compact = false } = {}) {
      const group = question(parent, id, label);
      const row = node("div", undefined, compact ? "onboarding-choices compact" : "onboarding-choices");
      let selection = initial;
      const controls = options.map((option) => {
        const value = typeof option === "object" ? option.id : option;
        const label = typeof option === "object" ? option.label : String(option);
        const button = node("button", compact && typeof value === "number" ? String(value) : label);
        button.type = "button";
        button.setAttribute("data-value", value);
        button.setAttribute("aria-label", label);
        button.addEventListener("click", () => {
          if (busy) return;
          error.textContent = "";
          const next = multiple
            ? (selection || []).includes(value) ? selection.filter((item) => item !== value) : [...(selection || []), value]
            : value;
          if (change(next) === false) return;
          selection = next;
          update();
          updateContinue();
        });
        row.append(button);
        return { button, value };
      });
      function update() {
        for (const { button, value } of controls) button.setAttribute("aria-pressed", String(multiple ? (selection || []).includes(value) : selection === value));
      }
      update();
      group.append(row);
      return group;
    }

    function textField(parent, id, label, value, change, { required = false, maxLength = 4000, singleLine = false } = {}) {
      const group = node("div", undefined, "onboarding-question");
      group.setAttribute("data-field", id);
      const caption = node("label", `${label}${required ? " (required)" : " (optional)"}`);
      const input = node(singleLine ? "input" : "textarea");
      input.id = `onboarding-input-${id}`;
      input.setAttribute("name", id);
      caption.setAttribute("for", input.id);
      input.value = value || "";
      input.required = required;
      input.maxLength = maxLength;
      if (singleLine) input.type = "text";
      else input.rows = 4;
      input.addEventListener("input", () => { if (!busy) { change(input.value); updateContinue(); } });
      group.append(caption, input);
      parent.append(group);
      return { group, input };
    }

    function partOne(schema, draft) {
      draft.answers ||= {};
      fields.append(node("p", "1 = Very Inaccurate · 5 = Very Accurate", "onboarding-help"));
      schema.questions.forEach((item, index) => choices(fields, item.id, `${index + 1}. ${item.prompt}`, schema.rating_options, draft.answers[item.id], (value) => { draft.answers[item.id] = value; }, { compact: true }));
    }

    function partTwo(schema, draft) {
      draft.domains ||= []; draft.ratings ||= {}; draft.familiarity ||= {};
      const details = node("div");
      choices(fields, "domains", "Your domains — select 1–2", Object.entries(schema.domains).map(([id, value]) => ({ id, label: value.label })), draft.domains, (selected) => {
        if (selected.length > schema.domain_limit.maximum) { error.textContent = "Select no more than 2 domains. Deselect one to choose another."; return false; }
        draft.domains = selected;
        for (const domain of Object.keys(draft.ratings)) if (!selected.includes(domain)) delete draft.ratings[domain];
        for (const domain of Object.keys(draft.familiarity)) if (!selected.includes(domain)) delete draft.familiarity[domain];
        renderDetails();
      }, { multiple: true });
      fields.append(details);
      function renderDetails() {
        details.replaceChildren();
        for (const id of draft.domains) {
          const domain = schema.domains[id];
          draft.familiarity[id] ||= {};
          choices(details, `rating:${id}`, `How would you rate your knowledge of ${domain.label}? (1 = beginner, 5 = expert)`, [1, 2, 3, 4, 5], draft.ratings[id], (value) => { draft.ratings[id] = value; }, { compact: true });
          for (const term of domain.terms) choices(details, `${id}:${term}`, term, [{ id: "familiar", label: "Familiar" }, { id: "not_familiar", label: "Not familiar" }], draft.familiarity[id][term], (value) => { draft.familiarity[id][term] = value; });
        }
      }
      renderDetails();
    }

    function partThree(schema, draft) {
      for (const item of schema.questions) {
        if (item.distinct_selection) {
          const section = node("section", undefined, "onboarding-pair");
          section.append(node("h2", item.prompt));
          for (const key of ["most", "least"]) choices(section, key, key.toUpperCase(), item.options, draft[key], (value) => {
            if (value === draft[key === "most" ? "least" : "most"]) { error.textContent = "MOST and LEAST must be different."; return false; }
            draft[key] = value;
          });
          fields.append(section);
        } else choices(fields, item.id, item.prompt, item.options, draft[item.id], (value) => { draft[item.id] = value; });
      }
    }

    function partFour(schema, draft) {
      for (const field of schema.fields) textField(fields, field.id, field.label, draft[field.id], (value) => { draft[field.id] = value; }, { required: field.required, maxLength: field.max_length });
    }

    function snapshot() {
      const profile = onboarding.profile;
      fields.append(node("p", "A descriptive starting point for how Cordia interprets your requests. This is not a diagnosis and does not grant permission to act.", "onboarding-summary"));
      const traits = node("section", undefined, "onboarding-question");
      traits.append(node("h2", "Your profile"));
      const labels = { social_energy: "Social energy", interpersonal_sensitivity: "Interpersonal sensitivity", order_follow_through: "Order & follow-through", emotional_reactivity: "Emotional reactivity", imagination_abstraction: "Imagination & abstraction" };
      for (const [key, value] of Object.entries(profile.traits)) {
        const row = node("div", undefined, "onboarding-trait");
        const caption = node("label", labels[key] || key);
        const meter = node("meter");
        meter.id = `trait-${key}`; meter.min = 0; meter.max = 10; meter.value = value;
        caption.setAttribute("for", meter.id);
        row.append(caption, meter, node("span", `${Number(value).toFixed(1)}/10`));
        traits.append(row);
      }
      fields.append(traits);
      const axes = { context: ["Context interpretation", "Explicit / literal", "Balanced", "Implicit / high-context"], scope: ["Scope preference", "Detail-first", "Balanced", "Big-picture"], directness: ["Directness preference", "Measured / indirect", "Balanced", "Direct"] };
      const axisSection = node("section", undefined, "onboarding-question");
      axisSection.append(node("h2", "How Cordia will communicate"));
      for (const [key, labels] of Object.entries(axes)) {
        const row = node("div", undefined, "onboarding-axis");
        row.setAttribute("data-axis", key);
        row.append(node("strong", labels[0]), node("span", labels[Number(profile.operator_axes[key]) + 2]));
        axisSection.append(row);
      }
      fields.append(axisSection);
      for (const domain of profile.domains) fields.append(node("p", `${domain.label}: self-rating ${domain.rating}/5. ${domain.expertise_confidence}.`, "onboarding-help"));
    }

    function conditionMatches(rule, draft) {
      const value = draft[rule.field];
      if (rule.test === "present") return typeof value === "string" ? Boolean(value.trim()) : Array.isArray(value) && value.length > 0;
      if (rule.test === "one_of") return (Array.isArray(value) ? value : [value]).some((item) => rule.values.includes(item));
      if (rule.test === "contains_any") {
        const text = rule.fields.map((key) => typeof draft[key] === "string" ? draft[key] : "").join(" ").toLowerCase();
        return rule.values.some((word) => text.includes(word));
      }
      return false;
    }

    function activeCondition(metadata, draft) {
      return (metadata.when_any || []).some((rule) => conditionMatches(rule, draft));
    }

    function applicationPicker(schema, draft) {
      draft.applications ||= [];
      const group = question(fields, "applications", "Which applications are involved? (required)");
      group.append(node("p", "Select the tools involved in this workflow. Selection is planning only; connections are set up later. Do not enter passwords or API keys.", "onboarding-help"));
      const { input } = textField(group, "application_search", "Search applications or type a name to add", "", renderResults, { singleLine: true, maxLength: 400 });
      const results = node("div", undefined, "onboarding-application-results");
      results.setAttribute("data-application-results", "");
      const manual = node("button", "Add this application", "quiet-button");
      manual.type = "button"; manual.setAttribute("data-add-manual", "");
      manual.addEventListener("click", () => addApplication(null, input.value.trim()));
      const selected = node("div", undefined, "onboarding-selected-apps");
      group.append(results, manual, selected);
      const controlOptions = schema.fields.find((field) => field.id === "control_level").options;

      function addApplication(id, name) {
        if (busy || !name) return;
        if (draft.applications.length >= 20) { error.textContent = "Select no more than 20 applications."; return; }
        const known = onboarding.application_catalog.find((item) => item.id === id || item.name.toLowerCase() === name.toLowerCase());
        if (draft.applications.some((item) => (known && item.application_id === known.id) || item.name.toLowerCase() === name.toLowerCase())) { error.textContent = "That application is already selected."; return; }
        draft.applications.push({ application_id: known?.id || null, name: known?.name || name, already_uses: false, wants_added: true, current_activities: "", desired_activities: "", inputs_outputs: "", control_level: "suggest_actions_only" });
        input.value = "";
        error.textContent = "";
        renderResults(); renderSelected();
        updateContinue();
        selected.querySelectorAll("textarea")[draft.applications.length * 3 - 3]?.focus();
      }

      function renderResults() {
        results.replaceChildren();
        const search = input.value.trim().toLowerCase();
        const matches = onboarding.application_catalog.filter((item) => item.name.toLowerCase().includes(search) || item.id.toLowerCase().includes(search));
        for (const item of matches) {
          const button = node("button", item.name);
          button.type = "button";
          button.disabled = draft.applications.some((application) => application.application_id === item.id);
          button.setAttribute("aria-pressed", String(button.disabled));
          button.addEventListener("click", () => addApplication(item.id, item.name));
          results.append(button);
        }
        if (!matches.length) results.append(node("p", "No matching supported application. Add the name below to record it as planned.", "onboarding-help"));
        manual.hidden = !search;
      }

      function renderSelected() {
        selected.replaceChildren();
        draft.applications.forEach((application, index) => {
          const card = node("section", undefined, "onboarding-application");
          const heading = node("div", undefined, "onboarding-application-heading");
          const remove = node("button", "Remove", "quiet-button");
          remove.type = "button";
          remove.setAttribute("aria-label", `Remove ${application.name}`);
          remove.addEventListener("click", () => { if (busy) return; draft.applications.splice(index, 1); renderSelected(); renderResults(); updateContinue(); input.focus(); });
          heading.append(node("h3", application.name), remove);
          card.append(heading);
          choices(card, `application-${index}-use`, "How does this application fit? Select one or both.", [{ id: "already_uses", label: "I already use it" }, { id: "wants_added", label: "I want it added" }], ["already_uses", "wants_added"].filter((key) => application[key]), (values) => {
            if (!values.length) { error.textContent = "Choose already used, wanted, or both."; return false; }
            application.already_uses = values.includes("already_uses"); application.wants_added = values.includes("wants_added");
          }, { multiple: true });
          for (const [key, label] of [["current_activities", "What do you currently do here? If it is new, say so."], ["desired_activities", "What would you like Cordia to do here?"], ["inputs_outputs", "What inputs and outputs are involved?"]]) textField(card, `application-${index}-${key}`, label, application[key], (value) => { application[key] = value; }, { required: true });
          choices(card, `application-${index}-control_level`, "Requested control level", controlOptions, application.control_level, (value) => { application.control_level = value; });
          selected.append(card);
        });
      }
      renderResults(); renderSelected();
    }

    function discovery(schema, draft) {
      const conditionalGroups = {};
      let firstEdited = Boolean(draft.first_workspace);
      const suggestion = () => draft.outputs?.trim() || draft.outcome?.trim() || "";
      if (!firstEdited) draft.first_workspace = suggestion();
      fields.append(node("p", "Start with one useful result. Your answers form a proposed workspace plan; no application is connected or authorized here.", "onboarding-summary"));
      const updateConditions = () => {
        for (const [id, group] of Object.entries(conditionalGroups)) group.hidden = !activeCondition(schema.conditional_fields[id], draft);
      };
      for (const field of schema.fields) {
        if (field.id === "applications") { applicationPicker(schema, draft); continue; }
        if (field.options) {
          choices(fields, field.id, `${field.label} (required)`, field.options, draft[field.id], (value) => { draft[field.id] = value; updateConditions(); });
          continue;
        }
        textField(fields, field.id, field.label, draft[field.id], (value) => {
          draft[field.id] = value;
          if (field.id === "first_workspace") firstEdited = true;
          if (!firstEdited && ["outputs", "outcome"].includes(field.id)) {
            draft.first_workspace = suggestion();
            const firstInput = fields.querySelector('[name="first_workspace"]');
            if (firstInput) firstInput.value = draft.first_workspace;
          }
          updateConditions();
        }, { required: field.required });
        if (field.id === "first_workspace") fields.append(node("p", "Suggested from your output or outcome. Edit it to the smallest useful first step.", "onboarding-help"));
      }
      fields.append(node("h2", "Workflow context"), node("p", "Select any relevant data categories and environments. Follow-up details are optional; leave them blank if unknown.", "onboarding-help"));
      for (const [id, metadata] of Object.entries(schema.conditional_fields)) {
        if (metadata.options) choices(fields, id, metadata.label, metadata.options, draft[id] || [], (values) => { draft[id] = values; updateConditions(); }, { multiple: true });
      }
      for (const [id, metadata] of Object.entries(schema.conditional_fields)) {
        if (metadata.options) continue;
        conditionalGroups[id] = textField(fields, id, metadata.label, draft[id], (value) => { draft[id] = value; }).group;
      }
      updateConditions();
    }

    function review() {
      const discovery = onboarding.review.workspace_discovery;
      const controls = onboarding.stage_schemas.workspace_discovery.fields.find((field) => field.id === "control_level").options;
      fields.append(node("p", "Review the proposed first workspace. Building saves your profile and plan; it does not connect applications or run the proposed work.", "onboarding-summary"));
      for (const [label, value] of [["Desired outcome", discovery.outcome], ["Success criteria", discovery.success_criteria], ["First workspace slice", discovery.first_workspace], ["Expected output", discovery.outputs], ["Approval boundary", controls.find((option) => option.id === discovery.control_level)?.label], ["Additional approval boundaries", discovery.approval_boundaries]]) {
        if (!value) continue;
        const section = node("section", undefined, "onboarding-question");
        section.append(node("h2", label), node("p", value));
        fields.append(section);
      }
      const apps = node("section", undefined, "onboarding-question");
      apps.append(node("h2", "Selected applications"));
      for (const application of onboarding.review.selected_applications || onboarding.selected_applications || []) {
        const row = node("div", undefined, "selected-application-row");
        row.append(node("strong", application.name), node("span", statusLabels[application.status] || "Requested", "application-status"));
        apps.append(row);
      }
      apps.append(node("p", "Setup required: supported connector, not connected. Planned: implementation is still needed. Only verified provider checks can establish a connection.", "onboarding-help"));
      fields.append(apps);
    }

    function serialize() {
      const draft = drafts[viewedStage];
      if (viewedStage !== "workspace_discovery") return copy(draft);
      const schema = onboarding.stage_schemas.workspace_discovery;
      const payload = Object.fromEntries(schema.fields.map((field) => [field.id, draft[field.id]]));
      for (const [id, metadata] of Object.entries(schema.conditional_fields)) {
        if (metadata.options) payload[id] = draft[id] || [];
        else if (activeCondition(metadata, draft) && typeof draft[id] === "string" && draft[id].trim()) payload[id] = draft[id];
      }
      return payload;
    }

    function previousStage() {
      return stages.slice(0, stages.indexOf(viewedStage)).reverse().find((stage) => onboarding.completed_stages.includes(stage) || (stage === "profile_snapshot" && onboarding.profile));
    }

    function draftValid() {
      const schema = onboarding.stage_schemas[viewedStage], draft = drafts[viewedStage];
      if (schema.computed) return true;
      const choice = (value, options) => options.some((option) => (typeof option === "object" ? option.id : option) === value);
      const text = (value, required = true, maximum = 4000) => {
        if (value === undefined && !required) return true;
        return typeof value === "string" && (!required || Boolean(value.trim())) && value.trim().length <= maximum;
      };
      if (viewedStage === "assessment_part_1") return schema.questions.every((item) => choice(draft.answers?.[item.id], item.options));
      if (viewedStage === "assessment_part_2") {
        const domains = draft.domains || [];
        return domains.length >= schema.domain_limit.minimum && domains.length <= schema.domain_limit.maximum && domains.every((id) => {
          const domain = schema.domains[id];
          return domain && choice(draft.ratings?.[id], onboarding.stage_schemas.assessment_part_1.rating_options)
            && domain.terms.every((term) => ["familiar", "not_familiar"].includes(draft.familiarity?.[id]?.[term]));
        });
      }
      if (viewedStage === "assessment_part_3") return schema.questions.every((item) => item.distinct_selection
        ? choice(draft.most, item.options) && choice(draft.least, item.options) && draft.most !== draft.least
        : choice(draft[item.id], item.options));
      const coreValid = schema.fields.every((field) => {
        if (field.id === "applications") {
          const applications = draft.applications || [];
          const controlOptions = schema.fields.find((item) => item.id === "control_level").options;
          return applications.length > 0 && applications.length <= 20 && applications.every((app) =>
            text(app.name, true, 400) && (app.already_uses || app.wants_added)
            && ["current_activities", "desired_activities", "inputs_outputs"].every((key) => text(app[key]))
            && choice(app.control_level, controlOptions));
        }
        return field.options ? choice(draft[field.id], field.options) : text(draft[field.id], field.required, field.max_length || 4000);
      });
      return coreValid && Object.entries(schema.conditional_fields || {}).every(([id, metadata]) => metadata.options
        ? (draft[id] || []).every((value) => choice(value, metadata.options))
        : !activeCondition(metadata, draft) || text(draft[id], false));
    }

    function updateContinue() {
      get("continue").disabled = busy || !draftValid();
    }

    function renderCurrentStage() {
      const schema = onboarding.stage_schemas[viewedStage];
      fields.replaceChildren(); error.textContent = "";
      get("title").textContent = schema.title;
      get("instructions").textContent = schema.instructions || "";
      get("progress").textContent = `SURVEYOR · STEP ${stages.indexOf(viewedStage) + 1} OF ${stages.length}`;
      get("continue").textContent = viewedStage === "workspace_review" ? "Build my workspace" : "CONTINUE";
      get("back").disabled = !previousStage();
      const draft = drafts[viewedStage] ||= copy(onboarding.answers[viewedStage] || {});
      const renderers = { assessment_part_1: partOne, assessment_part_2: partTwo, assessment_part_3: partThree, assessment_part_4: partFour, profile_snapshot: snapshot, workspace_discovery: discovery, workspace_review: review };
      renderers[viewedStage](schema, draft);
      updateContinue();
      root.scrollTo({ top: 0 });
      get("title").focus();
    }

    function setBusy(value) {
      busy = value;
      form.setAttribute("aria-busy", String(value));
      // Freeze inputs too, so typing during a save cannot silently discard edits.
      fields.querySelectorAll("input, textarea, button").forEach((control) => {
        if (value) { control.wasDisabled = control.disabled; control.disabled = true; }
        else { control.disabled = Boolean(control.wasDisabled); }
      });
      updateContinue();
      get("back").disabled = value || !previousStage();
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (busy || !draftValid()) return;
      error.textContent = "";
      if (viewedStage === "profile_snapshot") { viewedStage = "workspace_discovery"; renderCurrentStage(); return; }
      setBusy(true);
      try {
        if (viewedStage === "workspace_review") {
          const state = await api("/api/onboarding/complete", { method: "POST", body: "{}" });
          if (state.state !== "workspace") throw new Error("Your workspace is not complete yet. Please review and try again.");
          onComplete(state);
        } else {
          const savedStage = viewedStage;
          const response = await api(`/api/onboarding/${savedStage}`, { method: "PUT", body: JSON.stringify(serialize()) });
          onboarding = response.onboarding;
          delete drafts[savedStage];
          viewedStage = stages[stages.indexOf(savedStage) + 1];
          // A server save re-scores computed screens; Back never writes a stage.
          renderCurrentStage();
        }
      } catch (failure) { error.textContent = failure.message || "Unable to save. Your answers are still here."; }
      finally { setBusy(false); }
    });

    get("back").addEventListener("click", () => {
      if (busy) return;
      const previous = previousStage();
      if (previous) { viewedStage = previous; renderCurrentStage(); }
    });

    async function show(state) {
      onboarding = state || (await api("/api/onboarding")).onboarding;
      viewedStage = onboarding.current_stage;
      drafts = {};
      root.hidden = false;
      renderCurrentStage();
    }

    function hide() { root.hidden = true; }
    return { show, hide };
  }

  return { createController };
})();
