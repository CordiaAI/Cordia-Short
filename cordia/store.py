from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


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
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO survey_answers(user_id, field, value) VALUES (?, ?, ?)
                ON CONFLICT(user_id, field) DO UPDATE SET value = excluded.value
                """,
                (user_id, field, clean),
            )
        self._write_operator(user_id)

    def survey_answers(self, user_id: int) -> dict[str, str]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT field, value FROM survey_answers WHERE user_id = ?", (user_id,)
            ).fetchall()
        return {row["field"]: row["value"] for row in rows}

    def survey_complete(self, user_id: int) -> bool:
        answers = self.survey_answers(user_id)
        return all(answers.get(field) for field in SURVEY_FIELDS)

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
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT INTO artifacts(user_id, payload, created_at) VALUES (?, ?, ?)",
                (user_id, json.dumps(artifact), self._now().isoformat()),
            )
            return int(cursor.lastrowid)

    def artifacts(self, user_id: int) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, payload, created_at FROM artifacts WHERE user_id = ? ORDER BY id DESC",
                (user_id,),
            ).fetchall()
        artifacts = []
        for row in rows:
            artifact = json.loads(row["payload"])
            artifact.update({"id": int(row["id"]), "created_at": row["created_at"]})
            artifacts.append(artifact)
        return artifacts

    def create_oauth_state(self, user_id: int, connector_id: str, minutes: int = 10) -> str:
        state = secrets.token_urlsafe(32)
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        expires_at = self._now() + timedelta(minutes=minutes)
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO oauth_states(state_hash, user_id, connector_id, expires_at) VALUES (?, ?, ?, ?)",
                (state_hash, user_id, connector_id, expires_at.isoformat()),
            )
        return state

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
