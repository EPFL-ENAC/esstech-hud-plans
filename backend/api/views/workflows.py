import logging
from collections.abc import AsyncIterator
from typing import Annotated, cast
from uuid import UUID

from api.lib.workflows import common as workflow_common
from api.lib.workflows.common import (
    WorkflowNotFoundError,
    get_owned_workflow_run,
    stream_workflow_logs,
)
from api.lib.workflows.counter import schedule_counter
from api.lib.workflows.frame_extraction import (
    FrameExtractionArtifact,
    schedule_frame_extraction,
)
from api.models.auth import User
from api.models.workflows import (
    FrameExtractionResultResponse,
    FrameExtractionWorkflowSettings,
    WorkflowStatus,
    WorkflowStatusResponse,
    WorkflowSubmissionResponse,
)
from api.services.auth import require_user
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from prefect.client.schemas.objects import FlowRun, StateType
from pydantic import ValidationError

logger = logging.getLogger(__name__)

router = APIRouter()


async def get_current_workflow(
    workflow_id: UUID,
    current_user: User = Depends(require_user),
) -> FlowRun:
    try:
        return await get_owned_workflow_run(
            workflow_id=workflow_id,
            owner_id=current_user.sub,
        )
    except WorkflowNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workflow service is unavailable",
        ) from exc


@router.post(
    "/counter",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=WorkflowSubmissionResponse,
)
async def submit_counter(
    current_user: User = Depends(require_user),
) -> WorkflowSubmissionResponse:
    try:
        workflow_id = await schedule_counter(current_user.sub)
    except Exception as exc:
        logger.exception("Failed to schedule counter workflow")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Counter workflow service is unavailable",
        ) from exc

    return WorkflowSubmissionResponse(workflow_id=workflow_id)


@router.post(
    "/frame-extraction",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=WorkflowSubmissionResponse,
)
async def submit_frame_extraction(
    file: Annotated[UploadFile, File()],
    settings: Annotated[
        str,
        Form(
            description=(
                "JSON-encoded FrameExtractionWorkflowSettings with separate "
                '"ffmpeg" and "colmap" objects.'
            )
        ),
    ],
    current_user: User = Depends(require_user),
) -> WorkflowSubmissionResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="File must have a filename")
    if file.content_type is None or not file.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a video")

    try:
        workflow_settings = FrameExtractionWorkflowSettings.model_validate_json(
            settings
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors(include_url=False),
        ) from exc

    artifact = await FrameExtractionArtifact.from_uploaded_file(
        file, workflow_common.WORKFLOW_DATA_DIRECTORY
    )

    try:
        workflow_id = await schedule_frame_extraction(
            artifact=artifact,
            settings=workflow_settings,
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


@router.get("/listen/{workflow_id}", response_class=StreamingResponse)
async def listen_to_workflow(
    current_workflow: Annotated[FlowRun, Depends(get_current_workflow)],
) -> StreamingResponse:
    workflow_stream = stream_workflow_logs(current_workflow)
    try:
        first_item = await anext(workflow_stream)
    except Exception as exc:
        await workflow_stream.aclose()
        logger.exception("Failed to start workflow log stream")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workflow log stream is unavailable",
        ) from exc

    async def event_stream() -> AsyncIterator[str]:
        try:
            yield first_item.to_sse_event()
            async for item in workflow_stream:
                yield item.to_sse_event()
        finally:
            await workflow_stream.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/status/{workflow_id}", response_model=WorkflowStatusResponse)
async def get_workflow_status(
    current_workflow: Annotated[FlowRun, Depends(get_current_workflow)],
) -> WorkflowStatusResponse:
    workflow_status = cast(
        WorkflowStatus,
        (
            current_workflow.state_type.value.lower()
            if current_workflow.state_type is not None
            else StateType.PENDING.value.lower()
        ),
    )
    return WorkflowStatusResponse(
        workflow_id=current_workflow.id,
        status=workflow_status,
        message=(
            current_workflow.state.message
            if current_workflow.state is not None
            else None
        ),
    )


@router.get("/result/{workflow_id}", response_model=FrameExtractionResultResponse)
async def get_workflow_result(
    current_workflow: Annotated[FlowRun, Depends(get_current_workflow)],
) -> FrameExtractionResultResponse:
    if current_workflow.state_type != StateType.COMPLETED:
        state_name = (
            current_workflow.state_type.value.lower()
            if current_workflow.state_type is not None
            else "pending"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Workflow is not completed (current status: {state_name})",
        )

    try:
        artifact = FrameExtractionArtifact.from_flow_run(
            current_workflow, workflow_common.WORKFLOW_DATA_DIRECTORY
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

    if not artifact.colmap_sparse_directory.is_dir():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Workflow completed but its COLMAP sparse reconstruction is missing",
        )

    return FrameExtractionResultResponse(
        frames_directory=str(artifact.frames_directory.resolve()),
        colmap_directory=str(artifact.colmap_directory.resolve()),
    )
