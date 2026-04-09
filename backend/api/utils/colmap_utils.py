from pathlib import Path


def looks_like_colmap_model_dir(path: Path) -> bool:
    names = {p.name for p in path.iterdir() if p.is_file()}
    has_bin = {"cameras.bin", "images.bin", "points3D.bin"}.issubset(names)
    has_txt = {"cameras.txt", "images.txt", "points3D.txt"}.issubset(names)
    return has_bin or has_txt
