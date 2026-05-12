"""Persistence abstraction for interactive sessions and commands.

`InteractiveStore` is the integration point for facility-specific storage.
The reference adapter ships `InMemoryInteractiveStore`; facilities are
expected to subclass `InteractiveStore` and back it with whatever they
prefer (Postgres, MySQL, SQLite, Redis, etcd, …).

The interface is intentionally small and CRUD-shaped so it can be mapped
onto almost any storage engine without introducing a heavy ORM layer.
"""
import asyncio
from abc import ABC, abstractmethod

from .models import (
    Command,
    CommandStatus,
    InteractiveSession,
    NodeOutput,
    SessionStatus,
)


class InteractiveStore(ABC):
    """Storage abstraction for interactive sessions, commands, and outputs.

    Implementations may be synchronous internally — the async interface lets
    facilities back this with a real network database without blocking the
    event loop.
    """

    # -- sessions --------------------------------------------------------

    @abstractmethod
    async def save_session(self, session: InteractiveSession) -> None:
        """Insert or replace a session by `session_id`."""

    @abstractmethod
    async def get_session(self, session_id: str) -> InteractiveSession | None:
        """Return the session with this id, or None."""

    @abstractmethod
    async def list_sessions(
        self,
        *,
        user_id: str,
        resource_id: str | None = None,
        status: SessionStatus | None = None,
    ) -> list[InteractiveSession]:
        """Return sessions owned by `user_id`, optionally filtered."""

    @abstractmethod
    async def delete_session(self, session_id: str) -> None:
        """Delete a session and all its commands. No-op if missing."""

    # -- commands --------------------------------------------------------

    @abstractmethod
    async def save_command(self, command: Command) -> None:
        """Insert or replace a command by `command_id`."""

    @abstractmethod
    async def get_command(self, command_id: str) -> Command | None:
        """Return the command with this id, or None."""

    @abstractmethod
    async def list_commands(
        self,
        session_id: str,
        *,
        status: CommandStatus | None = None,
    ) -> list[Command]:
        """Return commands belonging to a session, optionally filtered."""

    @abstractmethod
    async def append_output(self, command_id: str, output: NodeOutput) -> None:
        """Append a per-node output record to a command.

        Implementations should upsert by `(command_id, node_id)` so that
        partial output updates (e.g. stdout written while the command is
        still running) overwrite the prior partial.
        """


class InMemoryInteractiveStore(InteractiveStore):
    """In-process reference implementation; suitable for dev / demo / tests.

    Uses an asyncio lock so concurrent coroutines that append outputs and
    update statuses on the same command don't race each other.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, InteractiveSession] = {}
        self._commands: dict[str, Command] = {}
        self._lock = asyncio.Lock()

    # -- sessions --------------------------------------------------------

    async def save_session(self, session: InteractiveSession) -> None:
        async with self._lock:
            self._sessions[session.session_id] = session

    async def get_session(self, session_id: str) -> InteractiveSession | None:
        async with self._lock:
            return self._sessions.get(session_id)

    async def list_sessions(
        self,
        *,
        user_id: str,
        resource_id: str | None = None,
        status: SessionStatus | None = None,
    ) -> list[InteractiveSession]:
        async with self._lock:
            sessions = [s for s in self._sessions.values() if s.user_id == user_id]
        if resource_id is not None:
            sessions = [s for s in sessions if s.resource_id == resource_id]
        if status is not None:
            sessions = [s for s in sessions if s.status == status]
        return sorted(sessions, key=lambda s: s.created_at, reverse=True)

    async def delete_session(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)
            for cmd_id in [cid for cid, c in self._commands.items() if c.session_id == session_id]:
                self._commands.pop(cmd_id, None)

    # -- commands --------------------------------------------------------

    async def save_command(self, command: Command) -> None:
        async with self._lock:
            self._commands[command.command_id] = command

    async def get_command(self, command_id: str) -> Command | None:
        async with self._lock:
            return self._commands.get(command_id)

    async def list_commands(
        self,
        session_id: str,
        *,
        status: CommandStatus | None = None,
    ) -> list[Command]:
        async with self._lock:
            cmds = [c for c in self._commands.values() if c.session_id == session_id]
        if status is not None:
            cmds = [c for c in cmds if c.status == status]
        return sorted(cmds, key=lambda c: c.submitted_at)

    async def append_output(self, command_id: str, output: NodeOutput) -> None:
        async with self._lock:
            cmd = self._commands.get(command_id)
            if cmd is None:
                return
            for i, existing in enumerate(cmd.outputs):
                if existing.node_id == output.node_id:
                    cmd.outputs[i] = output
                    return
            cmd.outputs.append(output)
