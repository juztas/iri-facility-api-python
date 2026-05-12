"""Models for interactive session router.

Interactive sessions let users reserve a slot of nodes on a compute resource
and then send shell commands to those nodes — to one node, to all nodes, or
to a specific node — blocking or non-blocking, with per-node output capture.
"""
import datetime
from enum import Enum

from pydantic import Field, computed_field, field_validator

from ...request_context import get_url_prefix
from ...types.base import IRIBaseModel


class SessionStatus(str, Enum):
    """Lifecycle states of an interactive session."""
    pending = "pending"        # allocation requested, not yet ready
    active = "active"          # nodes allocated, ready to accept commands
    expired = "expired"        # wall-clock duration exceeded
    terminated = "terminated"  # user-requested end
    failed = "failed"          # allocation failed


class CommandStatus(str, Enum):
    """Lifecycle states of a dispatched command."""
    queued = "queued"
    running = "running"
    completed = "completed"   # all nodes returned exit_code == 0
    failed = "failed"         # at least one node returned non-zero exit_code
    cancelled = "cancelled"
    timed_out = "timed_out"


# Reserved target values; anything else is interpreted as a specific node_id.
TARGET_ONE = "one"
TARGET_ALL = "all"


class InteractiveSessionSpec(IRIBaseModel):
    """Request body for creating an interactive session."""
    node_count: int = Field(..., ge=1, le=4096, description="Number of nodes to reserve", example=2)
    duration_seconds: int = Field(..., ge=60, description="Wall-clock duration in seconds", example=3600)
    queue: str | None = Field(default=None, description="Facility queue / partition", example="interactive")
    account: str | None = Field(default=None, description="Charge account / project", example="m1234")
    constraints: dict[str, str] = Field(
        default_factory=dict,
        description="Facility-specific constraints (gpu, memory, feature, …)",
        example={"gpu": "a100"},
    )


class NodeInfo(IRIBaseModel):
    """One node belonging to an interactive session."""
    node_id: str = Field(..., description="Adapter-assigned node identifier", example="demo-node-0")
    hostname: str | None = Field(default=None, description="DNS / hostname", example="nid001234")
    state: str = Field(default="ready", description="Adapter-defined node state", example="ready")


class InteractiveSession(IRIBaseModel):
    """An interactive session: a slot of nodes the user can drive."""
    def _self_path(self) -> str:
        return f"/interactive/sessions/{self.resource_id}/{self.session_id}"

    session_id: str = Field(..., description="Unique session identifier", example="sess-abc123")
    resource_id: str = Field(..., description="Compute resource hosting the session", example="perlmutter")
    user_id: str = Field(..., description="User who owns the session", example="user-123")
    status: SessionStatus = Field(..., description="Current lifecycle state", example="active")
    spec: InteractiveSessionSpec = Field(..., description="Original request spec")
    nodes: list[NodeInfo] = Field(default_factory=list, description="Allocated nodes (populated once active)")
    job_id: str | None = Field(default=None, description="Underlying scheduler job ID, if any", example="12345.batch")

    @field_validator("created_at", "started_at", "expires_at", "ended_at", mode="before")
    @classmethod
    def _norm_dt(cls, v):
        return cls.normalize_dt(v) if v is not None else v

    created_at: datetime.datetime = Field(..., description="When the session was requested")
    started_at: datetime.datetime | None = Field(default=None, description="When the allocation became active")
    expires_at: datetime.datetime | None = Field(default=None, description="When the allocation will expire")
    ended_at: datetime.datetime | None = Field(default=None, description="When the session was terminated / expired / failed")

    @computed_field(description="URI of this session")
    @property
    def self_uri(self) -> str:
        return f"{get_url_prefix()}{self._self_path()}"

    @computed_field(description="URI of the command collection for this session")
    @property
    def commands_uri(self) -> str:
        return f"{get_url_prefix()}{self._self_path()}/commands"


class CommandSpec(IRIBaseModel):
    """Request body for dispatching a command into a session."""
    command: str = Field(..., min_length=1, description="Shell command to execute", example="hostname && uptime")
    target: str = Field(
        default=TARGET_ONE,
        description=f"'{TARGET_ONE}' (any single node), '{TARGET_ALL}' (every node), or a specific node_id",
        example=TARGET_ONE,
    )
    blocking: bool = Field(
        default=False,
        description="If true, the API waits for the command to finish (subject to timeout_seconds) before responding",
        example=False,
    )
    timeout_seconds: int | None = Field(
        default=None,
        ge=1,
        description="Per-node wall-clock timeout in seconds; the command is marked timed_out if exceeded",
        example=60,
    )
    stdin: str | None = Field(default=None, description="Optional standard input data fed to the command")
    working_dir: str | None = Field(default=None, description="Working directory in which to execute the command", example="/tmp")
    env: dict[str, str] = Field(default_factory=dict, description="Extra environment variables to inject")


class NodeOutput(IRIBaseModel):
    """Captured output from running a command on one node."""
    node_id: str = Field(..., description="Node that produced this output", example="demo-node-0")
    exit_code: int | None = Field(default=None, description="Process exit code (None if still running)", example=0)
    stdout: str = Field(default="", description="Captured standard output")
    stderr: str = Field(default="", description="Captured standard error")

    @field_validator("started_at", "completed_at", mode="before")
    @classmethod
    def _norm_dt(cls, v):
        return cls.normalize_dt(v) if v is not None else v

    started_at: datetime.datetime | None = Field(default=None, description="When the command started on this node")
    completed_at: datetime.datetime | None = Field(default=None, description="When the command finished on this node")


class Command(IRIBaseModel):
    """A command dispatched into an interactive session."""
    def _self_path(self) -> str:
        return f"/interactive/sessions/{self.resource_id}/{self.session_id}/commands/{self.command_id}"

    command_id: str = Field(..., description="Unique command identifier", example="cmd-xyz789")
    session_id: str = Field(..., description="Session the command belongs to", example="sess-abc123")
    resource_id: str = Field(..., description="Compute resource hosting the session", example="perlmutter")
    spec: CommandSpec = Field(..., description="Original dispatch spec")
    status: CommandStatus = Field(..., description="Current command status", example="running")
    targets: list[str] = Field(default_factory=list, description="Resolved node IDs the command was dispatched to")

    @field_validator("submitted_at", "started_at", "completed_at", mode="before")
    @classmethod
    def _norm_dt(cls, v):
        return cls.normalize_dt(v) if v is not None else v

    submitted_at: datetime.datetime = Field(..., description="When the command was accepted by the API")
    started_at: datetime.datetime | None = Field(default=None, description="When execution started on at least one node")
    completed_at: datetime.datetime | None = Field(default=None, description="When the last node finished")
    outputs: list[NodeOutput] = Field(default_factory=list, description="Per-node captured output")

    @computed_field(description="URI of this command")
    @property
    def self_uri(self) -> str:
        return f"{get_url_prefix()}{self._self_path()}"


class CommandList(IRIBaseModel):
    """Paginated list of commands within a session."""
    items: list[Command]
    total: int
