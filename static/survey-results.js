(function surveyResultsModule() {
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function card(title, className = "") {
    const container = element("article", `results-card ${className}`.trim());
    container.append(element("h2", "results-card-title", title));
    return container;
  }

  function definition(list, term, description) {
    const row = element("div", "results-definition");
    row.append(element("dt", "", term), element("dd", "", description));
    list.append(row);
  }

  function drawPlot(canvas, plot) {
    const context = canvas.getContext("2d");
    if (!context) return;
    const origin = { x: 74, y: 244 };
    const x = origin.x + (plot.x.score / 100) * 330;
    const y = origin.y - (plot.y.score / 100) * 175;
    const zOffset = (plot.z.score / 100) * 54;
    const point = { x: x + zOffset, y: y - zOffset * 0.55 };

    context.clearRect(0, 0, canvas.width, canvas.height);
    context.strokeStyle = "#bbbdb7";
    context.fillStyle = "#6e6e6e";
    context.lineWidth = 1.5;
    context.font = "12px Inter, sans-serif";
    const axes = [
      { x: 438, y: 244, label: "X · Execution" },
      { x: 74, y: 42, label: "Y · Context" },
      { x: 142, y: 205, label: "Z · Complexity" },
    ];
    for (const axis of axes) {
      context.beginPath();
      context.moveTo(origin.x, origin.y);
      context.lineTo(axis.x, axis.y);
      context.stroke();
      context.fillText(axis.label, axis.x - 16, axis.y - 10);
    }
    context.fillStyle = "#4a5a42";
    context.beginPath();
    context.arc(point.x, point.y, 8, 0, Math.PI * 2);
    context.fill();
  }

  function renderPlot(plot) {
    const container = card("Your AI working style", "results-plot-card results-span-2");
    if (!plot) {
      container.append(element("p", "results-muted", "The plot could not be displayed safely."));
      return container;
    }
    const canvas = element("canvas", "results-plot");
    canvas.width = 520;
    canvas.height = 300;
    canvas.setAttribute("role", "img");
    canvas.setAttribute(
      "aria-label",
      `Execution autonomy ${plot.x.score} of 100, communication context ${plot.y.score} of 100, workflow complexity ${plot.z.score} of 100.`,
    );
    drawPlot(canvas, plot);
    container.append(canvas);

    const coordinates = element("dl", "results-coordinate-list");
    for (const key of ["x", "y", "z"]) {
      const axis = plot[key];
      definition(coordinates, `${key.toUpperCase()} · ${axis.title}`, `${axis.score}/100 · ${axis.label}`);
    }
    const references = element("div", "results-axis-references");
    for (const key of ["x", "y", "z"]) {
      const axis = plot[key];
      const group = element("section", "results-axis-reference");
      group.append(element("h3", "", `${key.toUpperCase()} score inputs`));
      for (const reference of axis.references || []) {
        group.append(element(
          "p",
          "",
          `${reference.title} · ${reference.score}/100 · ${reference.weight}× weight`,
        ));
      }
      references.append(group);
    }
    container.append(coordinates, references);
    return container;
  }

  function renderDirectFindings(findings) {
    const container = card("What your answers say", "results-answers-card");
    const list = element("ul", "results-finding-list");
    for (const finding of findings || []) {
      const item = element("li", "results-finding");
      const heading = element("div", "results-finding-heading");
      heading.append(
        element("strong", "", finding.title),
        finding.plot_axis
          ? element(
              "span",
              "results-axis-chip",
              `${finding.plot_axis.toUpperCase()} ${finding.plot_role === "scored" ? "score" : "reference"}`,
            )
          : element("span"),
      );
      item.append(heading, element("p", "", finding.statement));
      if (finding.detail) {
        const details = element("details", "results-details");
        details.append(
          element("summary", "", "Why this matters"),
          element("p", "", finding.detail),
        );
        item.append(details);
      }
      list.append(item);
    }
    container.append(list);
    return container;
  }

  function connectorField(container, label, value) {
    if (!value) return;
    const row = element("p", "results-connector-field");
    row.append(element("strong", "", `${label}: `), element("span", "", value));
    container.append(row);
  }

  function renderConnectors(connectors) {
    const container = card("Your application plan", "results-connectors-card results-span-2");
    const intro = element(
      "p",
      "results-muted",
      "These are requested applications and setup facts, not promises that every connection is live.",
    );
    const grid = element("div", "results-connector-grid");
    for (const connector of connectors || []) {
      const item = element("section", "results-connector");
      const heading = element("div", "results-connector-heading");
      heading.append(
        element("h3", "", connector.name),
        element("span", "results-status-chip", connector.status),
      );
      item.append(heading);
      connectorField(item, "Connection", connector.auth_method);
      connectorField(item, "Used today", connector.current_activities);
      connectorField(item, "Cordia should help", connector.desired_activities);
      connectorField(item, "Information flow", connector.inputs_outputs);
      connectorField(item, "Requested control", connector.control);
      item.append(element("p", "results-setup-note", connector.setup_note));
      grid.append(item);
    }
    if (!(connectors || []).length) {
      grid.append(element("p", "results-muted", "No applications were selected."));
    }
    container.append(intro, grid);
    return container;
  }

  function renderInferences(findings) {
    const container = card("What Cordia can infer", "results-inferences-card results-span-3");
    const intro = element(
      "p",
      "results-muted",
      "Each conclusion below is tied to multiple structured answers.",
    );
    const list = element("div", "results-inference-list");
    for (const finding of findings || []) {
      const item = element("section", "results-inference");
      const heading = element("div", "results-inference-heading");
      heading.append(
        element("h3", "", finding.title),
        element("span", "results-confidence", `${finding.confidence} confidence`),
      );
      item.append(heading, element("p", "", finding.statement));
      const evidence = element("div", "results-evidence");
      for (const value of finding.evidence || []) {
        evidence.append(element("span", "results-chip", value));
      }
      item.append(evidence);
      const behavior = element("p", "results-behavior");
      behavior.append(
        element("strong", "", "Cordia behavior: "),
        element("span", "", finding.cordia_behavior),
      );
      item.append(behavior);
      list.append(item);
    }
    if (!(findings || []).length) {
      list.append(element("p", "results-muted", "No cross-answer findings were supported."));
    }
    container.append(intro, list);
    return container;
  }

  function renderUnknowns(unknowns) {
    const container = card("What Cordia still needs to learn", "results-unknowns");
    const list = element("ul", "results-unknown-list");
    for (const unknown of unknowns || []) {
      const item = element("li", "results-unknown");
      item.append(element("strong", "", unknown.title), element("p", "", unknown.statement));
      list.append(item);
    }
    if (!(unknowns || []).length) {
      list.append(element("li", "results-muted", "No consequential gaps were detected from the available structured answers."));
    }
    container.append(list);
    return container;
  }

  function render(root, results) {
    const hero = element("header", "results-hero");
    hero.append(
      element("p", "eyebrow", "YOUR CORDIA PROFILE"),
      element("h1", "", "How Cordia will work with you"),
      element("span", "results-coming-soon", results.status.label),
      element("p", "results-status", results.status.detail),
    );
    const grid = element("section", "results-grid");
    grid.append(
      renderPlot(results.plot),
      renderDirectFindings(results.direct_findings),
      renderConnectors(results.connector_plans),
      renderInferences(results.indirect_findings),
      renderUnknowns(results.unknowns),
    );
    root.replaceChildren(hero, grid);
  }

  function activate(surfaces, state) {
    if (state.state !== "results") return false;
    surfaces.auth.hidden = true;
    surfaces.onboarding.hidden = true;
    surfaces.workspace.hidden = true;
    surfaces.results.hidden = false;
    render(surfaces.results, state.survey_results);
    return true;
  }

  window.CordiaSurveyResults = { activate, render };
})();
