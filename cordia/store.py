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
                """
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
        self._write_memory(user_id)

    def survey_answers(self, user_id: int) -> dict[str, str]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT field, value FROM survey_answers WHERE user_id = ?", (user_id,)
            ).fetchall()
        return {row["field"]: row["value"] for row in rows}

    def survey_complete(self, user_id: int) -> bool:
        answers = self.survey_answers(user_id)
        return all(answers.get(field) for field in SURVEY_FIELDS)

    def _write_memory(self, user_id: int) -> str:
        answers = self.survey_answers(user_id)
        sections = ["# Workspace memory", ""]
        for field in SURVEY_FIELDS:
            if field in answers:
                sections.extend((f"## {SURVEY_LABELS[field]}", "", answers[field], ""))
        memory = "\n".join(sections).rstrip() + "\n"
        directory = self.workspace_root / str(user_id)
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / "memory.md.tmp"
        destination = directory / "memory.md"
        temporary.write_text(memory, encoding="utf-8")
        temporary.replace(destination)
        return memory

    def memory_markdown(self, user_id: int) -> str:
        destination = self.workspace_root / str(user_id) / "memory.md"
        if destination.exists():
            return destination.read_text(encoding="utf-8")
        return self._write_memory(user_id)

    def add_message(self, user_id: int, role: str, content: str) -> int:
        if role not in {"user", "assistant"}:
            raise ValueError("invalid message role")
        clean = content.strip()
        if not clean:
            raise ValueError("message required")
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT INTO messages(user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (user_id, role, clean, self._now().isoformat()),
            )
            return int(cursor.lastrowid)

    def messages(self, user_id: int, limit: int = 30) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, role, content, created_at FROM (
                    SELECT id, role, content, created_at
                    FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?
                ) ORDER BY id ASC
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

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
