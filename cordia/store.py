from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from cordia.connectors import CONNECTORS
from cordia.onboarding import compile_documents, score_profile
from cordia.survey import PERSISTED_STAGES, SCHEMA_VERSION, validate_stage


SURVEY_FIELDS = ("name", "role", "goal", "apps", "communication")
SURVEY_LABELS = {
    "name": "Name",
    "role": "Role",
    "goal": "Primary goal",
    "apps": "Current apps",
    "communication": "Communication preference",
}
OPERATOR_AXES = ("context", "scope", "directness", "implementation")
OPERATOR_AXIS_LABELS = {
    "context": {
        -1: "Explicit",
        0: "Balanced",
        1: "Implicit / high-context",
    },
    "scope": {-1: "Detail-first", 0: "Balanced", 1: "Big-picture"},
    "directness": {-1: "Measured", 0: "Balanced", 1: "Direct"},
    "implementation": {
        -1: "Conceptual",
        0: "Balanced",
        1: "Implementation-first",
    },
}


class Store:
    def __init__(self, db_path: str | Path, workspace_root: str | Path):
        self.db_path = Path(db_path)
        self.workspace_root = Path(workspace_root)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self._cipher = Fernet(self._vault_key())
        self._initialize()

    def _vault_key(self) -> bytes:
        path = self.db_path.parent / ".vault.key"
        if not path.exists():
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(Fernet.generate_key())
            temporary.replace(path)
        return path.read_bytes()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS survey_answers (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    field TEXT NOT NULL,
                    value TEXT NOT NULL,
                    PRIMARY KEY (user_id, field)
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    kind TEXT NOT NULL DEFAULT 'chat' CHECK (kind IN ('chat', 'survey', 'agent')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_states (
                    state_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    connector_id TEXT NOT NULL,
                    requested_scopes TEXT NOT NULL DEFAULT '[]',
                    expires_at TEXT NOT NULL,
                    used_at TEXT
                );
                CREATE TABLE IF NOT EXISTS connections (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    connector_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    credentials TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, connector_id)
                );
                CREATE TABLE IF NOT EXISTS connection_settings (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    connector_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, connector_id, name)
                );
                CREATE TABLE IF NOT EXISTS setup_cards (
                    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operator_profiles (
                    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    context INTEGER NOT NULL DEFAULT 0 CHECK (context IN (-1, 0, 1)),
                    scope INTEGER NOT NULL DEFAULT 0 CHECK (scope IN (-1, 0, 1)),
                    directness INTEGER NOT NULL DEFAULT 0 CHECK (directness IN (-1, 0, 1)),
                    implementation INTEGER NOT NULL DEFAULT 0 CHECK (implementation IN (-1, 0, 1)),
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operator_adjustments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    response_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                    axis TEXT NOT NULL,
                    target INTEGER NOT NULL CHECK (target IN (-1, 1)),
                    previous INTEGER NOT NULL CHECK (previous IN (-1, 0, 1)),
                    current INTEGER NOT NULL CHECK (current IN (-1, 0, 1)),
                    label TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            message_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(messages)").fetchall()
            }
            if "kind" not in message_columns:
                connection.execute(
                    "ALTER TABLE messages ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat'"
                )
            oauth_state_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(oauth_states)").fetchall()
            }
            if "requested_scopes" not in oauth_state_columns:
                connection.execute(
                    "ALTER TABLE oauth_states ADD COLUMN requested_scopes TEXT NOT NULL DEFAULT '[]'"
                )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_email(email: str) -> str:
        normalized = email.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("valid email required")
        return normalized

    @staticmethod
    def _hash_password(password: str, salt: bytes | None = None) -> str:
        if len(password) < 12:
            raise ValueError("password must be at least 12 characters")
        salt = salt or secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)
        return "pbkdf2_sha256$240000${}${}".format(
            base64.urlsafe_b64encode(salt).decode(),
            base64.urlsafe_b64encode(digest).decode(),
        )

    @staticmethod
    def _password_matches(password: str, encoded: str) -> bool:
        try:
            algorithm, rounds, salt_text, expected_text = encoded.split("$", 3)
            if algorithm != "pbkdf2_sha256" or rounds != "240000":
                return False
            salt = base64.urlsafe_b64decode(salt_text.encode())
            actual = Store._hash_password(password, salt).split("$", 3)[3]
            return hmac.compare_digest(actual, expected_text)
        except (ValueError, TypeError):
            return False

    def register(self, email: str, password: str) -> int:
        normalized = self._normalize_email(email)
        password_hash = self._hash_password(password)
        try:
            with self._connection() as connection:
                cursor = connection.execute(
                    "INSERT INTO users(email, password_hash, created_at) VALUES (?, ?, ?)",
                    (normalized, password_hash, self._now().isoformat()),
                )
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise ValueError("email already registered") from exc

    def authenticate(self, email: str, password: str) -> int | None:
        try:
            normalized = self._normalize_email(email)
        except ValueError:
            return None
        with self._connection() as connection:
            row = connection.execute(
                "SELECT id, password_hash FROM users WHERE email = ?", (normalized,)
            ).fetchone()
        if row and self._password_matches(password, row["password_hash"]):
            return int(row["id"])
        return None

    def create_session(self, user_id: int, lifetime_days: int = 7) -> str:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires_at = self._now() + timedelta(days=lifetime_days)
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (token_hash, user_id, expires_at.isoformat()),
            )
        return token

    def user_for_session(self, token: str | None) -> int | None:
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT user_id, expires_at FROM sessions WHERE token_hash = ?", (token_hash,)
            ).fetchone()
            if not row:
                return None
            if datetime.fromisoformat(row["expires_at"]) <= self._now():
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                return None
            return int(row["user_id"])

    def end_session(self, token: str | None) -> None:
        if not token:
            return
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self._connection() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def save_survey_answer(self, user_id: int, field: str, value: str) -> None:
        if field not in SURVEY_FIELDS:
            raise ValueError("unknown survey field")
        clean = value.strip()
        if not clean:
            raise ValueError("survey answer required")
        self._save_survey_value(user_id, field, clean)
        if not self._uses_onboarding_schema(user_id):
            self._write_operator(user_id)

    def _save_survey_value(self, user_id: int, field: str, value: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO survey_answers(user_id, field, value) VALUES (?, ?, ?)
                ON CONFLICT(user_id, field) DO UPDATE SET value = excluded.value
                """,
                (user_id, field, value),
            )

    def survey_answers(self, user_id: int) -> dict[str, str]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT field, value FROM survey_answers WHERE user_id = ?", (user_id,)
            ).fetchall()
        return {row["field"]: row["value"] for row in rows}

    def legacy_survey_complete(self, user_id: int) -> bool:
        answers = self.survey_answers(user_id)
        return all(answers.get(field) for field in SURVEY_FIELDS)

    def _uses_onboarding_schema(self, user_id: int) -> bool:
        return self.survey_answers(user_id).get("survey_schema_version") == str(SCHEMA_VERSION)

    def onboarding_stages(self, user_id: int) -> dict[str, dict]:
        placeholders = ", ".join("?" for _ in PERSISTED_STAGES)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT field, value FROM survey_answers WHERE user_id = ? AND field IN ({placeholders})",
                (user_id, *PERSISTED_STAGES),
            ).fetchall()
        stored = {row["field"]: row["value"] for row in rows}
        stages = {}
        for stage in PERSISTED_STAGES:
            try:
                document = json.loads(stored[stage])
                if (
                    not isinstance(document, dict)
                    or document.get("schema_version") != SCHEMA_VERSION
                    or not isinstance(document.get("completed_at"), str)
                    or not document["completed_at"].strip()
                ):
                    continue
                validated = validate_stage(stage, document.get("answers"))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            stages[stage] = {
                "schema_version": validated["schema_version"],
                "answers": validated["answers"],
                "completed_at": document["completed_at"],
            }
        return stages

    def onboarding_state(self, user_id: int) -> dict:
        stages = self.onboarding_stages(user_id)
        completed_stages = [stage for stage in PERSISTED_STAGES if stage in stages]
        marker_is_valid = (
            self._uses_onboarding_schema(user_id)
            and len(stages) == len(PERSISTED_STAGES)
        )
        if marker_is_valid:
            current_stage = "workspace"
        else:
            missing = next((stage for stage in PERSISTED_STAGES if stage not in stages), None)
            current_stage = missing or "workspace_review"
            if missing == "workspace_discovery" and all(
                stage in stages for stage in PERSISTED_STAGES[:4]
            ):
                current_stage = "profile_snapshot"
        state = {
            "schema_version": SCHEMA_VERSION,
            "current_stage": current_stage,
            "completed_stages": completed_stages,
            "answers": {stage: stages[stage]["answers"] for stage in completed_stages},
        }
        if all(stage in stages for stage in PERSISTED_STAGES[:4]):
            state["profile"] = score_profile(stages)
        if "workspace_discovery" in stages:
            state["review"] = {"workspace_discovery": stages["workspace_discovery"]["answers"]}
        return state

    def save_onboarding_stage(self, user_id: int, stage: str, payload: dict) -> dict:
        if stage not in PERSISTED_STAGES:
            raise ValueError("unknown onboarding stage")
        saved_stages = self.onboarding_stages(user_id)
        required_before = PERSISTED_STAGES[: PERSISTED_STAGES.index(stage)]
        missing = next((name for name in required_before if name not in saved_stages), None)
        if missing:
            raise ValueError(f"complete {missing} first")
        document = validate_stage(stage, payload)
        document["completed_at"] = self._now().isoformat()
        self._save_survey_value(
            user_id,
            stage,
            json.dumps(document, sort_keys=True, separators=(",", ":")),
        )
        return document

    def survey_complete(self, user_id: int) -> bool:
        return (
            self._uses_onboarding_schema(user_id)
            and len(self.onboarding_stages(user_id)) == len(PERSISTED_STAGES)
        )

    @staticmethod
    def _connector_key(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")

    def _selected_connection_statuses(
        self, user_id: int, stages: dict[str, dict], connector_catalog: dict
    ) -> dict[str, str]:
        known_connectors = {}
        for catalog_id, connector in connector_catalog.items():
            connector_id = connector.get("id")
            if not isinstance(connector_id, str):
                continue
            for identity in (
                catalog_id,
                connector_id,
                connector.get("name"),
                *connector.get("aliases", []),
            ):
                if isinstance(identity, str):
                    known_connectors[self._connector_key(identity)] = connector_id
        selected_ids = set()
        for application in stages["workspace_discovery"]["answers"]["applications"]:
            for identity in (application["application_id"], application["name"]):
                if isinstance(identity, str):
                    connector_id = known_connectors.get(self._connector_key(identity))
                    if connector_id:
                        selected_ids.add(connector_id)
        return {
            connector_id: status
            for connector_id in selected_ids
            if (status := self.connection_status(user_id, connector_id)) is not None
        }

    def _operator_adjustments(self, user_id: int) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, response_id, label, axis, previous, current, created_at
                FROM operator_adjustments WHERE user_id = ? ORDER BY id ASC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _remove_temporary_directory(directory: Path, files: list[Path]) -> None:
        for file_path in files:
            if file_path.exists():
                file_path.unlink()
        if directory.exists():
            directory.rmdir()

    def _compile_onboarding_documents(
        self, user_id: int, connector_catalog: dict
    ) -> dict[str, str]:
        stages = self.onboarding_stages(user_id)
        missing = next((stage for stage in PERSISTED_STAGES if stage not in stages), None)
        if missing:
            raise ValueError(f"complete {missing} first")
        for stage in PERSISTED_STAGES:
            validate_stage(stage, stages[stage]["answers"])
        return compile_documents(
            stages,
            self._operator_adjustments(user_id),
            connector_catalog,
            self._selected_connection_statuses(user_id, stages, connector_catalog),
        )

    def _install_onboarding_documents(
        self, user_id: int, documents: dict[str, str], after_install=None
    ) -> None:
        workspace = self.workspace_root / str(user_id)
        workspace.mkdir(parents=True, exist_ok=True)
        temporary_directory = workspace / f".onboarding-{secrets.token_hex(8)}"
        temporary_directory.mkdir()
        destinations = {name: workspace / name for name in documents}
        temporary_files = [temporary_directory / name for name in documents]
        backups = {
            name: destination.read_bytes() if destination.exists() else None
            for name, destination in destinations.items()
        }
        try:
            for name, contents in documents.items():
                (temporary_directory / name).write_text(contents, encoding="utf-8")
            try:
                for name in documents:
                    (temporary_directory / name).replace(destinations[name])
                if after_install:
                    after_install()
            except Exception:
                for name, destination in destinations.items():
                    backup = backups[name]
                    if backup is None:
                        if destination.exists():
                            destination.unlink()
                    else:
                        destination.write_bytes(backup)
                raise
        finally:
            self._remove_temporary_directory(temporary_directory, temporary_files)

    def complete_onboarding(self, user_id: int, connector_catalog: dict) -> dict[str, str]:
        documents = self._compile_onboarding_documents(user_id, connector_catalog)
        self._install_onboarding_documents(
            user_id,
            documents,
            lambda: self._save_survey_value(
                user_id, "survey_schema_version", str(SCHEMA_VERSION)
            ),
        )
        return documents

    def _recompile_completed_onboarding(self, user_id: int) -> None:
        self._install_onboarding_documents(
            user_id,
            self._compile_onboarding_documents(user_id, CONNECTORS),
        )

    def operator_profile(self, user_id: int) -> dict[str, int]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT context, scope, directness, implementation FROM operator_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            return {axis: 0 for axis in OPERATOR_AXES}
        return {axis: int(row[axis]) for axis in OPERATOR_AXES}

    def _write_operator(self, user_id: int) -> str:
        answers = self.survey_answers(user_id)
        profile = self.operator_profile(user_id)
        sections = ["# Operator profile", "", "This profile helps Cordia interpret prompts and shape responses. It does not change factual truth or grant additional authority.", ""]
        for field in SURVEY_FIELDS:
            if field in answers:
                sections.extend((f"## {SURVEY_LABELS[field]}", "", answers[field], ""))
        sections.extend(
            (
                "## Prompt interpretation map",
                "",
                f"- Context interpretation: {OPERATOR_AXIS_LABELS['context'][profile['context']]} ({profile['context']})",
                f"- Scope preference: {OPERATOR_AXIS_LABELS['scope'][profile['scope']]} ({profile['scope']})",
                "",
                "## Response preference map",
                "",
                f"- Directness: {OPERATOR_AXIS_LABELS['directness'][profile['directness']]} ({profile['directness']})",
                f"- Implementation preference: {OPERATOR_AXIS_LABELS['implementation'][profile['implementation']]} ({profile['implementation']})",
                "",
                "## Adjustment evidence",
                "",
            )
        )
        with self._connection() as connection:
            adjustments = connection.execute(
                """
                SELECT response_id, label, axis, previous, current, created_at
                FROM operator_adjustments WHERE user_id = ? ORDER BY id ASC
                """,
                (user_id,),
            ).fetchall()
        if adjustments:
            for item in adjustments:
                sections.append(
                    f"- Response {item['response_id']}: User selected “{item['label']}.” "
                    f"{item['axis'].capitalize()} changed from {item['previous']} to {item['current']}."
                )
        else:
            sections.append("- No response adjustments recorded yet.")
        operator = "\n".join(sections).rstrip() + "\n"
        directory = self.workspace_root / str(user_id)
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / "operator.md.tmp"
        destination = directory / "operator.md"
        temporary.write_text(operator, encoding="utf-8")
        temporary.replace(destination)
        return operator

    def operator_markdown(self, user_id: int) -> str:
        destination = self.workspace_root / str(user_id) / "operator.md"
        if destination.exists():
            return destination.read_text(encoding="utf-8")
        return self._write_operator(user_id)

    def memory_markdown(self, user_id: int) -> str:
        return self.operator_markdown(user_id)

    def agent_context(self, user_id: int) -> str:
        """Return compiled onboarding context only after its workspace is complete."""
        if not self.survey_complete(user_id):
            return self.operator_markdown(user_id)
        workspace = self.workspace_root / str(user_id)
        documents = []
        for name in ("operator.md", "connectors.md", "fde.md"):
            path = workspace / name
            if not path.exists():
                raise OSError("completed onboarding context is unavailable")
            documents.append(path.read_text(encoding="utf-8"))
        return "\n\n".join(documents)

    def adjust_operator(
        self,
        user_id: int,
        response_id: int,
        axis: str,
        target: int,
        label: str,
    ) -> dict:
        if axis not in OPERATOR_AXES:
            raise ValueError("unknown operator axis")
        if target not in (-1, 1) or isinstance(target, bool):
            raise ValueError("target must be -1 or 1")
        clean_label = str(label).strip()
        if not clean_label or len(clean_label) > 80:
            raise ValueError("adjustment label is invalid")
        with self._connection() as connection:
            response = connection.execute(
                "SELECT id FROM messages WHERE id = ? AND user_id = ? AND role = 'assistant' AND kind = 'agent'",
                (response_id, user_id),
            ).fetchone()
            if not response:
                raise LookupError("assistant response not found")
            row = connection.execute(
                "SELECT context, scope, directness, implementation FROM operator_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            current_profile = (
                {name: int(row[name]) for name in OPERATOR_AXES}
                if row
                else {name: 0 for name in OPERATOR_AXES}
            )
            previous = current_profile[axis]
            current = previous if previous == target else previous + (1 if target > previous else -1)
            current_profile[axis] = current
            now = self._now().isoformat()
            connection.execute(
                """
                INSERT INTO operator_profiles(user_id, context, scope, directness, implementation, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    context = excluded.context,
                    scope = excluded.scope,
                    directness = excluded.directness,
                    implementation = excluded.implementation,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    current_profile["context"],
                    current_profile["scope"],
                    current_profile["directness"],
                    current_profile["implementation"],
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO operator_adjustments(
                    user_id, response_id, axis, target, previous, current, label, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, response_id, axis, target, previous, current, clean_label, now),
            )
        if self._uses_onboarding_schema(user_id):
            self._recompile_completed_onboarding(user_id)
        else:
            self._write_operator(user_id)
        return {
            "axis": axis,
            "target": target,
            "previous": previous,
            "current": current,
            "label": clean_label,
        }

    def add_message(self, user_id: int, role: str, content: str, kind: str = "chat") -> int:
        if role not in {"user", "assistant"}:
            raise ValueError("invalid message role")
        if kind not in {"chat", "survey", "agent"}:
            raise ValueError("invalid message kind")
        clean = content.strip()
        if not clean:
            raise ValueError("message required")
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT INTO messages(user_id, role, kind, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, role, kind, clean, self._now().isoformat()),
            )
            return int(cursor.lastrowid)

    def messages(self, user_id: int, limit: int = 30) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, role, kind, content, created_at FROM (
                    SELECT id, role, kind, content, created_at
                    FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?
                ) ORDER BY id ASC
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def messages_before_response(
        self, user_id: int, response_id: int, limit: int = 30
    ) -> list[dict]:
        with self._connection() as connection:
            response = connection.execute(
                "SELECT id FROM messages WHERE id = ? AND user_id = ? AND role = 'assistant' AND kind = 'agent'",
                (response_id, user_id),
            ).fetchone()
            if not response:
                raise LookupError("assistant response not found")
            rows = connection.execute(
                """
                SELECT id, role, kind, content, created_at FROM (
                    SELECT id, role, kind, content, created_at FROM messages
                    WHERE user_id = ? AND id < ? ORDER BY id DESC LIMIT ?
                ) ORDER BY id ASC
                """,
                (user_id, response_id, limit),
            ).fetchall()
        messages = [dict(row) for row in rows]
        if not messages or messages[-1]["role"] != "user":
            raise LookupError("original user request not found")
        return messages

    def save_artifact(self, user_id: int, artifact: dict) -> int:
        slot = self._artifact_slot(artifact)
        display_slot = self._artifact_display_slot(artifact)
        with self._connection() as connection:
            if slot or display_slot:
                rows = connection.execute(
                    "SELECT id, payload FROM artifacts WHERE user_id = ? ORDER BY id DESC",
                    (user_id,),
                ).fetchall()
                for row in rows:
                    saved = json.loads(row["payload"])
                    same_operation = slot and self._artifact_slot(saved) == slot
                    same_window = (
                        display_slot
                        and self._artifact_display_slot(saved) == display_slot
                    )
                    if same_operation or same_window:
                        connection.execute(
                            "UPDATE artifacts SET payload = ?, created_at = ? WHERE id = ?",
                            (json.dumps(artifact), self._now().isoformat(), row["id"]),
                        )
                        return int(row["id"])
            cursor = connection.execute(
                "INSERT INTO artifacts(user_id, payload, created_at) VALUES (?, ?, ?)",
                (user_id, json.dumps(artifact), self._now().isoformat()),
            )
            return int(cursor.lastrowid)

    @staticmethod
    def _artifact_slot(artifact: dict) -> str | None:
        source = str(artifact.get("source", "")).strip()
        operation_id = str(artifact.get("operation_id", "")).strip()
        return f"{source}:{operation_id}" if source and operation_id else None

    @staticmethod
    def _artifact_display_slot(artifact: dict) -> str | None:
        source = str(artifact.get("source", "")).strip().casefold()
        surface = str(artifact.get("surface", "workspace")).strip().casefold()
        title = str(artifact.get("title", "")).strip().casefold()
        return f"{source}:{surface}:{title}" if source and title else None

    def artifacts(self, user_id: int) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, payload, created_at FROM artifacts WHERE user_id = ? ORDER BY id DESC",
                (user_id,),
            ).fetchall()
        artifacts = []
        visible_slots = set()
        visible_display_slots = set()
        for row in rows:
            artifact = json.loads(row["payload"])
            slot = self._artifact_slot(artifact)
            display_slot = self._artifact_display_slot(artifact)
            if (slot and slot in visible_slots) or (
                display_slot and display_slot in visible_display_slots
            ):
                continue
            if slot:
                visible_slots.add(slot)
            if display_slot:
                visible_display_slots.add(display_slot)
            artifact.update({"id": int(row["id"]), "created_at": row["created_at"]})
            artifacts.append(artifact)
        return artifacts

    def create_oauth_state(
        self,
        user_id: int,
        connector_id: str,
        minutes: int = 10,
        requested_scopes: list[str] | None = None,
    ) -> str:
        state = secrets.token_urlsafe(32)
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        expires_at = self._now() + timedelta(minutes=minutes)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO oauth_states(
                    state_hash, user_id, connector_id, requested_scopes, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    state_hash,
                    user_id,
                    connector_id,
                    json.dumps(requested_scopes or []),
                    expires_at.isoformat(),
                ),
            )
        return state

    def oauth_requested_scopes(self, user_id: int, connector_id: str, state: str) -> list[str]:
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        now = self._now().isoformat()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT requested_scopes FROM oauth_states
                WHERE state_hash = ? AND user_id = ? AND connector_id = ?
                  AND used_at IS NULL AND expires_at > ?
                """,
                (state_hash, user_id, connector_id, now),
            ).fetchone()
        if not row:
            return []
        scopes = json.loads(row["requested_scopes"])
        return [str(scope) for scope in scopes if scope]

    def consume_oauth_state(self, user_id: int, connector_id: str, state: str) -> bool:
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        now = self._now().isoformat()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE oauth_states SET used_at = ?
                WHERE state_hash = ? AND user_id = ? AND connector_id = ?
                  AND used_at IS NULL AND expires_at > ?
                """,
                (now, state_hash, user_id, connector_id, now),
            )
            return cursor.rowcount == 1

    def oauth_connector_for_state(self, user_id: int, state: str) -> str | None:
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        now = self._now().isoformat()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT connector_id FROM oauth_states
                WHERE state_hash = ? AND user_id = ? AND used_at IS NULL AND expires_at > ?
                """,
                (state_hash, user_id, now),
            ).fetchone()
        return row["connector_id"] if row else None

    def save_connection(
        self, user_id: int, connector_id: str, status: str, credentials: dict | None = None
    ) -> None:
        encrypted = None
        if credentials is not None:
            encrypted = self._cipher.encrypt(json.dumps(credentials).encode()).decode()
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT credentials FROM connections WHERE user_id = ? AND connector_id = ?",
                (user_id, connector_id),
            ).fetchone()
            if encrypted is None and existing:
                encrypted = existing["credentials"]
            connection.execute(
                """
                INSERT INTO connections(user_id, connector_id, status, credentials, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, connector_id) DO UPDATE SET
                    status = excluded.status,
                    credentials = excluded.credentials,
                    updated_at = excluded.updated_at
                """,
                (user_id, connector_id, status, encrypted, self._now().isoformat()),
            )

    def connection_status(self, user_id: int, connector_id: str) -> str | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT status FROM connections WHERE user_id = ? AND connector_id = ?",
                (user_id, connector_id),
            ).fetchone()
        return row["status"] if row else None

    def connection_credentials(self, user_id: int, connector_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT credentials FROM connections WHERE user_id = ? AND connector_id = ?",
                (user_id, connector_id),
            ).fetchone()
        if not row or not row["credentials"]:
            return None
        try:
            plaintext = self._cipher.decrypt(row["credentials"].encode())
        except InvalidToken as exc:
            raise RuntimeError("stored connector credentials cannot be decrypted") from exc
        return json.loads(plaintext)

    def save_connection_setting(
        self, user_id: int, connector_id: str, name: str, value: str
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO connection_settings(user_id, connector_id, name, value, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, connector_id, name) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (user_id, connector_id, name, value, self._now().isoformat()),
            )

    def connection_setting(self, user_id: int, connector_id: str, name: str) -> str | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT value FROM connection_settings
                WHERE user_id = ? AND connector_id = ? AND name = ?
                """,
                (user_id, connector_id, name),
            ).fetchone()
        return row["value"] if row else None

    def save_setup_card(self, user_id: int, card: dict) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO setup_cards(user_id, payload, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (user_id, json.dumps(card), self._now().isoformat()),
            )

    def setup_card(self, user_id: int) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM setup_cards WHERE user_id = ?", (user_id,)
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def clear_setup_card(self, user_id: int) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM setup_cards WHERE user_id = ?", (user_id,))
