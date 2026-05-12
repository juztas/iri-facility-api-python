"""Abstract facility adapter for interactive sessions.

Facility-specific implementations bridge between the IRI API and whatever
runs the actual workload — SLURM `salloc`, Kubernetes Jobs, plain SSH to a
worker pool, etc. The adapter is responsible for:

  * allocating / releasing slots on a compute resource,
  * resolving "one / all / <node_id>" targets to concrete nodes,
  * launching commands and capturing their output,
  * persisting session and command state through an `InteractiveStore`.

The adapter chooses its own store; the demo implementation uses an
in-memory store, real facilities will typically use a database.
"""
from abc import abstractmethod

from ...types.user import User
from ..iri_router import AuthenticatedAdapter
from ..status import models as status_models
from . import models as interactive_models


class FacilityAdapter(AuthenticatedAdapter):
    """
    Facility-specific code is handled by the implementation of this interface.
    Use the `IRI_API_ADAPTER_interactive` environment variable
    (defaults to `app.demo_adapter.DemoAdapter`) to install your facility
    adapter before the API starts.
    """

    @abstractmethod
    async def create_session(
        self: "FacilityAdapter",
        resource: status_models.Resource,
        user: User,
        spec: interactive_models.InteractiveSessionSpec,
    ) -> interactive_models.InteractiveSession:
        """Reserve a slot of nodes on `resource` for `user`."""

    @abstractmethod
    async def get_session(
        self: "FacilityAdapter",
        resource: status_models.Resource,
        user: User,
        session_id: str,
    ) -> interactive_models.InteractiveSession:
        """Return one session owned by `user` on `resource`."""

    @abstractmethod
    async def list_sessions(
        self: "FacilityAdapter",
        resource: status_models.Resource,
        user: User,
    ) -> list[interactive_models.InteractiveSession]:
        """Return all of the user's sessions on `resource`."""

    @abstractmethod
    async def end_session(
        self: "FacilityAdapter",
        resource: status_models.Resource,
        user: User,
        session_id: str,
    ) -> None:
        """Terminate a session, cancelling any running commands."""

    @abstractmethod
    async def dispatch_command(
        self: "FacilityAdapter",
        resource: status_models.Resource,
        user: User,
        session_id: str,
        spec: interactive_models.CommandSpec,
    ) -> interactive_models.Command:
        """
        Dispatch a command into a session.

        If `spec.blocking` is True, the returned Command should already have
        a terminal `status` (completed/failed/timed_out) and populated
        `outputs`. Otherwise the command should be returned with status
        `queued` or `running` and the adapter must update the store as the
        command progresses.
        """

    @abstractmethod
    async def get_command(
        self: "FacilityAdapter",
        resource: status_models.Resource,
        user: User,
        session_id: str,
        command_id: str,
    ) -> interactive_models.Command:
        """Return one command, including any captured output so far."""

    @abstractmethod
    async def list_commands(
        self: "FacilityAdapter",
        resource: status_models.Resource,
        user: User,
        session_id: str,
    ) -> list[interactive_models.Command]:
        """Return all commands in a session."""

    @abstractmethod
    async def cancel_command(
        self: "FacilityAdapter",
        resource: status_models.Resource,
        user: User,
        session_id: str,
        command_id: str,
    ) -> None:
        """Cancel a queued or running command. No-op on already-terminal commands."""
