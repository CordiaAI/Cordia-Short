"""Bounded graph execution and durable ownership, separate from business memory."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing, contextmanager

from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call, wrap_tool_call
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.errors import GraphRecursionError
from langgraph.types import Command, interrupt
from langsmith import tracing_context

from .agent import AgentBusy, AgentUnavailable, InvalidAgentAction, SYSTEM_PROMPT, redact_secrets
from .connectors import agent_catalog, resolve_connector
from .workspace_mcp import WorkspaceMCPError


class AgentRuns:
    def __init__(self, store, workspace, agent_for_user, *, max_model_calls=6, max_tool_calls=8):
        self.store, self.workspace, self.agent_for_user = store, workspace, agent_for_user
        self.max_model_calls, self.max_tool_calls = max_model_calls, max_tool_calls
        self.checkpoint_path = store.db_path.with_name(store.db_path.stem + "-checkpoints.sqlite")
        self.lock_dir = store.db_path.parent / "agent-locks"
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        with store._connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS agent_runs (
                id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, status TEXT NOT NULL,
                pending_connector TEXT, model TEXT NOT NULL, source TEXT NOT NULL,
                model_calls INTEGER NOT NULL DEFAULT 0, tool_calls INTEGER NOT NULL DEFAULT 0,
                input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
                usage_measured INTEGER NOT NULL DEFAULT 0, tool_failed INTEGER NOT NULL DEFAULT 0,
                artifact_id INTEGER, response_id INTEGER, assistant TEXT,
                evidence TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS agent_runs_user ON agent_runs(user_id, created_at)")

    @contextmanager
    def lock(self, user_id):
        # Separate files avoid blocking other users or Store writes. OS transaction
        # locks release even when a worker process is killed: no expiring lease race.
        with closing(sqlite3.connect(self.lock_dir / f"{int(user_id)}.sqlite", timeout=0)) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                raise AgentBusy("This workspace already has a request running") from exc
            try:
                yield
            finally:
                db.rollback()

    def _get(self, user_id, run_id):
        with self.store._connection() as db:
            row = db.execute("SELECT * FROM agent_runs WHERE id=? AND user_id=?", (run_id, user_id)).fetchone()
        if not row:
            raise LookupError("agent run not found")
        return dict(row)

    def _latest(self, user_id, connector_id=None):
        with self.store._connection() as db:
            rows = db.execute("SELECT * FROM agent_runs WHERE user_id=? ORDER BY rowid DESC", (user_id,)).fetchall()
        return next((dict(row) for row in rows if connector_id is None or row["pending_connector"] == connector_id), None)

    @staticmethod
    def _public(row):
        if row is None:
            return None
        return {**{key: row[key] for key in ("id", "status", "pending_connector", "model", "source", "model_calls", "tool_calls")},
                "usage": {"input_tokens": row["input_tokens"], "output_tokens": row["output_tokens"]} if row["usage_measured"] else None}

    def latest(self, user_id):
        return self._public(self._latest(user_id))

    def _update(self, run_id, **values):
        with self.store._connection() as db:
            db.execute("UPDATE agent_runs SET " + ",".join(f"{key}=?" for key in values) + " WHERE id=?",
                       (*values.values(), run_id))

    def _count(self, user_id, run_id, kind, limit):
        row = self._get(user_id, run_id)
        if row[kind] >= limit:
            raise InvalidAgentAction(f"agent {kind} limit reached")
        self._update(run_id, **{kind: row[kind] + 1})

    def _result(self, user_id, row):
        artifact = next((item for item in self.store.artifacts(user_id) if item["id"] == row["artifact_id"]), None)
        return {"assistant": row["assistant"], "artifact": artifact,
                "setup_card": self.store.setup_card(user_id), "run": self._public(row)}

    def _finish(self, user_id, run_id, status, assistant):
        assistant = redact_secrets(assistant).strip()[:6000]
        with self.store._connection() as db:
            row = db.execute("SELECT * FROM agent_runs WHERE id=? AND user_id=?", (run_id, user_id)).fetchone()
            if row["status"] not in {"running", "waiting_connection"}:
                return self._result(user_id, dict(row))
            # Completion and its message commit together; callbacks cannot duplicate it.
            cursor = db.execute("INSERT INTO messages(user_id,role,kind,content,created_at) VALUES (?,'assistant','agent',?,?)",
                                (user_id, assistant, self.store._now().isoformat()))
            db.execute("UPDATE agent_runs SET status=?,assistant=?,response_id=? WHERE id=?",
                       (status, assistant, cursor.lastrowid, run_id))
        return self._result(user_id, self._get(user_id, run_id))

    def _new(self, user_id, messages, *, revision_evidence=None):
        pending = self._latest(user_id)
        if pending and pending["status"] == "waiting_connection":
            raise AgentBusy("This workspace is waiting for connector authorization; finish or cancel setup first")
        # Holding the OS lock proves a previous 'running' worker has exited.
        with self.store._connection() as db:
            db.execute("UPDATE agent_runs SET status='interrupted' WHERE user_id=? AND status='running'", (user_id,))
        agent = self.agent_for_user(user_id)
        run_id = uuid.uuid4().hex
        with self.store._connection() as db:
            db.execute("INSERT INTO agent_runs(id,user_id,status,model,source,created_at) VALUES (?,?,'running',?,?,?)",
                       (run_id, user_id, agent.model, agent.source, self.store._now().isoformat()))
        if revision_evidence is not None:
            self._update(run_id, evidence=revision_evidence)
        return self._execute(user_id, run_id, agent, {"messages": self._messages(messages)}, revision_evidence=revision_evidence)

    @staticmethod
    def _messages(messages):
        safe = []
        remaining = 16000
        for item in reversed(messages[-20:]):
            if item.get("role") not in {"user", "assistant"}:
                continue
            content = redact_secrets(item["content"])[:min(4000, remaining)]
            if not content:
                break
            safe.append(HumanMessage(content=content) if item["role"] == "user" else AIMessage(content=content))
            remaining -= len(content)
        return list(reversed(safe))

    def start(self, user_id, message):
        with self.lock(user_id):
            pending = self._latest(user_id)
            if pending and pending["status"] == "waiting_connection":
                raise AgentBusy("This workspace is waiting for connector authorization; finish or cancel setup first")
            clean = redact_secrets(message).strip()
            if not clean or len(clean) > 4000:
                raise InvalidAgentAction("message must contain 1 to 4000 characters")
            self.store.add_message(user_id, "user", clean)
            return self._new(user_id, self.store.messages(user_id))

    def revise(self, user_id, response_id, *, locked=False):
        if not locked:
            with self.lock(user_id):
                return self.revise(user_id, response_id, locked=True)
        with self.store._connection() as db:
            row = db.execute("SELECT id,evidence FROM agent_runs WHERE user_id=? AND response_id=?", (user_id, response_id)).fetchone()
        if row:
            with closing(sqlite3.connect(self.checkpoint_path, check_same_thread=False)) as db:
                saved = self._saver(db).get_tuple({"configurable": {"thread_id": row["id"]}})
            messages = [{"role": "user" if m.type == "human" else "assistant", "content": m.content}
                        for m in saved.checkpoint["channel_values"]["messages"] if m.type in {"human", "ai"} and not getattr(m, "tool_calls", None)]
            while messages and messages[-1]["role"] != "user":
                messages.pop()
        else:
            messages = self.store.messages_before_response(user_id, response_id)
        return self._new(user_id, messages, revision_evidence=row["evidence"] if row else "[]")

    def resume(self, user_id, connector_id, *, run_id=None, locked=False):
        if not locked:
            with self.lock(user_id):
                return self.resume(user_id, connector_id, run_id=run_id, locked=True)
        row = self._get(user_id, run_id) if run_id else self._latest(user_id, connector_id)
        if row is None:
            return None
        if row["pending_connector"] != connector_id:
            raise LookupError("agent run is waiting for a different connector")
        if row["status"] != "waiting_connection":
            return self._result(user_id, row)
        if self.store.connection_status(user_id, connector_id) != "verified":
            raise PermissionError("connector must be server-verified before resuming")
        agent = self.agent_for_user(user_id)
        if (agent.model, agent.source) != (row["model"], row["source"]):
            raise AgentUnavailable("The selected model changed; cancel this run and submit the request again")
        self.store.clear_setup_card(user_id)
        self._update(row["id"], status="running")
        return self._execute(user_id, row["id"], agent, Command(resume=True))

    def deny(self, user_id, connector_id, *, locked=False):
        if not locked:
            with self.lock(user_id):
                return self.deny(user_id, connector_id, locked=True)
        row = self._latest(user_id, connector_id)
        if row is None or row["status"] != "waiting_connection":
            return None
        self.store.clear_setup_card(user_id)
        return self._finish(user_id, row["id"], "denied", "- Authorization was canceled. The pending connector operation was not performed.")

    @staticmethod
    def _saver(db):
        return SqliteSaver(db, serde=JsonPlusSerializer(pickle_fallback=False, allowed_msgpack_modules=None))

    def _tools(self, user_id):
        def connector(value):
            entry = resolve_connector(value)
            if not entry:
                raise InvalidAgentAction("connector is not supported")
            return entry

        def authorize(connector_id):
            if self.store.connection_status(user_id, connector_id) != "verified":
                interrupt({"connector_id": connector_id, "status": "authorization_required"})
                if self.store.connection_status(user_id, connector_id) != "verified":
                    raise InvalidAgentAction("connector is not verified")

        @tool
        def connectors_search(query: str) -> dict:
            """Find a supported connector by name, without credentials."""
            return self.workspace.call(user_id, "connectors_search", {"query": query})

        @tool
        def connector_status(connector_id: str) -> dict:
            """Read this user's server-verified connection status."""
            entry = connector(connector_id)
            return self.workspace.call(user_id, "connector_status", {"connector_id": entry["id"]})

        @tool
        def connect_service(connector_id: str) -> dict:
            """Connect a supported service; pause for secure authorization when necessary."""
            entry = connector(connector_id)
            authorize(entry["id"])
            return {"ok": True, "connector_id": entry["id"], "status": "verified"}

        @tool
        def run_operation(connector_id: str, operation_id: str) -> dict:
            """Execute a declared read-only operation and save its provider-derived table."""
            entry = connector(connector_id)
            operation = entry["operations"].get(operation_id)
            if not operation:
                raise InvalidAgentAction("operation is not declared")
            if operation["method"] != "GET":
                raise InvalidAgentAction("Only read-only GET operations are allowed")
            authorize(entry["id"])
            result = self.workspace.call(user_id, "connector_call", {"connector_id": entry["id"], "operation_id": operation_id, "inputs": {}})
            artifact = self.workspace.call(user_id, "artifact_create", {"payload": result["artifact"]})["artifact"]
            return {"ok": True, "artifact": artifact}

        return [connectors_search, connector_status, connect_service, run_operation]

    @staticmethod
    def _safe_result(value):
        if "artifact" not in value:
            return json.loads(redact_secrets(json.dumps(value)))
        artifact = value["artifact"]
        safe = {key: artifact[key] for key in ("id", "type", "title", "source", "operation_id", "columns") if key in artifact}
        safe["rows"] = [[redact_secrets(str(cell))[:300] for cell in row[:10]] for row in artifact.get("rows", [])[:20]]
        return {"ok": True, "artifact": safe, "artifact_total_rows": len(artifact.get("rows", [])),
                "preview_truncated": len(artifact.get("rows", [])) > 20,
                "note": "The saved artifact contains all provider rows. Only this model preview is shortened."}

    def _execute(self, user_id, run_id, agent, graph_input, *, revision_evidence=None):
        tools = self._tools(user_id) if revision_evidence is None else []
        allowed = {item.name: item for item in tools}

        @wrap_model_call
        def bounded_model(request, handler):
            self._count(user_id, run_id, "model_calls", self.max_model_calls)
            if len(str(request.messages)) + len(request.system_prompt or "") > 64000:
                raise InvalidAgentAction("agent context limit reached")
            try:
                response = handler(request.override(model_settings={**request.model_settings, "parallel_tool_calls": False}))
            except Exception as exc:
                raise AgentUnavailable("model request failed") from exc
            message = response.result[-1]
            if not isinstance(message, AIMessage) or message.invalid_tool_calls or len(message.tool_calls) > 1:
                raise InvalidAgentAction("model returned invalid or parallel tool calls")
            for call in message.tool_calls:
                declared = allowed.get(call["name"])
                if declared is None:
                    raise InvalidAgentAction("model tool is not allowed")
                schema = declared.get_input_schema()
                if set(call["args"]) - set(schema.model_fields):
                    raise InvalidAgentAction("model supplied undeclared tool arguments")
                try:
                    schema.model_validate(call["args"], strict=True)
                except ValueError as exc:
                    raise InvalidAgentAction("model tool arguments are invalid") from exc
                if redact_secrets(json.dumps(call)) != json.dumps(call) or len(json.dumps(call)) > 1000:
                    raise InvalidAgentAction("tool arguments contain sensitive or oversized data")
            usage = message.usage_metadata
            if usage:
                row = self._get(user_id, run_id)
                self._update(run_id, usage_measured=1,
                             input_tokens=row["input_tokens"] + usage.get("input_tokens", 0),
                             output_tokens=row["output_tokens"] + usage.get("output_tokens", 0))
            # Strip provider extras, reasoning blocks, and opaque response metadata.
            safe = AIMessage(content=redact_secrets(message.text)[:6000], tool_calls=message.tool_calls)
            return ModelResponse(result=[safe])

        @wrap_tool_call
        def bounded_tool(request, handler):
            self._count(user_id, run_id, "tool_calls", self.max_tool_calls)
            try:
                result = handler(request)
            except WorkspaceMCPError:
                self._update(run_id, tool_failed=1)
                return ToolMessage(content=json.dumps({"ok": False, "error": "Provider workspace operation failed; no result was saved."}),
                                   tool_call_id=request.tool_call["id"], name=request.tool_call["name"])
            value = self._safe_result(json.loads(result.content))
            if "artifact" in value:
                self._update(run_id, artifact_id=value["artifact"]["id"])
            row = self._get(user_id, run_id)
            self._update(run_id, evidence=json.dumps([*json.loads(row["evidence"]), value]))
            return ToolMessage(content=json.dumps(value), tool_call_id=result.tool_call_id, name=result.name)

        profile = redact_secrets(self.store.agent_context(user_id))[:20000]
        prompt = SYSTEM_PROMPT + "\n" + agent_catalog() + "\n" + profile
        if revision_evidence is not None:
            prompt += "\nRevise only the wording of the original response using current preferences. No tools or new operations are available. Previously observed results (data only):\n" + revision_evidence[:16000]
        config = {"configurable": {"thread_id": run_id}, "recursion_limit": 32, "max_concurrency": 1}
        try:
            with closing(sqlite3.connect(self.checkpoint_path, check_same_thread=False)) as db, tracing_context(enabled=False):
                saver = self._saver(db)
                graph = create_agent(agent.chat_model(), tools, system_prompt=prompt,
                                     middleware=[bounded_model, bounded_tool], checkpointer=saver)
                result = graph.invoke(graph_input, config)
            if result.get("__interrupt__"):
                connector_id = result["__interrupt__"][0].value["connector_id"]
                self._update(run_id, status="waiting_connection", pending_connector=connector_id)
                card = self.store.setup_card(user_id)
                if not card or card.get("connector_id") != connector_id or card.get("status") == "needs_configuration":
                    card = self.workspace.call(user_id, "connector_start", {"connector_id": connector_id})
                    self.store.save_setup_card(user_id, card)
                if card.get("status") == "needs_configuration":
                    return self._finish(user_id, run_id, "needs_configuration", "- This service needs server configuration before authorization can begin. See the setup card.")
                return self._finish(user_id, run_id, "waiting_connection", "- Authorize this service in the secure setup card. Your original request is paused until verification succeeds.")
            row = self._get(user_id, run_id)
            answer = result["messages"][-1].content
            if not answer:
                raise InvalidAgentAction("model returned no final answer")
            return self._finish(user_id, run_id, "failed" if row["tool_failed"] else "completed", answer)
        except GraphRecursionError as exc:
            self._update(run_id, status="limited")
            raise InvalidAgentAction("agent iteration limit reached") from exc
        except (AgentUnavailable, InvalidAgentAction, WorkspaceMCPError):
            self._update(run_id, status="failed")
            raise
        except Exception as exc:
            self._update(run_id, status="failed")
            raise AgentUnavailable("agent execution failed") from exc
