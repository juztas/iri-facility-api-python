"""Backend-agnostic local task queue helpers for the reference API.

Facilities should treat this module as an extension seam: swap the backend
selection to Redis, RabbitMQ, SQS, NATS, or another local adapter without
changing the API-facing task contract.
"""
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import tempfile
import time
import uuid
from abc import ABC, abstractmethod
from contextlib import closing
from dataclasses import dataclass

from ...types.user import User
from ..status import models as status_models
from . import models as task_models


def _default_sqlite_path() -> str:
    return os.path.join(tempfile.gettempdir(), "iri-local-task-queue.sqlite3")


@dataclass(frozen=True)
class QueueSettings:
    backend: str
    sqlite_path: str
    memory_namespace: str
    lease_seconds: int

    @classmethod
    def from_env(cls) -> "QueueSettings":
        return cls(
            backend=os.environ.get("IRI_TASK_QUEUE_BACKEND", "memory").strip().lower() or "memory",
            sqlite_path=os.environ.get("IRI_TASK_QUEUE_SQLITE_PATH", _default_sqlite_path()),
            memory_namespace=os.environ.get("IRI_TASK_QUEUE_MEMORY_NAMESPACE", "default"),
            lease_seconds=max(1, int(os.environ.get("IRI_TASK_QUEUE_LEASE_SECONDS", "300"))),
        )


class QueueTaskLease(task_models.Task):
    """A queued task plus the worker context needed to execute it."""

    user: User
    resource: status_models.Resource | None = None


class TaskQueueBackend(ABC):
    """Common interface for demo and facility queue backends."""

    @abstractmethod
    def enqueue(
        self,
        *,
        user: User,
        resource: status_models.Resource | None,
        task: task_models.TaskCommand,
    ) -> task_models.TaskSubmitResponse:
        pass

    @abstractmethod
    def get_task(self, *, user: User, task_id: str) -> task_models.Task | None:
        pass

    @abstractmethod
    def list_tasks(self, *, user: User) -> list[task_models.Task]:
        pass

    @abstractmethod
    def cancel_task(self, *, user: User, task_id: str) -> None:
        pass

    @abstractmethod
    def claim_next(self, *, worker_id: str, lease_seconds: int) -> QueueTaskLease | None:
        pass

    @abstractmethod
    def complete_task(
        self,
        *,
        task_id: str,
        status: task_models.TaskStatus,
        result: dict | None,
    ) -> None:
        pass


@dataclass
class _MemoryTaskRecord:
    id: str
    command: task_models.TaskCommand
    user: User
    resource: status_models.Resource | None
    created_at: float
    updated_at: float
    status: task_models.TaskStatus = task_models.TaskStatus.pending
    result: dict | None = None
    claimed_by: str | None = None
    leased_until: float | None = None


class MemoryTaskQueue(TaskQueueBackend):
    """Simple in-process queue for demo and unit tests."""

    def __init__(self, namespace: str) -> None:
        self.namespace = namespace
        self._tasks: list[_MemoryTaskRecord] = []

    def enqueue(
        self,
        *,
        user: User,
        resource: status_models.Resource | None,
        task: task_models.TaskCommand,
    ) -> task_models.TaskSubmitResponse:
        now = time.time()
        task_id = f"task-{uuid.uuid4().hex[:12]}"
        self._tasks.append(
            _MemoryTaskRecord(
                id=task_id,
                command=task,
                user=user,
                resource=resource,
                created_at=now,
                updated_at=now,
            )
        )
        return task_models.TaskSubmitResponse(task_id=task_id)

    def get_task(self, *, user: User, task_id: str) -> task_models.Task | None:
        for task in self._tasks:
            if task.id == task_id and task.user.name == user.name:
                return _task_from_record(task)
        return None

    def list_tasks(self, *, user: User) -> list[task_models.Task]:
        return [
            _task_from_record(task)
            for task in sorted(self._tasks, key=lambda item: item.created_at, reverse=True)
            if task.user.name == user.name
        ]

    def cancel_task(self, *, user: User, task_id: str) -> None:
        now = time.time()
        for task in self._tasks:
            if task.id == task_id and task.user.name == user.name and task.status in {task_models.TaskStatus.pending, task_models.TaskStatus.active}:
                task.status = task_models.TaskStatus.canceled
                task.result = None
                task.updated_at = now
                task.leased_until = None
                break

    def claim_next(self, *, worker_id: str, lease_seconds: int) -> QueueTaskLease | None:
        now = time.time()
        for task in sorted(self._tasks, key=lambda item: item.created_at):
            if task.status == task_models.TaskStatus.pending and (task.leased_until is None or task.leased_until < now):
                task.status = task_models.TaskStatus.active
                task.updated_at = now
                task.claimed_by = worker_id
                task.leased_until = now + lease_seconds
                return _lease_from_record(task)
        return None

    def complete_task(
        self,
        *,
        task_id: str,
        status: task_models.TaskStatus,
        result: dict | None,
    ) -> None:
        now = time.time()
        for task in self._tasks:
            if task.id == task_id:
                task.status = status
                task.result = result
                task.updated_at = now
                task.leased_until = None
                break


class SqliteTaskQueue(TaskQueueBackend):
    """Small durable local queue example backed by SQLite."""

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
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    user_name TEXT NOT NULL,
                    command_json TEXT NOT NULL,
                    user_json TEXT NOT NULL,
                    resource_json TEXT,
                    result_json TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    claimed_by TEXT,
                    leased_until REAL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON tasks(status, created_at)")

    def enqueue(
        self,
        *,
        user: User,
        resource: status_models.Resource | None,
        task: task_models.TaskCommand,
    ) -> task_models.TaskSubmitResponse:
        task_id = f"task-{uuid.uuid4().hex[:12]}"
        now = time.time()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    id, status, command_json, user_json, resource_json, result_json,
                    created_at, updated_at, claimed_by, leased_until, user_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    task_models.TaskStatus.pending.value,
                    task.model_dump_json(),
                    user.model_dump_json(),
                    json.dumps(_serialize_resource(resource)) if resource is not None else None,
                    None,
                    now,
                    now,
                    None,
                    None,
                    user.name,
                ),
            )
        return task_models.TaskSubmitResponse(task_id=task_id)

    def get_task(self, *, user: User, task_id: str) -> task_models.Task | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT id, status, result_json, command_json FROM tasks WHERE id = ? AND user_name = ?",
                (task_id, user.name),
            ).fetchone()
        return _task_from_row(row)

    def list_tasks(self, *, user: User) -> list[task_models.Task]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT id, status, result_json, command_json
                FROM tasks
                WHERE user_name = ?
                ORDER BY created_at DESC
                """,
                (user.name,),
            ).fetchall()
        return [task for row in rows if (task := _task_from_row(row)) is not None]

    def cancel_task(self, *, user: User, task_id: str) -> None:
        now = time.time()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?, result_json = NULL, leased_until = NULL
                WHERE id = ? AND user_name = ? AND status IN (?, ?)
                """,
                (
                    task_models.TaskStatus.canceled.value,
                    now,
                    task_id,
                    user.name,
                    task_models.TaskStatus.pending.value,
                    task_models.TaskStatus.active.value,
                ),
            )

    def claim_next(self, *, worker_id: str, lease_seconds: int) -> QueueTaskLease | None:
        now = time.time()
        lease_until = now + lease_seconds
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT *
                FROM tasks
                WHERE status = ?
                  AND (leased_until IS NULL OR leased_until < ?)
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (task_models.TaskStatus.pending.value, now),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?, claimed_by = ?, leased_until = ?
                WHERE id = ?
                """,
                (task_models.TaskStatus.active.value, now, worker_id, lease_until, row["id"]),
            )
            conn.execute("COMMIT")
        return _lease_from_row(row)

    def complete_task(
        self,
        *,
        task_id: str,
        status: task_models.TaskStatus,
        result: dict | None,
    ) -> None:
        now = time.time()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?, result_json = ?, leased_until = NULL
                WHERE id = ?
                """,
                (status.value, now, json.dumps(result) if result is not None else None, task_id),
            )


_QUEUE_CACHE: dict[tuple[str, str], TaskQueueBackend] = {}


def get_task_queue(*, backend: str | None = None) -> TaskQueueBackend:
    settings = QueueSettings.from_env()
    selected_backend = (backend or settings.backend).strip().lower()
    cache_key = (selected_backend, settings.sqlite_path if selected_backend == "sqlite" else settings.memory_namespace)
    queue = _QUEUE_CACHE.get(cache_key)
    if queue is not None:
        return queue

    if selected_backend == "memory":
        queue = MemoryTaskQueue(settings.memory_namespace)
    elif selected_backend == "sqlite":
        queue = SqliteTaskQueue(settings.sqlite_path)
    else:
        raise ValueError(
            f"Unsupported task queue backend: {selected_backend!r}. "
            "Supported examples in the reference API are 'memory' and 'sqlite'."
        )

    _QUEUE_CACHE[cache_key] = queue
    return queue


def _task_from_record(task: _MemoryTaskRecord) -> task_models.Task:
    return task_models.Task(
        id=task.id,
        status=task.status,
        result=task.result,
        command=task.command,
    )


def _lease_from_record(task: _MemoryTaskRecord) -> QueueTaskLease:
    return QueueTaskLease(
        id=task.id,
        status=task.status,
        result=task.result,
        command=task.command,
        user=task.user,
        resource=task.resource,
    )


def _task_from_row(row: sqlite3.Row | None) -> task_models.Task | None:
    if row is None:
        return None
    return task_models.Task(
        id=row["id"],
        status=task_models.TaskStatus(row["status"]),
        result=json.loads(row["result_json"]) if row["result_json"] else None,
        command=task_models.TaskCommand.model_validate_json(row["command_json"]),
    )


def _lease_from_row(row: sqlite3.Row) -> QueueTaskLease:
    return QueueTaskLease(
        id=row["id"],
        status=task_models.TaskStatus.active,
        result=json.loads(row["result_json"]) if row["result_json"] else None,
        command=task_models.TaskCommand.model_validate_json(row["command_json"]),
        user=User.model_validate_json(row["user_json"]),
        resource=_deserialize_resource(row["resource_json"]),
    )


def _serialize_resource(resource: status_models.Resource) -> dict:
    data = resource.model_dump(mode="json")
    data["site_id"] = resource.site_id
    data["capability_ids"] = list(resource.capability_ids)
    return data


def _deserialize_resource(resource_json: str | None) -> status_models.Resource | None:
    if not resource_json:
        return None
    return status_models.Resource.model_validate(json.loads(resource_json))
