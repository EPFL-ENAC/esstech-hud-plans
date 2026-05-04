import cv2
import numpy as np
from api.lib.compute.image_utils import (
    calibrated_sharpness,
    compute_busyness_map,
    resize_to_fit,
)
from pydantic import BaseModel


class VideoFrameDistance(BaseModel):
    hue: float
    hue_count: int
    hue_count_normalized: float
    hue_normalized: float
    hue_normalized_smart: float
    hue_count_normalized_smart: float

    saturation: float
    saturation_count: int
    saturation_count_normalized: float
    saturation_count_normalized_smart: float
    saturation_normalized: float
    saturation_normalized_smart: float

    brightness: float
    brightness_count: int
    brightness_count_normalized: float
    brightness_normalized: float
    brightness_count_normalized_smart: float

    sum: float
    changes_count: int
    changes_score: float
    changes_score_smart: float
    score: float


class VideoFrame:
    name: str
    full_path: str
    index: int

    image: np.ndarray
    hsv_thumbnail: np.ndarray
    busyness_map: np.ndarray

    overall_sharpness: float

    def __init__(
        self,
        name,
        full_path,
        index,
        image=None,
        hsv_thumbnail=None,
        overall_sharpness=None,
        busyness_map=None,
    ):
        self.name = name
        self.full_path = full_path
        self.index = index
        self.image = image
        self.hsv_thumbnail = hsv_thumbnail
        self.overall_sharpness = overall_sharpness
        self.busyness_map = busyness_map

    @staticmethod
    def from_file(path, index, thumbnail_size=64):
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)

        thumb = resize_to_fit(img, thumbnail_size, thumbnail_size)
        hsv_thumb = cv2.cvtColor(thumb, cv2.COLOR_BGR2HSV)
        overall_sharpness = calibrated_sharpness(img)
        busyness_map = compute_busyness_map(img, (thumbnail_size, thumbnail_size))

        return VideoFrame(
            name=path.split("/")[-1],
            full_path=path,
            index=index,
            image=img,
            hsv_thumbnail=hsv_thumb,
            overall_sharpness=overall_sharpness,
            busyness_map=busyness_map,
        )

    def distance(
        self,
        other: "VideoFrame",
        hue_change_threshold: float = 0.1,
        saturation_change_threshold: float = 0.1,
        brightness_change_threshold: float = 0.1,
    ) -> VideoFrameDistance:
        if self.hsv_thumbnail is None or other.hsv_thumbnail is None:
            raise ValueError("Both frames must have hsv_thumbnail computed")

        dh = np.abs(
            self.hsv_thumbnail[:, :, 0].astype(np.float32)
            - other.hsv_thumbnail[:, :, 0].astype(np.float32)
        )
        dh = np.minimum(dh, 180.0 - dh) / 90.0  # normalize hue difference

        ds = (
            np.abs(
                self.hsv_thumbnail[:, :, 1].astype(np.float32)
                - other.hsv_thumbnail[:, :, 1].astype(np.float32)
            )
            / 255.0
        )
        dv = (
            np.abs(
                self.hsv_thumbnail[:, :, 2].astype(np.float32)
                - other.hsv_thumbnail[:, :, 2].astype(np.float32)
            )
            / 255.0
        )

        common_busyness_map = np.maximum(
            self.busyness_map.astype(np.float32),
            other.busyness_map.astype(np.float32),
        )
        smart_max_diff = np.sum(common_busyness_map)

        max_diff = self.hsv_thumbnail.shape[0] * self.hsv_thumbnail.shape[1]

        hue_sum = np.sum(dh)
        hue_count = np.sum(dh > hue_change_threshold)
        saturation_sum = np.sum(ds)
        saturation_count = np.sum(ds > saturation_change_threshold)
        brightness_sum = np.sum(dv)
        brightness_count = np.sum(dv > brightness_change_threshold)
        changes_count = np.sum(
            (dh > hue_change_threshold)
            | (ds > saturation_change_threshold)
            | (dv > brightness_change_threshold)
        )

        return VideoFrameDistance(
            hue=hue_sum,
            hue_count=hue_count,
            hue_count_normalized=hue_count / max_diff if max_diff > 0 else 0,
            hue_count_normalized_smart=(
                hue_count / smart_max_diff if smart_max_diff > 0 else 0
            ),
            hue_normalized=hue_sum / max_diff if max_diff > 0 else 0,
            hue_normalized_smart=(
                hue_sum / smart_max_diff if smart_max_diff > 0 else 0
            ),
            saturation=saturation_sum,
            saturation_count=saturation_count,
            saturation_count_normalized=(
                saturation_count / max_diff if max_diff > 0 else 0
            ),
            saturation_count_normalized_smart=(
                saturation_count / smart_max_diff if smart_max_diff > 0 else 0
            ),
            saturation_normalized=saturation_sum / max_diff if max_diff > 0 else 0,
            saturation_normalized_smart=(
                saturation_sum / smart_max_diff if smart_max_diff > 0 else 0
            ),
            brightness=brightness_sum,
            brightness_count=brightness_count,
            brightness_count_normalized=(
                brightness_count / max_diff if max_diff > 0 else 0
            ),
            brightness_normalized=brightness_sum / max_diff if max_diff > 0 else 0,
            brightness_count_normalized_smart=(
                brightness_count / smart_max_diff if smart_max_diff > 0 else 0
            ),
            sum=np.sum([hue_sum, saturation_sum, brightness_sum]),
            changes_count=changes_count,
            changes_score=changes_count / max_diff if max_diff > 0 else 0,
            changes_score_smart=(
                changes_count / smart_max_diff if smart_max_diff > 0 else 0
            ),
            score=(
                np.sum([hue_sum, saturation_sum, brightness_sum]) / (3 * max_diff)
                if max_diff > 0
                else 0
            ),
        )
