import cv2
import numpy as np


def hellinger_distance(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("Hue histograms must have the same size.")

    pa = np.asarray(a, dtype=np.float32)
    pb = np.asarray(b, dtype=np.float32)

    sa = float(pa.sum())
    sb = float(pb.sum())

    if sa == 0.0 and sb == 0.0:
        return 0.0
    if sa == 0.0 or sb == 0.0:
        return 1.0

    pa /= sa
    pb /= sb

    bc = float(np.sum(np.sqrt(pa * pb)))
    bc = max(0.0, min(1.0, bc))

    return float(np.sqrt(1.0 - bc))


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
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    busyness_map = np.abs(laplacian)

    if squash_to_fit:
        busyness_map = resize_to_fit(busyness_map, *squash_to_fit)

    return busyness_map
