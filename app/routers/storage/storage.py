from fastapi import Depends, Query, Request, HTTPException

from ...types.http import forbidExtraQueryParams
from ...types.user import User
from .. import iri_router
from ..error_handlers import DEFAULT_RESPONSES
from ..iri_meta import iri_meta_dict
from . import facility_adapter, models

router = iri_router.IriRouter(facility_adapter.FacilityAdapter, prefix="/storage", tags=["storage"])


@router.get(
    "/locations",
    responses=DEFAULT_RESPONSES,
    operation_id="listStorageLocations",
    response_model_exclude_none=True,
    openapi_extra=iri_meta_dict("beta", "required"),
)
async def list_storage_locations(
    request: Request,
    _forbid=Depends(forbidExtraQueryParams()),
) -> list[models.StorageLocationSummary]:
    """
    List the logical storage area names supported by this facility.

    Returns the set of logical names (e.g. *home*, *scratch*, *project*)
    that this facility recognises.  There is no requirement for all logical
    names to be present — facilities return only what they actually provide.

    To resolve a logical name to a concrete path for a specific resource,
    user, and project, use ``GET /storage/locations/{resource_id}``.
    """
    summaries = await router.adapter.list_storage_summaries()
    if not summaries:
        raise HTTPException(status_code=404, detail="No storage locations found")
    return summaries


@router.get(
    "/locations/{resource_id}",
    responses=DEFAULT_RESPONSES,
    operation_id="getStorageLocations",
    response_model_exclude_none=True,
    openapi_extra=iri_meta_dict("beta", "required"),
)
async def get_storage_locations(
    request: Request,
    resource_id: str,
    logicalpath: models.LogicalName | None = Query(
        default=None,
        description="Filter by logical storage area name (e.g. home, scratch, project).",
        example="scratch",
    ),
    project: str | None = Query(
        default=None,
        min_length=1,
        description="Project or allocation identifier used to resolve project-specific paths.",
        example="ABC123",
    ),
    intent: models.Intent | None = Query(
        default=None,
        description="Intended usage hint: read, write, staging, or long-term-storage.",
        example="write",
    ),
    current_user: User = Depends(router.current_user),
    _forbid=Depends(forbidExtraQueryParams("logicalpath", "project", "intent")),
) -> list[models.StorageLocation]:
    """
    Resolve storage paths for a resource.

    Given a resource ID and optional filters, returns the filesystem paths
    where data should be placed or accessed, together with quota, performance,
    and access-permission metadata.

    **Example question answered:** *"I want to upload my script — where should
    I put it, and will it be accessible from inside a job?"*

    Query parameters
    ----------------
    - **logicalpath** — return only entries for this logical name.
    - **project** — resolve project-scoped paths (e.g. ``/scratch/<project>/<user>``).
    - **intent** — hint used to prefer a filesystem (e.g. prefer high-performance
      scratch for ``write``, archive for ``long-term-storage``).
    """
    locations = await router.adapter.list_storage_locations(
        resource_id=resource_id,
        logicalpath=logicalpath,
        project=project,
        intent=intent,
        user_id=current_user.id,
    )
    if not locations:
        raise HTTPException(status_code=404, detail=f"No storage locations found for resource '{resource_id}'")
    return locations


@router.get(
    "/mounts/{resource_id}",
    responses=DEFAULT_RESPONSES,
    operation_id="getStorageMounts",
    response_model_exclude_none=True,
    openapi_extra=iri_meta_dict("beta", "required"),
)
async def get_storage_mounts(
    request: Request,
    resource_id: str,
    project: str | None = Query(
        default=None,
        min_length=1,
        description="Project or allocation identifier used to resolve project-specific paths.",
        example="ABC123",
    ),
    intent: models.Intent | None = Query(
        default=None,
        description="Intended usage hint: read, write, staging, or long-term-storage.",
    ),
    current_user: User = Depends(router.current_user),
    _forbid=Depends(forbidExtraQueryParams("project", "intent")),
) -> list[models.StorageMount]:
    """
    List filesystem mounts for a resource with in-job and out-of-job access.

    Returns every filesystem visible from the given resource (compute node,
    login node, DTN, …) together with:

    - **access** — permissions *inside* a batch job.
    - **access_outside_of_job** — permissions on login nodes / data-transfer
      nodes (``null`` when the distinction does not apply).

    **Example question answered:** *"Which filesystems are mounted on this
    cluster, what are the mount points, and can I write to them from inside
    a job vs. from a login node?"*
    """
    mounts = await router.adapter.list_storage_mounts(
        resource_id=resource_id,
        project=project,
        intent=intent,
        user_id=current_user.id,
    )
    if not mounts:
        raise HTTPException(status_code=404, detail=f"No storage mounts found for resource '{resource_id}'")
    return mounts
