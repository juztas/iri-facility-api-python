"""Interactive session API router.

Allows users to reserve a slot of nodes on a compute resource and
interactively send commands to them — target one node, target all nodes,
blocking or non-blocking, with per-node output capture and on-demand
retrieval.
"""
from fastapi import Depends, Query, Request, status

from ...types.http import forbidExtraQueryParams
from ...types.user import User
from .. import iri_router
from ..error_handlers import DEFAULT_RESPONSES
from ..iri_meta import iri_meta_dict
from ..status.status import router as status_router
from . import facility_adapter, models

router = iri_router.IriRouter(
    facility_adapter.FacilityAdapter,
    prefix="/interactive",
    tags=["interactive"],
)


# ---------------------------------------------------------------------------
# Sessions (slot management)
# ---------------------------------------------------------------------------


@router.post(
    "/sessions/{resource_id:str}",
    response_model=models.InteractiveSession,
    response_model_exclude_unset=True,
    status_code=status.HTTP_201_CREATED,
    responses=DEFAULT_RESPONSES,
    operation_id="createInteractiveSession",
    openapi_extra=iri_meta_dict("experimental", "optional"),
)
async def create_session(
    resource_id: str,
    spec: models.InteractiveSessionSpec,
    request: Request,
    user: User = Depends(router.current_user),
    _forbid=Depends(forbidExtraQueryParams()),
):
    """
    Create a new interactive session on a compute resource.

    The adapter reserves `spec.node_count` nodes for at most
    `spec.duration_seconds`. The returned session, once `status == active`,
    can accept commands via the `/commands` sub-collection.
    """
    resource = await status_router.adapter.get_resource(resource_id)
    return await router.adapter.create_session(resource=resource, user=user, spec=spec)


@router.get(
    "/sessions/{resource_id:str}",
    response_model=list[models.InteractiveSession],
    response_model_exclude_unset=True,
    responses=DEFAULT_RESPONSES,
    operation_id="listInteractiveSessions",
    openapi_extra=iri_meta_dict("experimental", "optional"),
)
async def list_sessions(
    resource_id: str,
    request: Request,
    user: User = Depends(router.current_user),
    _forbid=Depends(forbidExtraQueryParams()),
):
    """List the caller's interactive sessions on this resource."""
    resource = await status_router.adapter.get_resource(resource_id)
    return await router.adapter.list_sessions(resource=resource, user=user)


@router.get(
    "/sessions/{resource_id:str}/{session_id:str}",
    response_model=models.InteractiveSession,
    response_model_exclude_unset=True,
    responses=DEFAULT_RESPONSES,
    operation_id="getInteractiveSession",
    openapi_extra=iri_meta_dict("experimental", "optional"),
)
async def get_session(
    resource_id: str,
    session_id: str,
    request: Request,
    user: User = Depends(router.current_user),
    _forbid=Depends(forbidExtraQueryParams()),
):
    """Get the current state of an interactive session."""
    resource = await status_router.adapter.get_resource(resource_id)
    return await router.adapter.get_session(resource=resource, user=user, session_id=session_id)


@router.delete(
    "/sessions/{resource_id:str}/{session_id:str}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses=DEFAULT_RESPONSES,
    operation_id="endInteractiveSession",
    openapi_extra=iri_meta_dict("experimental", "optional"),
)
async def end_session(
    resource_id: str,
    session_id: str,
    request: Request,
    user: User = Depends(router.current_user),
    _forbid=Depends(forbidExtraQueryParams()),
):
    """End an interactive session early. Cancels any in-flight commands."""
    resource = await status_router.adapter.get_resource(resource_id)
    await router.adapter.end_session(resource=resource, user=user, session_id=session_id)
    return None


# ---------------------------------------------------------------------------
# Commands (interactive shell execution within a session)
# ---------------------------------------------------------------------------


@router.post(
    "/sessions/{resource_id:str}/{session_id:str}/commands",
    response_model=models.Command,
    response_model_exclude_unset=True,
    status_code=status.HTTP_201_CREATED,
    responses=DEFAULT_RESPONSES,
    operation_id="dispatchInteractiveCommand",
    openapi_extra=iri_meta_dict("experimental", "optional"),
)
async def dispatch_command(
    resource_id: str,
    session_id: str,
    spec: models.CommandSpec,
    request: Request,
    user: User = Depends(router.current_user),
    _forbid=Depends(forbidExtraQueryParams()),
):
    """
    Dispatch a shell command into an active session.

    The command is sent to one node, every node, or a specific node based on
    `spec.target`. When `spec.blocking` is true the API waits for all targets
    to finish (or `spec.timeout_seconds` to elapse) and returns the populated
    command; otherwise the API returns immediately and the caller polls via
    `GET /commands/{command_id}` to retrieve outputs.
    """
    resource = await status_router.adapter.get_resource(resource_id)
    return await router.adapter.dispatch_command(
        resource=resource, user=user, session_id=session_id, spec=spec,
    )


@router.get(
    "/sessions/{resource_id:str}/{session_id:str}/commands",
    response_model=list[models.Command],
    response_model_exclude_unset=True,
    responses=DEFAULT_RESPONSES,
    operation_id="listInteractiveCommands",
    openapi_extra=iri_meta_dict("experimental", "optional"),
)
async def list_commands(
    resource_id: str,
    session_id: str,
    request: Request,
    user: User = Depends(router.current_user),
    status_filter: models.CommandStatus | None = Query(default=None, alias="status", description="Filter by command status"),
    _forbid=Depends(forbidExtraQueryParams("status")),
):
    """List commands dispatched into this session."""
    resource = await status_router.adapter.get_resource(resource_id)
    commands = await router.adapter.list_commands(resource=resource, user=user, session_id=session_id)
    if status_filter is not None:
        commands = [c for c in commands if c.status == status_filter]
    return commands


@router.get(
    "/sessions/{resource_id:str}/{session_id:str}/commands/{command_id:str}",
    response_model=models.Command,
    response_model_exclude_unset=True,
    responses=DEFAULT_RESPONSES,
    operation_id="getInteractiveCommand",
    openapi_extra=iri_meta_dict("experimental", "optional"),
)
async def get_command(
    resource_id: str,
    session_id: str,
    command_id: str,
    request: Request,
    user: User = Depends(router.current_user),
    _forbid=Depends(forbidExtraQueryParams()),
):
    """
    Retrieve a command and its captured output.

    Poll this endpoint to follow a non-blocking command — `outputs[*].stdout`
    and `outputs[*].stderr` accumulate as the command runs, and `status`
    transitions to `completed` / `failed` / `timed_out` / `cancelled` when
    the last target finishes.
    """
    resource = await status_router.adapter.get_resource(resource_id)
    return await router.adapter.get_command(
        resource=resource, user=user, session_id=session_id, command_id=command_id,
    )


@router.delete(
    "/sessions/{resource_id:str}/{session_id:str}/commands/{command_id:str}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses=DEFAULT_RESPONSES,
    operation_id="cancelInteractiveCommand",
    openapi_extra=iri_meta_dict("experimental", "optional"),
)
async def cancel_command(
    resource_id: str,
    session_id: str,
    command_id: str,
    request: Request,
    user: User = Depends(router.current_user),
    _forbid=Depends(forbidExtraQueryParams()),
):
    """Cancel a queued or running command. No-op on already-terminal commands."""
    resource = await status_router.adapter.get_resource(resource_id)
    await router.adapter.cancel_command(
        resource=resource, user=user, session_id=session_id, command_id=command_id,
    )
    return None
