from abc import ABC, abstractmethod

from . import models as storage_models


class FacilityAdapter(ABC):
    """
    Adapter interface for the storage locations and mounts API.

    Facility-specific implementations resolve logical storage names to concrete
    filesystem paths for a given resource, user, and project.

    Use the ``IRI_API_ADAPTER_storage`` environment variable to install your
    facility adapter.  Defaults to ``app.demo_adapter.DemoAdapter``.
    """

    @abstractmethod
    async def list_storage_locations(
        self,
        resource_id: str,
        logicalpath: storage_models.LogicalName | None = None,
        project: str | None = None,
        intent: storage_models.Intent | None = None,
        user_id: str | None = None,
    ) -> list[storage_models.StorageLocation]:
        """
        Return a list of resolved storage locations for the given resource.

        Parameters
        ----------
        resource_id:
            The resource (compute cluster, DTN, …) whose storage layout is
            being queried.
        logicalpath:
            When given, return only locations matching this logical name.
        project:
            Project or allocation identifier used to resolve project-specific
            paths such as ``/scratch/<project>/<user>``.
        intent:
            Optional hint about how the caller plans to use the path (read,
            write, staging, long-term-storage).  Implementations may use this
            to prefer one filesystem over another.
        user_id:
            Authenticated user identifier, used to personalise paths such as
            ``/home/<user>``.
        """

    @abstractmethod
    async def list_storage_summaries(self) -> list[storage_models.StorageLocationSummary]:
        """
        Return the set of logical storage area names supported by this facility.

        There is no requirement for all ``LogicalName`` values to be present;
        facilities return only what they actually provide.
        """

    @abstractmethod
    async def list_storage_mounts(
        self,
        resource_id: str,
        project: str | None = None,
        intent: storage_models.Intent | None = None,
        user_id: str | None = None,
    ) -> list[storage_models.StorageMount]:
        """
        Return all filesystem mounts visible from ``resource_id``, together
        with both in-job and out-of-job access information.

        Parameters
        ----------
        resource_id:
            The resource whose mount table is being queried.
        project:
            Optional project/allocation filter; narrows results to paths
            relevant to that project.
        intent:
            Optional usage hint (see ``list_storage_locations``).
        user_id:
            Authenticated user identifier for personalising paths.
        """
