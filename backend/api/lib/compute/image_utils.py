import cv2
import numpy as np


def calibrated_sharpness(img_bgr, threshold=70.0):
    # 1. Resize to a consistent scale
    img = cv2.resize(img_bgr, (1024, 768))

    # 2. Convert to gray
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 3. Equalize contrast to handle lighting variations
    gray = cv2.equalizeHist(gray)

    # 4. Light blur to ignore sensor noise
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    # 5. Calculate Variance
    lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()

    score = 1 / (1 + np.exp(-0.02 * (lap_var - threshold)))

    return score


def resize_to_fit(img: np.ndarray, max_w: int, max_h: int) -> np.ndarray:
    h, w = img.shape[:2]
    scale = min(max_w / w, max_h / h)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))

    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    return cv2.resize(img, (new_w, new_h), interpolation=interp)


def compute_busyness_map(
    image: np.ndarray, squash_to_fit: tuple[int, int] | None = None
) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    avg_brightness = np.mean(gray) / 255.0
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)

    busyness_map = (
        np.abs(laplacian) / 1020.0 / avg_brightness
    )  # max value of laplacian is 255*4, so 1020 normalizes it to [0,1]

    if squash_to_fit:
        busyness_map = resize_to_fit(busyness_map, *squash_to_fit)

    return busyness_map  # np.clip(busyness_map, 0, 1)
