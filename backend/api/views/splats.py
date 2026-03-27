import json
import os
import shutil

from api.models.splats import (
    BlueprintConfig,
    BrushTrainingConfig,
    CameraType,
    ColmapAutoConfig,
    FFMPEGExtractionConfig,
    GenerationInputs,
    InteractiveBlueprintParams,
    RestartBrushInputs,
)
from api.services.splats import GenerationManager
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi_cache.decorator import cache
from pydantic import BaseModel

router = APIRouter()

manager = GenerationManager()

data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
upload_dir = os.path.join(data_dir, "uploads")


class PostRunGenerationResponse(BaseModel):
    generation_id: str


@router.get(
    "/",
    status_code=200,
    description="Say hello",
)
@cache()
async def hello() -> str:
    return "Hello from generation API!"


@router.post(
    "/generate",
    status_code=200,
    description="Generates a Gaussian splat",
    response_model=PostRunGenerationResponse,
)
async def generate(
    request: Request,
    file: UploadFile = File(...),
    ffmpeg_config: str = Form(...),
    colmap_config: str = Form(...),
    brush_config: str = Form(...),
    blueprint_config: str = Form(None),
    device_name: str = Form(""),
    camera_type: CameraType = Form("standard"),
    browser_info: str = Form(""),
) -> PostRunGenerationResponse:
    # 1. Validate file type
    if not file.content_type or not file.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="File must be a video")

    # 2. Parse and Validate JSON Settings
    try:
        # We parse the strings and load them into Pydantic models for validation
        ffmpeg_settings = FFMPEGExtractionConfig(**json.loads(ffmpeg_config))
        colmap_settings = ColmapAutoConfig(**json.loads(colmap_config))
        brush_settings = BrushTrainingConfig(**json.loads(brush_config))
        blueprint_settings = (
            BlueprintConfig(**json.loads(blueprint_config))
            if blueprint_config
            else None
        )
    except Exception as e:
        raise HTTPException(
            status_code=422, detail=f"Invalid configuration format: {str(e)}"
        )

    # 3. Save the file
    if not file.filename:
        raise HTTPException(status_code=400, detail="File must have a filename")

    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir, exist_ok=True)

    file_path = os.path.join(upload_dir, file.filename)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    finally:
        await file.close()

    # 4. Run generation with all inputs
    client_host = request.client.host if request.client else ""
    inputs = GenerationInputs(
        video_path=file_path,
        ffmpeg=ffmpeg_settings,
        colmap=colmap_settings,
        brush=brush_settings,
        blueprint=blueprint_settings,
        device_name=device_name,
        camera_type=camera_type,
        ip_address=client_host,
        browser_info=browser_info,
    )

    run = manager.run_generation(inputs)

    return PostRunGenerationResponse(generation_id=run.id)


@router.get(
    "/get/{generation_id}",
    status_code=200,
    description="Retrieves the generated splat",
)
async def get_splat(generation_id: str):
    result = manager.get_run(generation_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail="Generation not found or not completed yet"
        )

    # Assuming 'result' contains the file path
    file_path = result.output_splat_path

    if file_path is None or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        path=file_path, filename="splat.ply", media_type="application/octet-stream"
    )


@router.get(
    "/status/{generation_id}",
    status_code=200,
    description="Checks the status of a generation run",
)
async def check_status(generation_id: str):
    return manager.get_status(generation_id)


@router.get(
    "/blueprints/{generation_id}",
    status_code=200,
    description="Retrieves the blueprint images of a generation run",
)
async def get_blueprints(generation_id: str):
    return manager.get_blueprints(generation_id)


@router.get(
    "/blueprints/{generation_id}/{view}",
    description="Returns the actual PNG image for a specific view",
)
async def get_blueprint_image(generation_id: str, view: str):
    # Construct the file path
    filename = f"blueprint_{view}.png"
    file_path = os.path.join(data_dir, "splats", generation_id, filename)

    # Security: Ensure the resolved path is actually inside our DATA_ROOT
    real_path = os.path.abspath(file_path)
    print("Real path : " + real_path)
    print("Data dir : " + data_dir)

    if not real_path.startswith(os.path.abspath(data_dir)):
        raise HTTPException(status_code=403, detail="Access denied")

    if not os.path.exists(real_path):
        raise HTTPException(
            status_code=404,
            detail=f"Blueprint {view} for generation {generation_id} not found",
        )

    return FileResponse(real_path, media_type="image/png")


class BlueprintGeometryResponse(BaseModel):
    world_rotation: list[list[float]]
    center: list[float]
    radius: float
    positions: list[list[float]]


@router.get(
    "/blueprint-geometry/{generation_id}",
    status_code=200,
    description="Returns world rotation matrix and center for building blueprint view matrix",
    response_model=BlueprintGeometryResponse,
)
async def get_blueprint_geometry(generation_id: str):
    """Get the geometric data needed for the blueprint view."""
    colmap_geometry = manager.get_colmap_geometry(generation_id)

    if colmap_geometry is None:
        raise HTTPException(
            status_code=404,
            detail=f"COLMAP geometric data not found for generation {generation_id}. "
            "The pipeline may not have completed the COLMAP step yet.",
        )

    return BlueprintGeometryResponse(
        world_rotation=colmap_geometry["world_rotation"],
        center=colmap_geometry["center"],
        radius=colmap_geometry["radius"],
        positions=colmap_geometry["positions"],
    )


@router.get(
    "/settings/{generation_id}",
    status_code=200,
    description="Retrieves the settings used for a generation run",
)
async def get_generation_settings(generation_id: str):
    """Get the settings used for a generation run."""
    settings = manager.get_settings(generation_id)

    if settings is None:
        raise HTTPException(
            status_code=404,
            detail=f"Settings not found for generation {generation_id}. "
            "The generation may not exist or may not have started yet.",
        )

    return settings


@router.post(
    "/restart-brush",
    status_code=200,
    description="Restarts brush training on an existing COLMAP pipeline",
    response_model=PostRunGenerationResponse,
)
async def restart_brush(
    request: Request,
    colmap_generation_id: str = Form(...),
    brush_config: str = Form(...),
    blueprint_config: str = Form(None),
    browser_info: str = Form(""),
) -> PostRunGenerationResponse:
    try:
        brush_settings = BrushTrainingConfig(**json.loads(brush_config))
        blueprint_settings = (
            BlueprintConfig(**json.loads(blueprint_config))
            if blueprint_config
            else None
        )
    except Exception as e:
        raise HTTPException(
            status_code=422, detail=f"Invalid configuration format: {str(e)}"
        )

    client_host = request.client.host if request.client else ""
    inputs = RestartBrushInputs(
        colmap_generation_id=colmap_generation_id,
        brush=brush_settings,
        blueprint=blueprint_settings,
        ip_address=client_host,
        browser_info=browser_info,
    )

    try:
        run = manager.run_restart_brush(inputs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return PostRunGenerationResponse(generation_id=run.id)


class InteractiveBlueprintParamsResponse(BaseModel):
    viewerSize: int
    sceneZRotation: float
    displayCameraPositions: bool
    displayFloor: bool
    floorZOffset: float
    cameramanHeightCm: float
    sectionZFactor: dict | None = None
    densityThreshold: float
    opacityMultiplier: float
    contrast: float


@router.get(
    "/blueprint-params/{generation_id}",
    status_code=200,
    description="Retrieves the interactive blueprint parameters for a generation run",
    response_model=InteractiveBlueprintParamsResponse,
)
async def get_interactive_blueprint_params(generation_id: str):
    """Get the interactive blueprint parameters, with defaults if not saved."""
    saved_params = manager.get_interactive_blueprint_params(generation_id)

    if saved_params is not None:
        return InteractiveBlueprintParamsResponse(**saved_params)

    default_params = InteractiveBlueprintParams()
    return default_params


@router.post(
    "/blueprint-params/{generation_id}",
    status_code=200,
    description="Saves the interactive blueprint parameters for a generation run",
)
async def save_interactive_blueprint_params(
    generation_id: str,
    params: InteractiveBlueprintParams,
):
    """Save the interactive blueprint parameters."""
    success = manager.save_interactive_blueprint_params(
        generation_id, params.model_dump()
    )

    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Generation {generation_id} not found or status file unavailable",
        )

    return {"status": "saved"}
