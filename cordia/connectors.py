from __future__ import annotations

import re


def normalize_identifier(value: str) -> str:
    """Normalize user text for comparison without creating an app allowlist."""
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def public_application(record: dict) -> dict:
    """Translate one provider-owned application record into Cordia's public shape."""
    application_id = str(record.get("name_slug") or record.get("id") or "").strip()
    name = str(record.get("name") or "").strip()
    if not application_id or not name:
        raise ValueError("provider application requires an id and name")
    logo = str(record.get("img_src") or record.get("logo") or "").strip()
    if logo and not logo.startswith(("https://", "/static/")):
        logo = ""
    categories = record.get("categories") or []
    if not isinstance(categories, list):
        categories = []
    return {
        "id": application_id,
        "name": name,
        "logo": logo,
        "description": str(record.get("description") or "").strip(),
        "categories": [str(item) for item in categories if item],
        "auth_kind": str(record.get("auth_type") or "managed").strip(),
    }


def public_tool(record: dict) -> dict:
    """Preserve provider tool identity and schema without app-specific mapping."""
    tool_id = str(record.get("name") or record.get("id") or "").strip()
    if not tool_id:
        raise ValueError("provider tool requires an id")
    schema = record.get("inputSchema") or record.get("input_schema") or {}
    if not isinstance(schema, dict):
        schema = {}
    annotations = record.get("annotations") or {}
    if not isinstance(annotations, dict):
        annotations = {}
    return {
        "id": tool_id,
        "name": str(record.get("title") or tool_id).strip(),
        "description": str(record.get("description") or "").strip(),
        "input_schema": schema,
        "annotations": annotations,
    }


def resolve_application(value: str, catalog: list[dict]) -> dict | None:
    wanted = normalize_identifier(value)
    exact_name = next(
        (
            application
            for application in catalog
            if normalize_identifier(application.get("name", "")) == wanted
        ),
        None,
    )
    if exact_name:
        return exact_name
    for application in catalog:
        names = {application.get("id", ""), application.get("name", "")}
        if wanted in {normalize_identifier(name) for name in names if name}:
            return application
    return None


def catalog_for_onboarding(applications: list[dict]) -> dict[str, dict]:
    """Adapt a runtime list to the existing onboarding compiler's mapping contract."""
    return {
        application["id"]: {**application, "aliases": []}
        for application in applications
    }
