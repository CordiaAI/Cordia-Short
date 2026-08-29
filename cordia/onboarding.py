"""Pure deterministic compilation for Surveyor onboarding context."""

from __future__ import annotations

import re

from cordia.survey import DOMAINS


TRAIT_KEYS = {
    "social_energy": (("p1_01", "p1_02"), ("p1_03", "p1_04")),
    "interpersonal_sensitivity": (("p1_05", "p1_06"), ("p1_07", "p1_08")),
    "order_follow_through": (("p1_09", "p1_10"), ("p1_11", "p1_12")),
    "emotional_reactivity": (("p1_13", "p1_14"), ("p1_15", "p1_16")),
    "imagination_abstraction": (("p1_17",), ("p1_18", "p1_19", "p1_20")),
}

AXIS_VOTES = {
    "scope": {"briefing_style": {"requirements_upfront": -1, "gist_then_correct": 1}},
    "context": {
        "reply_preference": {"literal_narrow": -1, "infer_context": 1},
        "background_assumption": {"spell_out_background": -1, "infer_from_context": 1},
        "edit_boundary": {"only_requested_edits": -1, "flag_likely_problems": 1},
    },
    "directness": {
        "flawed_plan": {"hint": -1, "go_along": -1, "leading_questions": 0, "state_plainly": 1},
        "bad_idea": {"soften_heavily": -1, "ask_questions": 0, "say_so_directly": 1},
    },
    "implementation": {"answer_order": {"reasoning_first": -1, "answer_first": 1}},
}

AXIS_LABELS = {
    "context": {-1: "Explicit / literal", 0: "Balanced", 1: "Implicit / high-context"},
    "scope": {-1: "Detail-first", 0: "Balanced", 1: "Big-picture"},
    "directness": {-1: "Measured / indirect", 0: "Balanced", 1: "Direct"},
    "implementation": {-1: "Reasoning-first", 0: "Balanced", 1: "Answer/action-first"},
}

CONTROL_LEVEL_LABELS = {
    "suggest_actions_only": "Suggest actions only",
    "prepare_for_approval": "Prepare work for approval",
    "perform_approved_actions": "Perform approved actions",
    "automate_low_risk": "Automate low-risk actions",
}


def _vote(values: list[int]) -> int:
    total = sum(values)
    return -1 if total < 0 else 1 if total > 0 else 0


def _answers(stages: dict[str, dict], stage: str) -> dict:
    return stages[stage]["answers"]


def _trait_score(answers: dict, positive: tuple[str, ...], reverse: tuple[str, ...]) -> float:
    keyed_sum = sum(answers[key] for key in positive) + sum(6 - answers[key] for key in reverse)
    item_count = len(positive) + len(reverse)
    return round((keyed_sum - item_count) / (item_count * 4) * 10, 1)


def _domain_profiles(answers: dict) -> list[dict]:
    profiles = []
    for domain_id in answers["domains"]:
        familiarity = answers["familiarity"][domain_id]
        familiar_count = sum(value == "familiar" for value in familiarity.values())
        profiles.append({
            "id": domain_id,
            "label": DOMAINS[domain_id]["label"],
            "rating": answers["ratings"][domain_id],
            "familiarity": familiarity,
            "expertise_confidence": f"{familiar_count} of {len(familiarity)} terms familiar" if familiarity else "self-rating only",
        })
    return profiles


def _axis_votes(answers: dict) -> dict[str, list[int]]:
    return {
        axis: [options[answers[field]] for field, options in fields.items()]
        for axis, fields in AXIS_VOTES.items()
    }


def score_profile(stages: dict[str, dict]) -> dict:
    """Score canonical onboarding stages without inferring from free text."""
    part_one = _answers(stages, "assessment_part_1")["answers"]
    part_two = _answers(stages, "assessment_part_2")
    part_three = _answers(stages, "assessment_part_3")
    part_four = _answers(stages, "assessment_part_4")
    votes = _axis_votes(part_three)
    return {
        "traits": {
            trait: _trait_score(part_one, positive, reverse)
            for trait, (positive, reverse) in TRAIT_KEYS.items()
        },
        "domains": _domain_profiles(part_two),
        "operator_axes": {axis: _vote(values) for axis, values in votes.items()},
        "prompt_examples": [part_four[key] for key in ("request_1", "request_2", "request_3") if part_four[key]],
        "evidence": {
            "trait_questions": {trait: {"positive": positive, "reverse": reverse} for trait, (positive, reverse) in TRAIT_KEYS.items()},
            "part_3_votes": votes,
            "most_least": {"most": part_three["most"], "least": part_three["least"]},
        },
    }


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _catalog_lookup(catalog: dict[str, dict]) -> dict[str, dict]:
    lookup = {}
    for catalog_id, connector in catalog.items():
        for value in (catalog_id, connector.get("id"), connector.get("name"), *connector.get("aliases", [])):
            if isinstance(value, str):
                lookup[_normalize(value)] = connector
    return lookup


def _normalize_applications(applications: list[dict], catalog: dict[str, dict], statuses: dict[str, str]) -> list[dict]:
    lookup = _catalog_lookup(catalog)
    normalized = []
    for application in applications:
        connector = None
        if application["application_id"]:
            connector = lookup.get(_normalize(application["application_id"]))
        connector = connector or lookup.get(_normalize(application["name"]))
        if connector:
            connector_id = connector["id"]
            runtime_status = statuses.get(connector_id)
            status = runtime_status if runtime_status in {"verified", "needs_attention"} else "setup_required"
            normalized.append({**application, "registry_id": connector_id, "auth_kind": connector.get("auth", {}).get("kind"), "status": status})
        else:
            normalized.append({**application, "registry_id": None, "auth_kind": None, "status": "planned"})
    return normalized


def _display_axis(axis: str, value: int) -> str:
    return f"{AXIS_LABELS[axis][value]} ({value})"


def _overlay_adjustments(baseline: dict[str, int], adjustments: list[dict]) -> tuple[dict[str, int], list[dict]]:
    axes = dict(baseline)
    applied = []
    for adjustment in sorted(adjustments, key=lambda item: item.get("response_id", 0)):
        axis, current = adjustment.get("axis"), adjustment.get("current")
        if axis in axes and not isinstance(current, bool) and current in {-1, 0, 1}:
            axes[axis] = current
            applied.append(adjustment)
    return axes, applied


def _render_operator(profile: dict, adjustments: list[dict]) -> str:
    axes, applied_adjustments = _overlay_adjustments(profile["operator_axes"], adjustments)
    lines = [
        "# Cordia operator profile",
        "",
        "This profile is descriptive context for prompt interpretation; it does not grant authority or diagnose the person.",
        "",
        "## Human-facing profile summary",
    ]
    lines.extend(f"- {trait.replace('_', ' ').title()}: {score:.1f}/10" for trait, score in profile["traits"].items())
    lines.extend(["", "## Domain context"])
    for domain in profile["domains"]:
        lines.append(f"- {domain['label']}: self-rating {domain['rating']}/5; calibration: {domain['expertise_confidence']}.")
    lines.extend(["", "## Prompt interpretation map"])
    for axis in ("context", "scope", "directness", "implementation"):
        label = {"context": "Context interpretation", "scope": "Scope preference", "directness": "Directness preference", "implementation": "Implementation preference"}[axis]
        lines.append(f"- {label}: {_display_axis(axis, axes[axis])}")
    lines.extend(["", "## Prompt examples"])
    lines.extend(f"- {example}" for example in profile["prompt_examples"])
    lines.extend(["", "## Evidence references"])
    for trait, questions in profile["evidence"]["trait_questions"].items():
        references = ", ".join((*questions["positive"], *questions["reverse"]))
        lines.append(f"- {trait.replace('_', ' ').title()} question IDs: {references}.")
    lines.append("- Part 3 communication evidence: " + "; ".join(f"{axis} votes {values}" for axis, values in profile["evidence"]["part_3_votes"].items()) + ".")
    most_least = profile["evidence"]["most_least"]
    lines.append(f"- MOST: {most_least['most']}; LEAST: {most_least['least']}. These are descriptive evidence and do not alter operator axes.")
    lines.extend(["", "## Explicit response-adjustment history"])
    if applied_adjustments:
        for adjustment in applied_adjustments:
            lines.append(f"- Response {adjustment['response_id']}: {adjustment['label']} — {adjustment['axis']} changed from {adjustment['previous']} to {adjustment['current']}.")
    else:
        lines.append("- No explicit response adjustments recorded.")
    return "\n".join(lines) + "\n"


def _render_connectors(applications: list[dict]) -> str:
    lines = ["# Selected applications", "", "Selections are planning context, not proof of a live connection."]
    for application in applications:
        use = "already used and wanted" if application["already_uses"] and application["wants_added"] else "already used" if application["already_uses"] else "wanted"
        lines.extend(["", f"## {application['name']}"])
        if application["registry_id"]:
            lines.append(f"- Registry ID: {application['registry_id']}")
        lines.extend([
            f"- Use: {use}",
            f"- Current activities: {application['current_activities']}",
            f"- Desired Cordia activities: {application['desired_activities']}",
            f"- Required inputs and expected outputs: {application['inputs_outputs']}",
            f"- Requested control level: {CONTROL_LEVEL_LABELS[application['control_level']]}",
            f"- Approval boundary: {CONTROL_LEVEL_LABELS[application['control_level']]}",
        ])
        if application["auth_kind"]:
            lines.append(f"- Authentication type: {application['auth_kind']}")
        lines.append(f"- Status: {application['status']}")
    return "\n".join(lines) + "\n"


def _render_fde(discovery: dict, applications: list[dict]) -> str:
    lines = [
        "# First workspace plan",
        "",
        "This is a proposed plan, not proof that the work is implemented.",
        "",
        "## Desired outcome",
        discovery["outcome"],
        "",
        "## Success criteria",
        discovery["success_criteria"],
        "",
        "## Current workflow",
        discovery["current_workflow"],
        "",
        "## Proposed first future workflow",
        f"Proposed: use the selected applications to turn {discovery['inputs']} into {discovery['outputs']}",
        "",
        "## Smallest valuable workspace slice",
        discovery["first_workspace"],
        "",
        "## Required applications and missing connections",
    ]
    lines.extend(f"- {application['name']}: {application['status']}" for application in applications)
    lines.extend([
        "",
        "## Proposed initial artifacts and skills",
        f"- Proposed artifact: {discovery['outputs']}",
        "- Proposed skill: organize the supplied workflow inputs into a reviewable result.",
        "",
        "## Human-approval boundaries",
        CONTROL_LEVEL_LABELS[discovery["control_level"]],
    ])
    if discovery.get("approval_boundaries"):
        lines.append(discovery["approval_boundaries"])
    if discovery.get("sensitive_data") or discovery.get("sensitive_data_details"):
        lines.extend(["", "## Security and sensitivity constraints"])
        if discovery.get("sensitive_data"):
            lines.append("- Sensitive data categories: " + ", ".join(discovery["sensitive_data"]) + ".")
        if discovery.get("sensitive_data_details"):
            lines.append("- Handling detail: " + discovery["sensitive_data_details"])
    if discovery.get("environment") or discovery.get("environment_policy"):
        lines.extend(["", "## Environment constraints"])
        if discovery.get("environment"):
            lines.append("- Environments: " + ", ".join(discovery["environment"]) + ".")
        if discovery.get("environment_policy"):
            lines.append("- Policy: " + discovery["environment_policy"])
    if discovery.get("failure_behavior"):
        lines.extend(["", "## Failure behavior", discovery["failure_behavior"]])
    if discovery.get("deadline"):
        lines.extend(["", "## Timing constraints", discovery["deadline"]])
    if discovery.get("policies"):
        lines.extend(["", "## Policy constraints", discovery["policies"]])
    lines.extend([
        "",
        "## Ordered implementation sequence",
        "1. Resolve missing application connections through verified setup where supported.",
        "2. Confirm the proposed workflow and approval boundary with the user.",
        "3. Build and review the smallest valuable workspace slice.",
        "",
        "## Explicit unknowns",
        "- The Cordia Agent must resolve any missing source access, workflow details, and connection setup through conversation or verified action.",
    ])
    return "\n".join(lines) + "\n"


def compile_documents(
    stages: dict[str, dict],
    adjustments: list[dict],
    connector_catalog: dict[str, dict],
    connection_statuses: dict[str, str] | None = None,
) -> dict[str, str]:
    """Compile onboarding context into three stable Markdown documents."""
    profile = score_profile(stages)
    applications = _normalize_applications(
        _answers(stages, "workspace_discovery")["applications"],
        connector_catalog,
        connection_statuses or {},
    )
    return {
        "operator.md": _render_operator(profile, adjustments),
        "connectors.md": _render_connectors(applications),
        "fde.md": _render_fde(_answers(stages, "workspace_discovery"), applications),
    }
