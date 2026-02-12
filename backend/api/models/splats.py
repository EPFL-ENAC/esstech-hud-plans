from typing import Literal, Optional, Union

from pydantic import BaseModel


class FFMPEGExtractionConfig(BaseModel):
    fps: int
    fitInWidth: int
    fitInHeight: int


CameraModel = Literal["PINHOLE", "OPENCV", "OPENCV_FISHEYE", "RADIAL"]
COLMAPQuality = Literal["low", "medium", "high", "extreme"]


class ColmapAutoConfig(BaseModel):
    quality: str
    camera_model: str
    max_image_size: int
    single_camera: bool
    dense: bool


class ColmapManualConfig(BaseModel):
    mode: Literal["manual"]
    camera_model: CameraModel
    max_num_features: int
    overlap: int
    loop_closure: bool
    min_track_len: int
    use_gpu: bool = True


class BrushTrainingConfig(BaseModel):
    totalSteps: int
    renderMode: str
    shDegree: int
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


class GenerationInputs(BaseModel):
    video_path: str
    ffmpeg: FFMPEGExtractionConfig
    colmap: Union[ColmapAutoConfig, ColmapManualConfig]
    brush: BrushTrainingConfig
    blueprint: Optional[BlueprintConfig] = None
