"""Deterministic, human-facing results derived from canonical Surveyor data."""

from __future__ import annotations

from cordia.onboarding import AXIS_GUIDANCE, AXIS_LABELS, CONTROL_LEVEL_LABELS


CONTROL_SCORES = {
    "suggest_actions_only": 0,
    "prepare_for_approval": 33,
    "perform_approved_actions": 67,
    "automate_low_risk": 100,
}
STATUS_LABELS = {
    "verified": "Connected",
    "needs_attention": "Needs attention",
    "setup_required": "Setup required",
    "planned": "Planned",
}
AUTH_LABELS = {
    "oauth2": "OAuth",
    "api_key": "API key",
    "remote_mcp": "Managed connection",
}
WORKFLOW_FIELDS = (
    ("Desired outcome", "outcome"),
    ("Success criteria", "success_criteria"),
    ("First workspace", "first_workspace"),
    ("Starting information", "inputs"),
    ("Expected output", "outputs"),
    ("Cadence", "cadence"),
    ("Approval boundaries", "approval_boundaries"),
)
AXIS_TITLES = {
    "context": "Context preference",
    "scope": "Scope preference",
    "directness": "Directness preference",
    "implementation": "Implementation preference",
}
PLOT_AXIS_FOR_OPERATOR = {
    "context": "y",
    "scope": "z",
    "directness": "y",
    "implementation": "x",
}
PLOT_AXIS_FOR_TRAIT = {
    "social_energy": "y",
    "interpersonal_sensitivity": "y",
    "order_follow_through": "x",
    "emotional_reactivity": "y",
    "imagination_abstraction": "z",
}


def _present(value) -> bool:
    return bool(value.strip()) if isinstance(value, str) else bool(value)


def delegation_score(discovery: dict, applications: list[dict]) -> dict:
    selections = [discovery["control_level"]]
    selections.extend(
        application["control_level"]
        for application in applications
        if application.get("control_level")
    )
    score = round(sum(CONTROL_SCORES[value] for value in selections) / len(selections))
    nearest = min(
        CONTROL_SCORES,
        key=lambda key: abs(CONTROL_SCORES[key] - score),
    )
    return {"score": score, "label": CONTROL_LEVEL_LABELS[nearest]}


def context_score(profile: dict) -> dict:
    value = profile["operator_axes"]["context"]
    return {
        "score": {-1: 0, 0: 50, 1: 100}[value],
        "label": AXIS_LABELS["context"][value],
    }


def breadth_score(discovery: dict, applications: list[dict]) -> dict:
    signals = (
        len(applications) > 1,
        _present(discovery.get("cadence")),
        _present(discovery.get("people_roles")),
        _present(discovery.get("source_locations")),
        len(discovery.get("environment", [])) > 1,
    )
    score = sum(signals) * 20
    if score < 40:
        label = "Single task"
    elif score < 80:
        label = "Connected workflow"
    else:
        label = "Multi-environment orchestration"
    return {"score": score, "label": label}


def _operator_score(value: int) -> int:
    return {-1: 0, 0: 50, 1: 100}[value]


def _axis(title: str, references: list[dict], labels: tuple[str, str, str]) -> dict:
    weight = sum(reference["weight"] for reference in references)
    score = round(sum(reference["score"] * reference["weight"] for reference in references) / weight)
    label = labels[0] if score < 40 else labels[1] if score < 70 else labels[2]
    return {"title": title, "score": score, "label": label, "references": references}


def plot_profile(discovery: dict, profile: dict, applications: list[dict]) -> dict:
    """Build explainable coordinates from normalized, structured Surveyor scores."""
    controls = delegation_score(discovery, applications)["score"]
    breadth = breadth_score(discovery, applications)["score"]
    axes = profile["operator_axes"]
    traits = profile["traits"]
    return {
        "x": _axis(
            "Execution autonomy",
            [
                {"title": "Requested control", "score": controls, "weight": 2},
                {"title": "Implementation preference", "score": _operator_score(axes["implementation"]), "weight": 1},
                {"title": "Order and follow-through", "score": round(traits["order_follow_through"] * 10), "weight": 1},
            ],
            ("Guided support", "Shared execution", "Agent-led execution"),
        ),
        "y": _axis(
            "Communication context",
            [
                {"title": "Context preference", "score": _operator_score(axes["context"]), "weight": 2},
                {"title": "Directness preference", "score": _operator_score(axes["directness"]), "weight": 1},
                {"title": "Social energy", "score": round(traits["social_energy"] * 10), "weight": 1},
                {"title": "Interpersonal sensitivity", "score": round(traits["interpersonal_sensitivity"] * 10), "weight": 1},
                {"title": "Emotional steadiness", "score": round((10 - traits["emotional_reactivity"]) * 10), "weight": 1},
            ],
            ("Literal communication", "Balanced collaboration", "High-context collaboration"),
        ),
        "z": _axis(
            "Workflow complexity",
            [
                {"title": "Workflow breadth", "score": breadth, "weight": 2},
                {"title": "Scope preference", "score": _operator_score(axes["scope"]), "weight": 1},
                {"title": "Imagination and abstraction", "score": round(traits["imagination_abstraction"] * 10), "weight": 1},
            ],
            ("Focused task", "Connected workflow", "Systems orchestration"),
        ),
    }


def _direct_findings(discovery: dict, profile: dict) -> list[dict]:
    findings = []
    for axis in ("context", "scope", "directness", "implementation"):
        value = profile["operator_axes"][axis]
        findings.append(
            {
                "title": AXIS_TITLES[axis],
                "statement": AXIS_LABELS[axis][value],
                "detail": AXIS_GUIDANCE[axis][value],
                "plot_axis": PLOT_AXIS_FOR_OPERATOR[axis],
                "plot_role": "scored",
            }
        )
    for trait, score in profile["traits"].items():
        findings.append(
            {
                "title": trait.replace("_", " ").capitalize(),
                "statement": f"{score:.1f}/10",
                "detail": "Survey-derived description, not a diagnosis.",
                "plot_axis": PLOT_AXIS_FOR_TRAIT[trait],
                "plot_role": "scored",
            }
        )
    for domain in profile["domains"]:
        findings.append(
            {
                "title": domain["label"],
                "statement": f"Self-rating {domain['rating']}/5",
                "detail": domain["expertise_confidence"],
                "plot_axis": "y",
                "plot_role": "reference",
            }
        )
    for title, field in WORKFLOW_FIELDS:
        if _present(discovery.get(field)):
            findings.append({
                "title": title,
                "statement": discovery[field],
                "plot_axis": "x" if field == "approval_boundaries" else "z",
                "plot_role": "reference",
            })
    findings.append(
        {
            "title": "Requested control",
            "statement": CONTROL_LEVEL_LABELS[discovery["control_level"]],
            "detail": "This is a preference, not authorization already granted.",
            "plot_axis": "x",
            "plot_role": "scored",
        }
    )
    return findings


def _connector_setup_note(status: str, auth_kind: str | None) -> str:
    if status == "verified":
        return "The existing connection is verified."
    if status == "needs_attention":
        return "The existing connection needs provider attention or reauthorization."
    if status == "planned":
        return "This application is not yet available in the provider catalog."
    if auth_kind == "oauth2":
        return "Application sign-in and provider permission approval will be required."
    if auth_kind == "api_key":
        return "A scoped API key will be required and must not be placed in chat."
    if auth_kind == "remote_mcp":
        return "A managed provider connection will be required."
    return "Setup requirements are not yet known."


def _connector_plan(application: dict) -> dict:
    status = application.get("status", "planned")
    auth_kind = application.get("auth_kind")
    return {
        "name": application["name"],
        "status": STATUS_LABELS.get(status, "Planned"),
        "auth_method": AUTH_LABELS.get(auth_kind, "Not known yet"),
        "current_activities": application.get("current_activities", ""),
        "desired_activities": application.get("desired_activities", ""),
        "inputs_outputs": application.get("inputs_outputs", ""),
        "control": CONTROL_LEVEL_LABELS[application["control_level"]],
        "setup_note": _connector_setup_note(status, auth_kind),
    }


def _finding(
    title: str,
    statement: str,
    evidence: list[str],
    confidence: str,
    behavior: str,
) -> dict:
    return {
        "title": title,
        "statement": statement,
        "evidence": evidence,
        "confidence": confidence,
        "cordia_behavior": behavior,
    }


def _indirect_findings(
    discovery: dict, profile: dict, applications: list[dict]
) -> list[dict]:
    axes = profile["operator_axes"]
    findings = []

    if axes["context"] == 1 and axes["implementation"] == 1:
        findings.append(
            _finding(
                "Concise, context-aware execution",
                "Cordia should act first, keep replies brief, and label consequential assumptions.",
                [AXIS_LABELS["context"][1], AXIS_LABELS["implementation"][1]],
                "high",
                "Return the result first; ask only when a missing fact changes the action.",
            )
        )
    if axes["context"] == -1 and axes["scope"] == -1:
        findings.append(
            _finding(
                "Explicit requirements before expansion",
                "Cordia should stay inside the stated request until important missing requirements are resolved.",
                [AXIS_LABELS["context"][-1], AXIS_LABELS["scope"][-1]],
                "high",
                "Ask about consequential gaps before broadening the task.",
            )
        )
    if axes["directness"] == 1 and axes["implementation"] == 1:
        findings.append(
            _finding(
                "Direct result-first replies",
                "Cordia should state completed work or blockers plainly without padded explanation.",
                [AXIS_LABELS["directness"][1], AXIS_LABELS["implementation"][1]],
                "high",
                "Lead with the result and include rationale only when it helps the decision.",
            )
        )
    if axes["implementation"] == -1:
        findings.append(
            _finding(
                "Reasoning before recommendation",
                "Cordia should explain the basis for a recommendation before giving the next step.",
                [AXIS_LABELS["implementation"][-1], AXIS_LABELS["directness"][axes["directness"]]],
                "high",
                "Present concise reasoning first while matching the selected tone.",
            )
        )

    action_control = discovery["control_level"] == "automate_low_risk"
    if action_control and _present(discovery.get("sensitive_data")):
        findings.append(
            _finding(
                "Guarded automation",
                "Automation should stop before sensitive or externally consequential actions.",
                [
                    CONTROL_LEVEL_LABELS["automate_low_risk"],
                    "Sensitive data: " + ", ".join(discovery["sensitive_data"]),
                ],
                "high",
                "Automate low-risk steps and request approval before sensitive consequences.",
            )
        )
    if len(applications) > 1 and _present(discovery.get("source_locations")):
        findings.append(
            _finding(
                "Cross-application handoffs",
                "The requested workspace crosses application and source boundaries.",
                [f"{len(applications)} selected applications", "Source locations provided"],
                "high",
                "Verify identity, permissions, and data shape at each handoff.",
            )
        )
    if _present(discovery.get("cadence")) and not _present(discovery.get("failure_behavior")):
        findings.append(
            _finding(
                "Recovery rule needed",
                "Recurring execution needs an explicit response to failure.",
                ["Cadence provided", "Failure behavior not provided"],
                "high",
                "Do not start recurring execution until a recovery rule is confirmed.",
            )
        )
    for application in applications:
        if application.get("status") == "planned":
            findings.append(
                _finding(
                    f"{application['name']} catalog gap",
                    "This is a catalog implementation gap, not evidence of a connection failure.",
                    ["Status: Planned", "Registry entry: unavailable"],
                    "high",
                    "Keep the application in the build plan without claiming it is connected.",
                )
            )
        elif application.get("status") == "setup_required" and application.get("auth_kind"):
            findings.append(
                _finding(
                    f"{application['name']} authorization boundary",
                    "This application has a known setup step; that does not indicate provider unreliability.",
                    ["Status: Setup required", f"Authentication: {AUTH_LABELS.get(application['auth_kind'], 'Declared')}"],
                    "high",
                    "Pause only for the declared credential or approval step.",
                )
            )
    if _present(discovery.get("sensitive_data")) and _present(discovery.get("environment")):
        findings.append(
            _finding(
                "Data and environment boundary",
                "The named data categories and operating environments constrain the workspace design.",
                [
                    "Sensitive data: " + ", ".join(discovery["sensitive_data"]),
                    "Environments: " + ", ".join(discovery["environment"]),
                ],
                "high",
                "Preserve the stated handling and environment policies during every action.",
            )
        )
    return findings


def _unknowns(discovery: dict, applications: list[dict]) -> list[dict]:
    unknowns = []
    if (
        discovery["control_level"] == "automate_low_risk"
        or _present(discovery.get("cadence"))
    ) and not _present(discovery.get("failure_behavior")):
        unknowns.append(
            {
                "title": "Failure recovery",
                "statement": "Not enough evidence to choose what Cordia should do after a failed automation.",
            }
        )
    if discovery["control_level"] in {"perform_approved_actions", "automate_low_risk"} and not _present(discovery.get("approval_boundaries")):
        unknowns.append(
            {
                "title": "Approval boundaries",
                "statement": "Not enough evidence to decide which consequential actions require approval.",
            }
        )
    if _present(discovery.get("sensitive_data")) and not _present(discovery.get("sensitive_data_details")):
        unknowns.append(
            {
                "title": "Sensitive-data handling",
                "statement": "Not enough evidence to choose handling rules for the selected sensitive data.",
            }
        )
    for application in applications:
        if application.get("status") == "planned" and not application.get("auth_kind"):
            unknowns.append(
                {
                    "title": f"{application['name']} setup",
                    "statement": "Not enough evidence to determine this application's authentication requirements.",
                }
            )
    return unknowns


def build_survey_results(
    stages: dict, profile: dict, applications: list[dict]
) -> dict:
    discovery = stages["workspace_discovery"]["answers"]
    return {
        "status": {
            "label": "Workspace coming soon",
            "detail": "Your profile and workspace plan are saved.",
        },
        "plot": plot_profile(discovery, profile, applications),
        "direct_findings": _direct_findings(discovery, profile),
        "connector_plans": [_connector_plan(application) for application in applications],
        "indirect_findings": _indirect_findings(discovery, profile, applications),
        "unknowns": _unknowns(discovery, applications),
    }
