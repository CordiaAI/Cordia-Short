"""Versioned, browser-safe Surveyor manifest and answer validation."""

from __future__ import annotations

from copy import deepcopy


SCHEMA_VERSION = 2
STAGE_ORDER = (
    "assessment_part_1",
    "assessment_part_2",
    "assessment_part_3",
    "assessment_part_4",
    "profile_snapshot",
    "workspace_discovery",
    "workspace_review",
)
PERSISTED_STAGES = (
    "assessment_part_1",
    "assessment_part_2",
    "assessment_part_3",
    "assessment_part_4",
    "workspace_discovery",
)

PART_1 = (
    {"id": "p1_01", "prompt": "Am the life of the party.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_02", "prompt": "Talk to a lot of different people at parties.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_03", "prompt": "Don't talk a lot.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_04", "prompt": "Keep in the background.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_05", "prompt": "Sympathize with others' feelings.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_06", "prompt": "Feel others' emotions.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_07", "prompt": "Am not really interested in others.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_08", "prompt": "Am not interested in other people's problems.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_09", "prompt": "Get chores done right away.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_10", "prompt": "Like order.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_11", "prompt": "Often forget to put things back in their proper place.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_12", "prompt": "Make a mess of things.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_13", "prompt": "Have frequent mood swings.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_14", "prompt": "Get upset easily.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_15", "prompt": "Am relaxed most of the time.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_16", "prompt": "Seldom feel blue.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_17", "prompt": "Have a vivid imagination.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_18", "prompt": "Have difficulty understanding abstract ideas.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_19", "prompt": "Am not interested in abstract ideas.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_20", "prompt": "Do not have a good imagination.", "options": (1, 2, 3, 4, 5)},
)

DOMAINS = {
    "work_professional": {"label": "Work / professional (whatever your actual job is)", "terms": ()},
    "technology_software": {"label": "Technology & software", "terms": ("cloud storage", "two-factor authentication", "adaptive port throttling", "browser cache", "API")},
    "money_finance": {"label": "Money & finance", "terms": ("APR", "annualized credit", "amortization", "compound interest", "diversification")},
    "health_wellness": {"label": "Health & wellness", "terms": ("inflammation", "metabolic threshold syncing", "BMI", "cholesterol", "electrolytes")},
    "creative_writing": {"label": "Creative & writing", "terms": ("dangling modifier", "narrative displacement clause", "iambic pentameter", "thesis statement", "active voice")},
    "everyday_general": {"label": "Everyday life / general knowledge", "terms": ("the food-safety temperature danger zone", "expiration vs. best-by dates", "daylight saving time", "recycling symbols", "passive humidity banking")},
}

PART_3 = (
    {"id": "briefing_style", "prompt": "You're briefing a new assistant on a task. You'd rather:", "options": (("requirements_upfront", "Write out every requirement and constraint upfront"), ("gist_then_correct", "Give the gist and correct it as you go"))},
    {"id": "reply_preference", "prompt": '"Can you look at this and tell me what you think?" Which reply would you rather get?', "options": (("literal_narrow", "A literal, narrow reply that answers only what was explicitly asked"), ("infer_context", "A reply that infers likely unstated context and addresses it"))},
    {"id": "most_least", "prompt": "Pick which word describes you MOST, and which describes you LEAST.", "options": ("logical", "practical", "imaginative", "data-driven"), "distinct_selection": True},
    {"id": "flawed_plan", "prompt": "A colleague's plan has an obvious flaw. Do you:", "options": (("state_plainly", "State it plainly"), ("leading_questions", "Ask leading questions to get them there"), ("hint", "Hint at it"), ("go_along", "Go along with it"))},
    {"id": "answer_order", "prompt": "When someone asks you a question, you tend to:", "options": (("reasoning_first", "Walk through your reasoning first, then give the answer"), ("answer_first", "Give the answer first, then reasoning if asked"))},
    {"id": "background_assumption", "prompt": "When explaining something to someone, you usually:", "options": (("spell_out_background", "Assume they need the background spelled out"), ("infer_from_context", "Assume they'll pick up what you mean from context"))},
    {"id": "edit_boundary", "prompt": '"Hey, could you take a pass at this before I send it?" Which reply would you rather get?', "options": (("only_requested_edits", "A reply that makes only the specific edits literally requested"), ("flag_likely_problems", "A reply that also flags likely problems the sender didn't mention"))},
    {"id": "bad_idea", "prompt": "Someone asks your opinion on something you think is a bad idea. You:", "options": (("say_so_directly", "Say so directly"), ("soften_heavily", "Soften it heavily"), ("ask_questions", "Ask questions instead of stating your view"))},
)

PART_4_FIELDS = (
    {"id": "request_1", "label": "Request 1", "required": True, "max_length": 2000},
    {"id": "request_2", "label": "Request 2", "required": True, "max_length": 2000},
    {"id": "request_3", "label": "Request 3", "required": False, "max_length": 2000},
)
RATING_OPTIONS = (
    {"id": 1, "label": "1 (Very Inaccurate)"},
    {"id": 2, "label": "2"},
    {"id": 3, "label": "3"},
    {"id": 4, "label": "4"},
    {"id": 5, "label": "5 (Very Accurate)"},
)
CONTROL_LEVEL_OPTIONS = (
    {"id": "suggest_actions_only", "label": "Suggest actions only"},
    {"id": "prepare_for_approval", "label": "Prepare work for approval"},
    {"id": "perform_approved_actions", "label": "Perform approved actions"},
    {"id": "automate_low_risk", "label": "Automate low-risk actions"},
)
CONTROL_LEVEL_IDS = tuple(option["id"] for option in CONTROL_LEVEL_OPTIONS)
SENSITIVE_DATA_OPTIONS = (
    {"id": "personal", "label": "personal"},
    {"id": "financial", "label": "financial"},
    {"id": "health", "label": "health"},
    {"id": "legal", "label": "legal"},
    {"id": "employee", "label": "employee"},
    {"id": "confidential", "label": "confidential"},
)
ENVIRONMENT_OPTIONS = (
    {"id": "web", "label": "web"},
    {"id": "desktop", "label": "desktop"},
    {"id": "local_files", "label": "local files"},
    {"id": "company_network", "label": "a company network"},
    {"id": "cloud_services", "label": "cloud services"},
    {"id": "mobile_devices", "label": "mobile devices"},
)

DISCOVERY_FIELDS = (
    {"id": "outcome", "label": "What is the first meaningful result you want this workspace to produce?", "required": True},
    {"id": "success_criteria", "label": "How will you know it worked?", "required": True},
    {"id": "current_workflow", "label": "Walk Cordia through how you handle this today.", "required": True},
    {"id": "applications", "label": "Which applications are involved?", "required": True},
    {"id": "inputs", "label": "What information starts this workflow?", "required": True},
    {"id": "outputs", "label": "What should Cordia produce or change?", "required": True},
    {"id": "control_level", "label": "Control level", "required": True, "options": CONTROL_LEVEL_OPTIONS},
    {"id": "first_workspace", "label": "Which part should Cordia build first?", "required": True},
)
CONDITIONAL_DISCOVERY_FIELDS = {
    "source_locations": {"label": "Where are the relevant documents, records, or messages?"},
    "cadence": {"label": "Is this occasional, daily, continuous, or event-triggered?"},
    "scale": {"label": "Roughly how many files, records, customers, or requests are involved?"},
    "people_roles": {"label": "Who creates, reviews, approves, or receives the work?"},
    "permissions": {"label": "What may Cordia read, create, edit, send, or execute?"},
    "sensitive_data": {"label": "Does the workflow involve personal, financial, health, legal, employee, or confidential information?", "options": SENSITIVE_DATA_OPTIONS},
    "sensitive_data_details": {"label": "What sensitive data is involved and how should it be handled?"},
    "environment": {"label": "Does the work happen on the web, desktop, local files, a company network, cloud services, or mobile devices?", "options": ENVIRONMENT_OPTIONS},
    "failure_behavior": {"label": "What should happen if the automation fails?"},
    "approval_boundaries": {"label": "What actions need approval before Cordia performs them?"},
    "deadline": {"label": "Is there a deadline or response-time requirement?"},
    "policies": {"label": "Are there company policies, compliance rules, preferred providers, or prohibited tools?"},
    "environment_policy": {"label": "What environment or policy constraints should Cordia respect?"},
}


def _browser_copy(value):
    if isinstance(value, dict):
        return {key: _browser_copy(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_browser_copy(item) for item in value]
    return deepcopy(value)


def public_stage_schema(stage: str, answers: dict | None = None) -> dict:
    """Return a fresh JSON-safe schema for one displayed onboarding stage."""
    if stage not in STAGE_ORDER:
        raise ValueError("unknown onboarding stage")
    part_3_questions = []
    for question in PART_3:
        browser_question = {"id": question["id"], "prompt": question["prompt"]}
        if question["id"] == "most_least":
            browser_question["options"] = question["options"]
            browser_question["distinct_selection"] = True
        else:
            browser_question["options"] = tuple(
                {"id": option_id, "label": label}
                for option_id, label in question["options"]
            )
        part_3_questions.append(browser_question)
    discovery = (answers or {}).get("workspace_discovery", answers or {})
    if isinstance(discovery, dict) and isinstance(discovery.get("answers"), dict):
        discovery = discovery["answers"]
    schemas = {
        "assessment_part_1": {"title": "Part 1 of 4: About you", "instructions": "Describe yourself as you generally are now, not as you wish to be in the future. Describe yourself as you honestly see yourself, in relation to other people you know of the same sex and age. Rate each statement from 1 (Very Inaccurate) to 5 (Very Accurate).", "rating_options": RATING_OPTIONS, "questions": PART_1},
        "assessment_part_2": {"title": "Part 2 of 4: Your domains", "instructions": "Pick 1-2 areas where you'd bring real context to an AI conversation.", "domains": DOMAINS, "domain_limit": {"minimum": 1, "maximum": 2}},
        "assessment_part_3": {"title": "Part 3 of 4: How you communicate", "instructions": "There are no right answers — pick whichever feels closest to how you actually operate.", "questions": tuple(part_3_questions)},
        "assessment_part_4": {"title": "Part 4 of 4: In your own words", "instructions": "Write 2-3 things you'd actually type to an AI assistant if you were using one right now for something real — not test questions, actual requests you'd send.", "fields": PART_4_FIELDS},
        "profile_snapshot": {"title": "Profile snapshot", "computed": True},
        "workspace_discovery": {"title": "Workspace Discovery", "fields": DISCOVERY_FIELDS, "conditional_fields": CONDITIONAL_DISCOVERY_FIELDS, "active_conditional_fields": conditional_discovery_fields(discovery)},
        "workspace_review": {"title": "Workspace Review", "computed": True},
    }
    return _browser_copy(schemas[stage])


def _reject_unexpected(payload: dict, allowed: set[str]) -> None:
    unexpected = set(payload) - allowed
    if unexpected:
        raise ValueError("unexpected field: " + sorted(unexpected)[0])


def _rating(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in (1, 2, 3, 4, 5):
        raise ValueError(f"{field} must be an integer from 1 to 5")
    return value


def _text(value, field: str, maximum: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    clean = value.strip()
    if required and not clean:
        raise ValueError(f"{field} is required")
    if len(clean) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")
    return clean


def _validate_part_1(payload: dict) -> dict:
    _reject_unexpected(payload, {"answers"})
    answers = payload.get("answers")
    expected = {question["id"] for question in PART_1}
    if not isinstance(answers, dict) or set(answers) != expected:
        raise ValueError("Part 1 requires ratings for all 20 statements")
    return {"answers": {question["id"]: _rating(answers[question["id"]], question["id"]) for question in PART_1}}


def _validate_part_2(payload: dict) -> dict:
    _reject_unexpected(payload, {"domains", "ratings", "familiarity"})
    domains, ratings, familiarity = payload.get("domains"), payload.get("ratings"), payload.get("familiarity")
    if not isinstance(domains, list) or not 1 <= len(domains) <= 2:
        raise ValueError("select 1 or 2 domains")
    if not all(isinstance(domain, str) for domain in domains) or len(set(domains)) != len(domains):
        raise ValueError("unknown domain")
    if any(domain not in DOMAINS for domain in domains):
        raise ValueError("unknown domain")
    if not isinstance(ratings, dict) or set(ratings) != set(domains):
        raise ValueError("ratings are required for each selected domain")
    if not isinstance(familiarity, dict) or set(familiarity) != set(domains):
        raise ValueError("familiarity is required for each selected domain")
    clean_familiarity = {}
    for domain in domains:
        terms = DOMAINS[domain]["terms"]
        supplied = familiarity[domain]
        if not isinstance(supplied, dict) or set(supplied) != set(terms):
            raise ValueError(f"familiarity answers are required for {domain}")
        if any(answer not in ("familiar", "not_familiar") for answer in supplied.values()):
            raise ValueError(f"familiarity answers for {domain} must be familiar or not_familiar")
        clean_familiarity[domain] = {term: supplied[term] for term in terms}
    return {"domains": list(domains), "ratings": {domain: _rating(ratings[domain], domain) for domain in domains}, "familiarity": clean_familiarity}


def _validate_part_3(payload: dict) -> dict:
    question_ids = {question["id"] for question in PART_3 if question["id"] != "most_least"}
    allowed = question_ids | {"most", "least"}
    _reject_unexpected(payload, allowed)
    if set(payload) != allowed:
        raise ValueError("all Part 3 answers are required")
    clean = {}
    for question in PART_3:
        if question["id"] == "most_least":
            continue
        choices = {choice[0] for choice in question["options"]}
        value = payload[question["id"]]
        if not isinstance(value, str) or value not in choices:
            raise ValueError(f"{question['id']} has an unknown option")
        clean[question["id"]] = value
    words = set(next(question for question in PART_3 if question["id"] == "most_least")["options"])
    if not isinstance(payload["most"], str) or not isinstance(payload["least"], str) or payload["most"] not in words or payload["least"] not in words:
        raise ValueError("MOST and LEAST must be valid choices")
    if payload["most"] == payload["least"]:
        raise ValueError("MOST and LEAST must be different")
    return {"briefing_style": clean["briefing_style"], "reply_preference": clean["reply_preference"], "most": payload["most"], "least": payload["least"], "flawed_plan": clean["flawed_plan"], "answer_order": clean["answer_order"], "background_assumption": clean["background_assumption"], "edit_boundary": clean["edit_boundary"], "bad_idea": clean["bad_idea"]}


def _validate_part_4(payload: dict) -> dict:
    fields = {field["id"] for field in PART_4_FIELDS}
    _reject_unexpected(payload, fields)
    return {field["id"]: _text(payload.get(field["id"], ""), field["label"], field["max_length"], field["required"]) for field in PART_4_FIELDS}


def _validate_application(application: dict) -> dict:
    allowed = {"application_id", "name", "already_uses", "wants_added", "current_activities", "desired_activities", "inputs_outputs", "control_level"}
    if not isinstance(application, dict):
        raise ValueError("application must be an object")
    _reject_unexpected(application, allowed)
    if set(application) != allowed:
        raise ValueError("application is incomplete")
    application_id = application["application_id"]
    if application_id is not None and (not isinstance(application_id, str) or not application_id.strip()):
        raise ValueError("application_id must be text or null")
    if not isinstance(application["already_uses"], bool) or not isinstance(application["wants_added"], bool):
        raise ValueError("application use choices must be booleans")
    if not application["already_uses"] and not application["wants_added"]:
        raise ValueError("application must be already used or wanted")
    if not isinstance(application["control_level"], str) or application["control_level"] not in CONTROL_LEVEL_IDS:
        raise ValueError("application control_level is invalid")
    return {"application_id": application_id.strip() if isinstance(application_id, str) else None, "name": _text(application["name"], "application name", 400), "already_uses": application["already_uses"], "wants_added": application["wants_added"], "current_activities": _text(application["current_activities"], "current_activities", 4000), "desired_activities": _text(application["desired_activities"], "desired_activities", 4000), "inputs_outputs": _text(application["inputs_outputs"], "inputs_outputs", 4000), "control_level": application["control_level"]}


def _validate_workspace_discovery(payload: dict) -> dict:
    core_ids = {field["id"] for field in DISCOVERY_FIELDS}
    conditional_ids = set(CONDITIONAL_DISCOVERY_FIELDS)
    _reject_unexpected(payload, core_ids | conditional_ids)
    if not core_ids <= set(payload):
        raise ValueError("all Workspace Discovery core fields are required")
    if not isinstance(payload["control_level"], str) or payload["control_level"] not in CONTROL_LEVEL_IDS:
        raise ValueError("control_level is invalid")
    applications = payload["applications"]
    if not isinstance(applications, list) or not applications:
        raise ValueError("at least one application is required")
    if len(applications) > 20:
        raise ValueError("no more than 20 applications are allowed")
    clean = {field_id: _text(payload[field_id], field_id, 4000) for field_id in ("outcome", "success_criteria", "current_workflow", "inputs", "outputs", "first_workspace")}
    clean["applications"] = [_validate_application(application) for application in applications]
    clean["control_level"] = payload["control_level"]
    trigger_ids = {"sensitive_data", "environment"}
    for field_id in trigger_ids & set(payload):
        value = payload[field_id]
        allowed_options = SENSITIVE_DATA_OPTIONS if field_id == "sensitive_data" else ENVIRONMENT_OPTIONS
        allowed_ids = {option["id"] for option in allowed_options}
        if not isinstance(value, list) or not all(isinstance(item, str) and item in allowed_ids for item in value):
            raise ValueError(f"{field_id} must be a list of valid choices")
        clean[field_id] = list(value)
    active_conditional_ids = set(conditional_discovery_fields(clean))
    supplied_conditional_ids = conditional_ids & set(payload) - trigger_ids
    inactive = supplied_conditional_ids - active_conditional_ids
    if inactive:
        raise ValueError("inactive conditional field: " + sorted(inactive)[0])
    for field_id in active_conditional_ids & set(payload):
        clean[field_id] = _text(payload[field_id], field_id, 4000)
    return clean


def validate_stage(stage: str, payload: dict) -> dict:
    if stage not in PERSISTED_STAGES:
        raise ValueError("unknown onboarding stage")
    if not isinstance(payload, dict):
        raise ValueError("stage answers must be an object")
    validators = {"assessment_part_1": _validate_part_1, "assessment_part_2": _validate_part_2, "assessment_part_3": _validate_part_3, "assessment_part_4": _validate_part_4, "workspace_discovery": _validate_workspace_discovery}
    return {"schema_version": SCHEMA_VERSION, "answers": validators[stage](payload)}


def next_stage(saved_stages: dict[str, dict]) -> str | None:
    for stage in PERSISTED_STAGES:
        if stage not in saved_stages:
            return stage
    return None


def conditional_discovery_fields(discovery: dict) -> list[str]:
    """Return stable conditional field identifiers from saved core answers only."""
    if not isinstance(discovery, dict):
        return []
    fields = []
    sensitive = discovery.get("sensitive_data", [])
    if isinstance(sensitive, list) and any(item in {"personal", "financial", "health", "legal", "employee", "confidential"} for item in sensitive):
        fields.append("sensitive_data_details")
    if discovery.get("control_level") in {"perform_approved_actions", "automate_low_risk"}:
        fields.extend(("failure_behavior", "approval_boundaries"))
    environment = discovery.get("environment", [])
    if isinstance(environment, list) and environment:
        fields.append("environment_policy")
    return fields
