import os
import shutil

from api.services.splats import GenerationInputs, GenerationManager
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi_cache.decorator import cache
from pydantic import BaseModel

router = APIRouter()

manager = GenerationManager()

upload_dir = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "uploads"
)


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
async def generate(file: UploadFile = File(...)) -> PostRunGenerationResponse:
    # Validate file type
    if not file.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="File must be a video")

    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir, exist_ok=True)

    file_path = os.path.join(upload_dir, file.filename)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    finally:
        file.file.close()

    run = manager.run_generation(GenerationInputs(video_path=file_path))

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
