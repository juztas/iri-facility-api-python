"""Models for storage location and mount API endpoints."""
from enum import Enum

from pydantic import Field

from ...types.base import IRIBaseModel


class LogicalName(str, Enum):
    """Well-known logical storage area names."""
    home = "home"
    scratch = "scratch"
    project = "project"
    campaign = "campaign"
    archive = "archive"
    shared = "shared"
    temporary = "temporary"


class PerformanceTier(str, Enum):
    """Storage performance classification."""
    high = "high"
    medium = "medium"
    low = "low"
    archive = "archive"


class Intent(str, Enum):
    """Caller's intended usage, used to select the most appropriate path."""
    read = "read"
    write = "write"
    staging = "staging"
    long_term_storage = "long-term-storage"


class StorageAccess(IRIBaseModel):
    """POSIX-style access permissions for a storage path."""
    read: bool = Field(..., description="Read access is permitted.", example=True)
    write: bool = Field(..., description="Write access is permitted.", example=True)
    execute: bool = Field(..., description="Execute / traverse access is permitted.", example=True)


class StorageLocation(IRIBaseModel):
    """
    A resolved storage path for a given resource, user, and project.

    Answers: "Where should data be, and what are the quota/performance characteristics?"
    """
    logical_name: LogicalName = Field(
        ...,
        description="The logical name of the storage area (e.g. home, scratch, project).",
        example="scratch",
    )
    path: str = Field(
        ...,
        description="Absolute filesystem path for this user/project on this resource.",
        example="/scratch/ABC123/jbalcas",
    )
    filesystem: str | None = Field(
        default=None,
        description="Name or type of the underlying filesystem (e.g. lustre-scratch, gpfs, nfs).",
        example="lustre-scratch",
    )
    performance_tier: PerformanceTier | None = Field(
        default=None,
        description="Performance classification of the storage area.",
        example="high",
    )
    quota_bytes: int | None = Field(
        default=None,
        description="Total storage quota in bytes. Null if not applicable or unknown.",
        example=5000000000000,
    )
    available_bytes: int | None = Field(
        default=None,
        description="Currently available storage in bytes. Null if not applicable or unknown.",
        example=4200000000000,
    )
    purge_policy_days: int | None = Field(
        default=None,
        description="Number of days after last access before files are subject to purge. Null if no purge policy.",
        example=30,
    )
    shared: bool = Field(
        default=False,
        description="True if this path is shared across multiple users or projects.",
        example=False,
    )
    access: StorageAccess = Field(
        ...,
        description="Access permissions for this path.",
    )


class StorageMount(StorageLocation):
    """
    A storage path with both in-job and out-of-job (e.g. login node / DTN) access information.

    Answers: "For a resource in a given state (in-job or out-of-job), what volumes are mounted
    and with what permissions?"
    """
    access_outside_of_job: StorageAccess | None = Field(
        default=None,
        description=(
            "Access permissions when operating outside a batch job "
            "(e.g. on a login node or data-transfer node). "
            "Null if the distinction does not apply for this resource."
        ),
    )


class StorageLocationSummary(IRIBaseModel):
    """A brief summary of one supported logical storage area at this facility."""
    logical_name: LogicalName = Field(
        ...,
        description="The logical name of the storage area.",
        example="scratch",
    )
    description: str | None = Field(
        default=None,
        description="Human-readable description of this storage area.",
        example="High-performance Lustre scratch filesystem. Files purged after 30 days of inactivity.",
    )
    filesystem: str | None = Field(
        default=None,
        description="Name or type of the underlying filesystem.",
        example="lustre-scratch",
    )
    performance_tier: PerformanceTier | None = Field(
        default=None,
        description="Performance classification of the storage area.",
        example="high",
    )
