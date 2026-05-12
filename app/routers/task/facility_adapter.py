import os
import traceback
from abc import abstractmethod
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from ...types.user import User
from . import models as task_models
from .local_queue import QueueSettings, get_task_queue
from ..status import models as status_models
from ..filesystem import models as filesystem_models, facility_adapter as filesystem_adapter
from ..interactive import facility_adapter as interactive_adapter
from ..iri_router import AuthenticatedAdapter, IriRouter

from ...apilogger import get_stream_logger

logger = get_stream_logger(__name__)

class FacilityAdapter(AuthenticatedAdapter):
    """
    Facility-specific code is handled by the implementation of this interface.
    Use the `IRI_API_ADAPTER` environment variable (defaults to `app.demo_adapter.FacilityAdapter`)
    to install your facility adapter before the API starts.
    """

    @abstractmethod
    async def get_task(self: "FacilityAdapter", user: User, task_id: str) -> task_models.Task | None:
        pass

    @abstractmethod
    async def get_tasks(self: "FacilityAdapter", user: User) -> list[task_models.Task]:
        pass

    @abstractmethod
    async def put_task(self: "FacilityAdapter", user: User, resource: status_models.Resource | None, task: task_models.TaskCommand) -> task_models.TaskSubmitResponse:
        pass

    @abstractmethod
    async def delete_task(self: "FacilityAdapter", user: User, task_id: str) -> None:
        pass

    @staticmethod
    async def on_task(resource: status_models.Resource, user: User, task: task_models.TaskCommand) -> tuple[dict, task_models.TaskStatus]:
        # Handle a task from the facility message queue.
        # Returns: (result, status)
        def _extractNull(ind):
            if hasattr(ind, "model_dump"):
                data = ind.model_dump()
            else:
                data = ind
            return {k: v for k, v in data.items() if v is not None}
        try:
            r = None
            logger.info(f"Received task: {task.router}:{task.command} with args: {task.args}")
            if task.router == "filesystem":
                fs_adapter = IriRouter.create_adapter(task.router, filesystem_adapter.FacilityAdapter)
                if task.command == "chmod":
                    data = _extractNull(task.args["request_model"])
                    request_model = filesystem_models.PutFileChmodRequest.model_validate(data)
                    r = await fs_adapter.chmod(resource, user, request_model)
                elif task.command == "chown":
                    data = _extractNull(task.args["request_model"])
                    request_model = filesystem_models.PutFileChownRequest.model_validate(data)
                    r = await fs_adapter.chown(resource, user, request_model)
                elif task.command == "file":
                    r = await fs_adapter.file(resource, user, **task.args)
                elif task.command == "stat":
                    r = await fs_adapter.stat(resource, user, **task.args)
                elif task.command == "mkdir":
                    data = _extractNull(task.args["request_model"])
                    request_model = filesystem_models.PostMakeDirRequest.model_validate(data)
                    r = await fs_adapter.mkdir(resource, user, request_model)
                elif task.command == "symlink":
                    data = _extractNull(task.args["request_model"])
                    request_model = filesystem_models.PostFileSymlinkRequest.model_validate(data)
                    r = await fs_adapter.symlink(resource, user, request_model)
                elif task.command == "ls":
                    r = await fs_adapter.ls(resource, user, **task.args)
                elif task.command == "head":
                    r = await fs_adapter.head(resource, user, **task.args)
                elif task.command == "view":
                    r = await fs_adapter.view(resource, user, **task.args)
                elif task.command == "tail":
                    r = await fs_adapter.tail(resource, user, **task.args)
                elif task.command == "checksum":
                    r = await fs_adapter.checksum(resource, user, **task.args)
                elif task.command == "rm":
                    r = await fs_adapter.rm(resource, user, **task.args)
                elif task.command == "compress":
                    data = _extractNull(task.args["request_model"])
                    request_model = filesystem_models.PostCompressRequest.model_validate(data)
                    r = await fs_adapter.compress(resource, user, request_model)
                elif task.command == "extract":
                    data = _extractNull(task.args["request_model"])
                    request_model = filesystem_models.PostExtractRequest.model_validate(data)
                    r = await fs_adapter.extract(resource, user, request_model)
                elif task.command == "mv":
                    data = _extractNull(task.args["request_model"])
                    request_model = filesystem_models.PostMoveRequest.model_validate(data)
                    r = await fs_adapter.mv(resource, user, request_model)
                elif task.command == "cp":
                    data = _extractNull(task.args["request_model"])
                    request_model = filesystem_models.PostCopyRequest.model_validate(data)
                    r = await fs_adapter.cp(resource, user, request_model)
                elif task.command == "download":
                    r = await fs_adapter.download(resource, user, **task.args)
                elif task.command == "upload":
                    r = await fs_adapter.upload(resource, user, **task.args)
            elif task.router == "interactive":
                interactive = IriRouter.create_adapter(task.router, interactive_adapter.FacilityAdapter)
                if task.command == "run_command":
                    r = await interactive.run_queued_command(resource, user, **task.args)
            if r is not None:
                return (r, task_models.TaskStatus.completed)
            else:
                return ({"output": f"Task was cancelled due to unknown router/command: {task.router}:{task.command}"}, task_models.TaskStatus.failed)
        except Exception as exc:
            traceback_str = traceback.format_exc()
            logger.warning(f"Error handling task {task.router}:{task.command} with args: {task.args}\nError: {exc}")
            logger.debug(f"Traceback:\n{traceback_str}")
            return ({"output": f"Error: {exc}"}, task_models.TaskStatus.failed)


def drain_local_task_queue_once() -> bool:
    """Claim and execute one locally queued task, if any."""
    settings = QueueSettings.from_env()
    queue = get_task_queue()
    worker_id = os.environ.get("IRI_TASK_WORKER_ID", "local-worker")
    lease = queue.claim_next(worker_id=worker_id, lease_seconds=settings.lease_seconds)
    if lease is None:
        return False

    resource = lease.resource
    if lease.command and lease.command.router != "interactive" and resource is None:
        queue.complete_task(
            task_id=lease.id,
            status=task_models.TaskStatus.failed,
            result={"output": "Queued task is missing a resource binding"},
        )
        return True

    result, status = _run_task_sync(resource, lease.user, lease.command)
    normalized = _normalize_task_result(result)
    queue.complete_task(task_id=lease.id, status=status, result=normalized)
    return True


def _run_task_sync(
    resource: status_models.Resource | None,
    user: User,
    command: task_models.TaskCommand | None,
) -> tuple[dict | None, task_models.TaskStatus]:
    import asyncio

    if command is None:
        return {"output": "Queued task is missing a command"}, task_models.TaskStatus.failed
    return asyncio.run(FacilityAdapter.on_task(resource, user, command))


def _normalize_task_result(result: dict | object | None) -> dict | None:
    if result is None:
        return None
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    if isinstance(result, dict):
        return jsonable_encoder(result)
    return jsonable_encoder({"output": result})
