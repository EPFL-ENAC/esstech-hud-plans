from typing import Literal

from pydantic import BaseModel


class FFMPEGExtractionConfig(BaseModel):
    fps: float
    fitInWidth: int
    fitInHeight: int


ColmapDataType = Literal["individual", "video", "internet"]
ColmapQuality = Literal["low", "medium", "high", "extreme"]
ColmapCameraModel = Literal["PINHOLE", "OPENCV", "OPENCV_FISHEYE", "RADIAL"]
CameraType = Literal["standard", "wide_angle", "zoom"]


class ColmapAutoConfig(BaseModel):
    data_type: ColmapDataType
    quality: ColmapQuality
    camera_model: ColmapCameraModel
    max_image_size: int
    single_camera: bool
    dense: bool


class ColmapManualConfig(BaseModel):
    mode: Literal["manual"]
    camera_model: ColmapCameraModel
    max_num_features: int
    overlap: int
    loop_closure: bool
    min_track_len: int
    use_gpu: bool = True


class BrushTrainingConfig(BaseModel):
    totalSteps: int
    renderMode: str
    shDegree: int
    maxSplats: int
    growthGradThreshold: float
    refineEvery: int
    growthStopIter: int
    alphaMode: str
    maxResolution: int
    subsampleFrames: int


class BlueprintConfig(BaseModel):
    enabled: bool = False
    imageWidth: int
    imageHeight: int
    radiusScale: float
    verticalClip: float
    opacityShift: float
    opacity: float


class SectionZFactor(BaseModel):
    min: float
    max: float


class InteractiveBlueprintParams(BaseModel):
    viewerSize: int = 700
    sceneZRotation: float = 0
    displayCameraPositions: bool = True
    displayFloor: bool = False
    floorZOffset: float = 0
    cameramanHeightCm: float = 170
    sectionZFactor: SectionZFactor | None = None
    densityThreshold: float = 1.0
    opacityMultiplier: float = 0.2
    contrast: float = 2.0


class QualityRating(BaseModel):
    category: str
    rating: int


class GenerationFeedback(BaseModel):
    ratings: list[QualityRating]
    notes: str = ""


class GenerationFeedbackSave(BaseModel):
    ratings: list[QualityRating]
    notes: str = ""


class BaseGenerationInputs(BaseModel):
    ffmpeg: FFMPEGExtractionConfig | None = None
    colmap: ColmapAutoConfig | ColmapManualConfig | None = None
    brush: BrushTrainingConfig | None = None
    blueprint: BlueprintConfig | None = None


class GenerationInputs(BaseGenerationInputs):
    video_path: str
    ffmpeg: FFMPEGExtractionConfig
    colmap: ColmapAutoConfig | ColmapManualConfig
    brush: BrushTrainingConfig
    device_name: str
    camera_type: CameraType
    ip_address: str = ""
    browser_info: str = ""


class RestartBrushInputs(BaseGenerationInputs):
    colmap_generation_id: str
    brush: BrushTrainingConfig
    ip_address: str = ""
    browser_info: str = ""
