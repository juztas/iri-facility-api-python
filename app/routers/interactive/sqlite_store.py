"""SQLite-backed interactive session store for local worker compatibility."""
from __future__ import annotations

import os
import pathlib
import sqlite3
import tempfile
from contextlib import closing

from .models import Command, CommandStatus, InteractiveSession, NodeOutput, SessionStatus
from .store import InteractiveStore


def _default_sqlite_path() -> str:
    return os.path.join(tempfile.gettempdir(), "iri-interactive-store.sqlite3")


class SqliteInteractiveStore(InteractiveStore):
    """Shared store so API and local workers see the same interactive state."""

    def __init__(self, path: str) -> None:
        self.path = path
        pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS interactive_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS interactive_commands (
                    command_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_interactive_sessions_user_resource ON interactive_sessions(user_id, resource_id, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_interactive_commands_session_submitted ON interactive_commands(session_id, submitted_at)"
            )

    async def save_session(self, session: InteractiveSession) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO interactive_sessions (session_id, user_id, resource_id, status, created_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    resource_id = excluded.resource_id,
                    status = excluded.status,
                    created_at = excluded.created_at,
                    payload_json = excluded.payload_json
                """,
                (
                    session.session_id,
                    session.user_id,
                    session.resource_id,
                    session.status.value,
                    session.created_at.isoformat(),
                    session.model_dump_json(),
                ),
            )

    async def get_session(self, session_id: str) -> InteractiveSession | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT payload_json FROM interactive_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return InteractiveSession.model_validate_json(row["payload_json"]) if row else None

    async def list_sessions(
        self,
        *,
        user_id: str,
        resource_id: str | None = None,
        status: SessionStatus | None = None,
    ) -> list[InteractiveSession]:
        query = "SELECT payload_json FROM interactive_sessions WHERE user_id = ?"
        params: list[object] = [user_id]
        if resource_id is not None:
            query += " AND resource_id = ?"
            params.append(resource_id)
        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        query += " ORDER BY created_at DESC"
        with closing(self._connect()) as conn:
            rows = conn.execute(query, params).fetchall()
        return [InteractiveSession.model_validate_json(row["payload_json"]) for row in rows]

    async def delete_session(self, session_id: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM interactive_commands WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM interactive_sessions WHERE session_id = ?", (session_id,))

    async def save_command(self, command: Command) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO interactive_commands (command_id, session_id, status, submitted_at, payload_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(command_id) DO UPDATE SET
                    session_id = excluded.session_id,
                    status = excluded.status,
                    submitted_at = excluded.submitted_at,
                    payload_json = excluded.payload_json
                """,
                (
                    command.command_id,
                    command.session_id,
                    command.status.value,
                    command.submitted_at.isoformat(),
                    command.model_dump_json(),
                ),
            )

    async def get_command(self, command_id: str) -> Command | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT payload_json FROM interactive_commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
        return Command.model_validate_json(row["payload_json"]) if row else None

    async def list_commands(
        self,
        session_id: str,
        *,
        status: CommandStatus | None = None,
    ) -> list[Command]:
        query = "SELECT payload_json FROM interactive_commands WHERE session_id = ?"
        params: list[object] = [session_id]
        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        query += " ORDER BY submitted_at ASC"
        with closing(self._connect()) as conn:
            rows = conn.execute(query, params).fetchall()
        return [Command.model_validate_json(row["payload_json"]) for row in rows]

    async def append_output(self, command_id: str, output: NodeOutput) -> None:
        command = await self.get_command(command_id)
        if command is None:
            return
        for i, existing in enumerate(command.outputs):
            if existing.node_id == output.node_id:
                command.outputs[i] = output
                break
        else:
            command.outputs.append(output)
        await self.save_command(command)


_STORE_CACHE: dict[str, SqliteInteractiveStore] = {}


def build_sqlite_store() -> SqliteInteractiveStore:
    path = os.environ.get("IRI_INTERACTIVE_STORE_SQLITE_PATH", _default_sqlite_path())
    store = _STORE_CACHE.get(path)
    if store is None:
        store = SqliteInteractiveStore(path)
        _STORE_CACHE[path] = store
    return store
