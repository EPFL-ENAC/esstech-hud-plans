from typing import Literal

from pydantic import BaseModel


class FrameExtractionBase(BaseModel):
    """Common settings shared by both extraction modes."""

    fitInWidth: int = 1920
    fitInHeight: int = 1920


class FixedExtractionConfig(FrameExtractionBase):
    """Configuration for standard constant FPS extraction."""

    mode: Literal["fixed"] = "fixed"
    fps: float = 2.0


class SmartExtractionConfig(FrameExtractionBase):
    """Configuration for movement and sharpness based extraction."""

    mode: Literal["smart"] = "smart"
    min_fps: int = 1
    distance_threshold: float = 0.2
    remove_outliers: bool = True
    outlier_sharpness_ratio: float = 0.1


# This type alias allows Pydantic to choose the right class based on the "mode" field
FrameExtractionConfig = FixedExtractionConfig | SmartExtractionConfig


class FFMPEGExtractionConfig(BaseModel):
    fps: float | None = None
    fitInWidth: int
    fitInHeight: int


class FramePickerConfig(BaseModel):
    enabled: bool = False
    sharpness_threshold: float = 0.5
    distance_threshold: float = 0.2
    max_bin_length: int = 10
    grid_cols: int = 8
    grid_rows: int = 8


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
    use_global_mapper: bool = False


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
    frame_extraction: FrameExtractionConfig | None = None
    colmap: ColmapAutoConfig | ColmapManualConfig | None = None
    brush: BrushTrainingConfig | None = None
    blueprint: BlueprintConfig | None = None


class GenerationInputs(BaseGenerationInputs):
    video_path: str
    frame_extraction: FrameExtractionConfig
    colmap: ColmapAutoConfig | ColmapManualConfig
    brush: BrushTrainingConfig
    device_name: str
    camera_type: CameraType
    ip_address: str = ""
    browser_info: str = ""


class RestartBrushInputs(BaseGenerationInputs):
    colmap_generation_id: str
    colmap_sparse_reconstruction_id: int | str = 0
    brush: BrushTrainingConfig
    ip_address: str = ""
    browser_info: str = ""
