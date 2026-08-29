import logging
import shutil
from typing import Annotated, cast
from uuid import UUID

from api.models.auth import User
from api.models.workflows import (
    FrameExtractionResultResponse,
    FrameExtractionSettings,
    WorkflowStatus,
    WorkflowStatusResponse,
    WorkflowSubmissionResponse,
)
from api.services import workflows as workflow_service
from api.services.auth import require_user
from api.services.workflows import (
    FrameExtractionArtifact,
    WorkflowNotFoundError,
    get_owned_workflow_run,
    schedule_frame_extraction,
)
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from prefect.client.schemas.objects import StateType
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/frame-extraction",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=WorkflowSubmissionResponse,
)
async def submit_frame_extraction(
    file: Annotated[UploadFile, File()],
    fps: Annotated[float, Form(gt=0)] = 2.0,
    fit_in_width: Annotated[int, Form(gt=0)] = 1920,
    fit_in_height: Annotated[int, Form(gt=0)] = 1920,
    current_user: User = Depends(require_user),
) -> WorkflowSubmissionResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="File must have a filename")
    if file.content_type is None or not file.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a video")

    file_extension = file.filename.split(".")[-1].lower()
    artifact = FrameExtractionArtifact.create(
        workflow_service.WORKFLOW_DATA_DIRECTORY, video_format=file_extension
    )
    try:
        with artifact.video_path.open("wb") as destination:
            await run_in_threadpool(shutil.copyfileobj, file.file, destination)
    except Exception:
        artifact.remove()
        raise
    finally:
        await file.close()

    settings = FrameExtractionSettings(
        fps=fps,
        fit_in_width=fit_in_width,
        fit_in_height=fit_in_height,
    )
    try:
        workflow_id = await schedule_frame_extraction(
            artifact=artifact,
            settings=settings,
            owner_id=current_user.sub,
        )
    except Exception as exc:
        logger.exception("Failed to schedule frame extraction")
        artifact.remove()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Frame extraction service is unavailable",
        ) from exc

    return WorkflowSubmissionResponse(workflow_id=workflow_id)


@router.post("/submit")
def submit_workflow(
    current_user: User = Depends(require_user),
):
    pass


@router.get("/list")
def list_workflows(
    current_user: User = Depends(require_user),
):
    pass


@router.get("/status/{workflow_id}", response_model=WorkflowStatusResponse)
async def get_workflow_status(
    workflow_id: UUID,
    current_user: User = Depends(require_user),
) -> WorkflowStatusResponse:
    try:
        flow_run = await get_owned_workflow_run(workflow_id, current_user.sub)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workflow not found") from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workflow service is unavailable",
        ) from exc

    workflow_status = cast(
        WorkflowStatus,
        (
            flow_run.state_type.value.lower()
            if flow_run.state_type is not None
            else StateType.PENDING.value.lower()
        ),
    )
    return WorkflowStatusResponse(
        workflow_id=workflow_id,
        status=workflow_status,
        message=flow_run.state.message if flow_run.state is not None else None,
    )


@router.get("/result/{workflow_id}", response_model=FrameExtractionResultResponse)
async def get_workflow_result(
    workflow_id: UUID,
    current_user: User = Depends(require_user),
) -> FrameExtractionResultResponse:
    try:
        flow_run = await get_owned_workflow_run(workflow_id, current_user.sub)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workflow not found") from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workflow service is unavailable",
        ) from exc

    if flow_run.state_type != StateType.COMPLETED:
        state_name = (
            flow_run.state_type.value.lower()
            if flow_run.state_type is not None
            else "pending"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Workflow is not completed (current status: {state_name})",
        )

    try:
        artifact = FrameExtractionArtifact.from_flow_run(
            flow_run, workflow_service.WORKFLOW_DATA_DIRECTORY
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    if not artifact.frames_directory.is_dir():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Workflow completed but its frames directory is missing",
        )

    return FrameExtractionResultResponse(
        frames_directory=str(artifact.frames_directory.resolve())
    )
