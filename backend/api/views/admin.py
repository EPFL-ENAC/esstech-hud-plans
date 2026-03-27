import pandas as pd
from api.services.admin import generate_parameters_table
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

router = APIRouter()


@router.get("/parameters-table")
async def download_parameters_table():
    """
    Generate and download an Excel file with all generation parameters.

    Scans all status.json files in data/splats/<gen-id>/ directories and
    aggregates generation IDs, tool settings (ffmpeg, colmap, brush),
    video path, interactive blueprint params, generation feedback, and timing data.
    """
    try:
        rows, filename = generate_parameters_table()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    df = pd.DataFrame(rows)

    buffer = pd.io.common.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
