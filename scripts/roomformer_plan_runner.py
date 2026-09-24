#!/usr/bin/env python
"""RoomFormer runner: .ply point cloud -> density map -> room polygons (SVG + JSON).

Must run inside the RoomFormer workspace venv (python 3.11, torch + open3d).
Heavy imports stay inside main() so the module compiles fast outside the venv.
The density projection follows the official data_preprocess projection, and the
polygon decode follows engine.py; both changed only for the outlier handling
requested for an uncleaned COLMAP dense cloud.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import traceback
from pathlib import Path

RESULT_PREFIX = "ROOMFORMER_PLAN_RESULT "

# Structured3D room type ids (data_preprocess/stru3d/stru3d_utils.py type2id);
# 16 is door and 17 is window, kept out of the room list
ROOM_TYPES = [
    "living room", "kitchen", "bedroom", "bathroom", "balcony", "corridor",
    "dining room", "study", "studio", "store room", "garden", "laundry room",
    "office", "basement", "garage", "undefined",
]
ROOM_PALETTE = {
    "living room": "#c8e6c9", "kitchen": "#ffe0b2", "bedroom": "#c5cae9",
    "bathroom": "#b2ebf2", "balcony": "#f0f4c3", "corridor": "#d7ccc8",
    "dining room": "#ffccbc", "study": "#d1c4e9", "studio": "#f8bbd0",
    "store room": "#cfd8dc", "garden": "#ccff90", "laundry room": "#b3e5fc",
    "office": "#ffcdd2", "basement": "#d0d9cf", "garage": "#e0e0e0",
    "undefined": "#eef2f9",
}
NON_SEMANTIC_FILL = "#eef2f9"
# density grid: the model trains on 256x256 density images
MAP_SIZE = 256



def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run RoomFormer on a point cloud approximate density map.")
    p.add_argument("--input", required=True, help="Input .ply point cloud.")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--codero", required=True, help="RoomFormer repo root (on sys.path).")
    p.add_argument("--checkpoint", required=True, help="Path to the .pth checkpoint.")
    p.add_argument("--variant", default="stru3d")
    p.add_argument("--num-queries", type=int, default=800)
    p.add_argument("--num-polys", type=int, default=20)
    p.add_argument("--semantic-classes", type=int, default=-1)
    p.add_argument("--sor-neighbors", type=int, default=30)
    p.add_argument("--sor-std", type=float, default=2.0)
    p.add_argument("--voxel-size", type=float, default=-1.0,
                   help="Voxel pre-pass in meters to equalize the density map before counting: "
                        "-1 auto (half the density cell), 0 disables, >0 explicit.")
    p.add_argument("--z-min", type=float, default=None)
    p.add_argument("--z-max", type=float, default=None)
    p.add_argument("--min-area-px", type=float, default=100.0)
    p.add_argument("--density-only", action="store_true",
                   help="Export the density image at the requested share and stop, "
                        "without the model or inference.")
    p.add_argument("--bright-fraction", type=float, default=0.05,
                   help="Initial share of all pixels brighter than 128 (0.05 = 5 percent). "
                        "0 disables the search and uses the official max normalization.")
    p.add_argument("--target-rooms", type=int, default=1,
                   help="Room count the iterative brightness search stops at.")
    p.add_argument("--max-density-iters", type=int, default=9,
                   help="Maximum search attempts; the share halves toward 0 (= official max "
                        "normalization) and stops.")
    p.add_argument("--gpu-index-used", type=int, default=0,
                   help="Physical GPU index picked by the facade, for the result record.")
    p.add_argument("--corner-threshold", type=float, default=0.5,
                   help="Corner validity threshold, same as eval.py. Lower to 0.2-0.3 for sparse clouds.")
    p.add_argument("--density-gamma", type=float, default=1.0,
                   help="Gamma exponent applied to the density map before quantization; "
                        "raise contrast for sparse clouds (try 0.5) when the decode finds no rooms.")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def _install_native_rasterizer_stub() -> None:
    """Give diff_ras a placeholder module when its CUDA extension is missing.

    models/losses.py imports diff_ras.polygon at module level, which imports the
    compiled native_rasterizer. The rasterizer is training-only; the decode
    never calls it, so a stub keeps the import chain alive without compiling.
    """
    import types

    try:
        import native_rasterizer  # noqa: F401  the compiled ext is present
        return
    except ModuleNotFoundError:
        pass
    stub = types.ModuleType("native_rasterizer")

    def _missing(*_a, **_k):
        raise RuntimeError("differentiable rasterization needs the compiled diff_ras extension")

    stub.forward_rasterize = _missing
    stub.backward_rasterize = _missing
    sys.modules["native_rasterizer"] = stub


def _generate_density(points_xy, width: int = MAP_SIZE, height: int = MAP_SIZE):
    """Replica of data_preprocess/stru3d/stru3d_utils.py:generate_density.

    Orthographic histogram of the xy coordinates over the padded bounding box:
    10 percent padding on each side, round to a (width, height) grid, clamp.
    Returns the raw bin-count map and the padded bbox needed to map pixels back
    to meters. Contrast normalization happens in _tune_density.
    """
    import numpy as np

    ps = points_xy.astype("float64")
    image_res = np.array((width, height))
    max_coords = np.max(ps, axis=0)
    min_coords = np.min(ps, axis=0)
    max_m_min = max_coords - min_coords
    max_m_min = np.where(max_m_min <= 0, 1.0, max_m_min)  # degenerate axis guard
    max_coords = max_coords + 0.1 * max_m_min
    min_coords = min_coords - 0.1 * max_m_min

    coordinates = np.round(
        (ps - min_coords[None, :]) / (max_coords[None, :] - min_coords[None, :]) * image_res[None]
    )
    coordinates = np.minimum(np.maximum(coordinates, np.zeros_like(image_res)), image_res - 1)

    density = np.zeros((height, width), dtype="float32")
    unique_coordinates, counts = np.unique(coordinates, return_counts=True, axis=0)
    unique_coordinates = unique_coordinates.astype("int32")
    density[unique_coordinates[:, 1], unique_coordinates[:, 0]] = counts
    norm = {"min_coords": min_coords, "max_coords": max_coords, "image_res": image_res}
    return density, norm


def _tune_density(density, bright_target: float = 0.05, blur_sigma: float = 1.0,
                  tol: float = 0.1):
    """Tune the density map contrast for the model.

    The official preprocessing normalizes counts by their maximum, which leaves
    only the wall peaks bright when a COLMAP cloud is sparse (about 0.1 percent
    of the pixels brighter than 128). Tune instead: blur the histogram to
    spread wall thickness, then pick the scale that puts the requested share of
    all pixels (bright_target, default 5 percent) at intensity 128 and the wall
    peaks at 255. Falls back to the official max normalization when the target
    is unreachable, that is when the occupied area is smaller than the target.
    """
    import numpy as np
    from scipy.ndimage import gaussian_filter

    total = int(density.size)
    target = int(round(total * bright_target))
    for sigma in (blur_sigma, blur_sigma * 2.0, blur_sigma * 4.0):
        blurred = gaussian_filter(density.astype("float32"), sigma=sigma, mode="constant")
        flat = blurred.ravel()
        if int((flat > 0).sum()) < target:
            continue  # not enough occupied area even after blur
        idx = min(target, flat.size) - 1
        t = float(np.sort(flat)[::-1][idx])
        if t <= 0:
            continue
        # pixel intensity is exactly 128 at the target rank, 255 at the peaks
        scale = t * 255.0 / 128.0
        out = np.clip(flat / scale, 0.0, 1.0).reshape(density.shape).astype("float32")
        bright = int(((out * 255.0) >= 128.0).sum()) / total
        mode = "tuned" if abs(bright - bright_target) <= tol * bright_target else "tuned-unverified"
        return out, {
            "mode": mode,
            "blur_sigma": float(sigma),
            "scale": float(scale),
            "bright_fraction": float(bright),
        }
    mx = max(float(np.max(density)), 1.0)
    out = np.clip(density / mx, 0.0, 1.0).astype("float32")
    return out, {
        "mode": "max",
        "blur_sigma": 0.0,
        "scale": mx,
        "bright_fraction": int(((out * 255.0) >= 128.0).sum()) / total,
    }


def _decode_polys(outputs, norm, min_area_px: float, corner_threshold: float):
    """Polygon decode, following engine.py:evaluate_floor."""
    import numpy as np
    import torch
    from shapely.geometry import Polygon

    pred_logits = outputs["pred_logits"][0]  # [num_polys, num_queries_per_poly]
    pred_corners = outputs["pred_coords"][0]  # [num_polys, num_queries_per_poly, 2]
    fg_mask = torch.sigmoid(pred_logits) > corner_threshold
    semantic = "pred_room_logits" in outputs
    room_labels = None
    if semantic:
        prob = torch.nn.functional.softmax(outputs["pred_room_logits"][0], dim=-1)
        room_labels = prob[..., :-1].argmax(-1).cpu().numpy()  # last slot is not a class

    min_xy, max_xy = norm["min_coords"], norm["max_coords"]
    extent = max_xy - min_xy
    image_res = float(MAP_SIZE)

    def to_meters(b):
        # b holds bin indices from round(normalized * 255): m = min + b * extent / 256
        return np.asarray(min_xy) + np.asarray(b, dtype="float64") * np.asarray(extent) / image_res

    rooms, doors, windows = [], [], []
    for j in range(pred_corners.shape[0]):
        valid = pred_corners[j][fg_mask[j]]
        if valid.shape[0] == 0:
            continue
        b = np.around(valid.cpu().numpy() * 255).astype("int32")
        b = np.clip(b, 0, MAP_SIZE - 1)
        label = int(room_labels[j]) if semantic else None
        if label is not None and label == 16:
            type_name = "door"
        elif label is not None and label == 17:
            type_name = "window"
        elif label is not None and label < len(ROOM_TYPES):
            type_name = ROOM_TYPES[label]
        else:
            type_name = "undefined"

        if semantic and label in (16, 17):
            if b.shape[0] == 2:  # door / window: open segment with 2 corners
                (doors if label == 16 else windows).append(
                    {"id": len(doors if label == 16 else windows), "type": type_name,
                     "p0_px": b[0], "p1_px": b[1],
                     "p0_px_m": tuple(to_meters(b[0])), "p1_px_m": tuple(to_meters(b[1]))}
                )
        else:
            if b.shape[0] >= 4:
                poly = Polygon(b)
                if poly.area >= min_area_px:
                    rooms.append(
                        {"id": len(rooms), "type": None if not semantic else type_name,
                         "corners_px": b,
                         "corners_px_m": [tuple(to_meters(c)) for c in b],
                         "area_m2": float(poly.area) * float(extent[0]) * float(extent[1]) / (image_res ** 2)}
                    )
    return rooms, doors, windows, semantic


def _attr(points) -> str:
    return " ".join(f"{x:.3f},{y:.3f}" for x, y in points)


def _write_svg(path: Path, rooms, doors, windows) -> None:
    pts = [p for r in rooms for p in r["corners_px_m"]]
    pts += [line["p0_px_m"] for line in doors + windows]
    pts += [line["p1_px_m"] for line in doors + windows]
    if pts:
        minx = min(p[0] for p in pts) - 0.5
        maxx = max(p[0] for p in pts) + 0.5
        miny = min(p[1] for p in pts) - 0.5
        maxy = max(p[1] for p in pts) + 0.5
    else:
        minx, maxx, miny, maxy = -0.5, 0.5, -0.5, 0.5
    maxy_raw = max((p[1] for p in pts), default=0.0)

    def fy(y: float) -> float:
        # flip y for the SVG y-down system
        return maxy_raw - y

    w_m, h_m = maxx - minx, maxy - miny
    ppm = 100  # px per meter
    s = []
    s.append('<?xml version="1.0" encoding="UTF-8"?>')
    s.append("<!-- 2D vector plan exported by the RoomFormer pipeline (esstech-hud-plans) -->")
    s.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{minx:.3f} {maxy_raw - maxy:.3f} {w_m:.3f} {h_m:.3f}" '
        f'width="{max(400, int(w_m * ppm))}" height="{max(300, int(h_m * ppm))}">'
    )
    s.append(
        f'<rect x="{minx:.3f}" y="{maxy_raw - maxy:.3f}" width="{w_m:.3f}" height="{h_m:.3f}" fill="#fafafa"/>'
    )

    if not pts:
        s.append(
            '<text x="0" y="0" font-family="sans-serif" font-size="0.2" fill="#666">'
            "no room polygons</text>"
        )
        s.append("</svg>")
        path.write_text("\n".join(s))
        return

    s.append('<g id="rooms">')
    for r in rooms:
        corners = [(x, fy(y)) for x, y in r["corners_px_m"]]
        fill = ROOM_PALETTE.get(r["type"], NON_SEMANTIC_FILL) if r["type"] is not None else NON_SEMANTIC_FILL
        s.append(
            f'<polygon id="room_{r["id"]}" points="{_attr(corners)}" '
            f'fill="{fill}" stroke="#23272e" stroke-width="0.03"/>'
        )
    s.append("</g>")

    s.append('<g id="labels">')
    for r in rooms:
        cx = sum(p[0] for p in r["corners_px_m"]) / len(r["corners_px_m"])
        cy = sum(p[1] for p in r["corners_px_m"]) / len(r["corners_px_m"])
        label = r["type"] if r["type"] is not None else f"room_{r['id']}"
        s.append(
            f'<text x="{cx:.3f}" y="{fy(cy):.3f}" font-family="sans-serif" font-size="0.15" '
            f'fill="#546e7a" text-anchor="middle">{label}</text>'
        )
    s.append("</g>")

    if doors:
        s.append('<g id="doors">')
        for i, line in enumerate(doors):
            p0, p1 = line["p0_px_m"], line["p1_px_m"]
            s.append(
                f'<line id="door_{i}" x1="{p0[0]:.3f}" y1="{fy(p0[1]):.3f}" '
                f'x2="{p1[0]:.3f}" y2="{fy(p1[1]):.3f}" stroke="#e65100" stroke-width="0.025"/>'
            )
        s.append("</g>")

    if windows:
        s.append('<g id="windows">')
        for i, line in enumerate(windows):
            p0, p1 = line["p0_px_m"], line["p1_px_m"]
            s.append(
                f'<line id="window_{i}" x1="{p0[0]:.3f}" y1="{fy(p0[1]):.3f}" '
                f'x2="{p1[0]:.3f}" y2="{fy(p1[1]):.3f}" stroke="#0d47a1" stroke-width="0.025"/>'
            )
        s.append("</g>")

    s.append("</svg>")
    path.write_text("\n".join(s))


def _write_json(path: Path, rooms, doors, windows, norm, args, meta: dict, points: dict,
                tune_meta: dict) -> None:
    """Pixel coords on the grid map to meters as: m = min_xy + px * (max_xy - min_xy) / 256."""
    data = {
        "schema": "esstech-hud-plans/roomformer-plan-2d",
        "units": "meters",
        "source_ply": args.input,
        "variant": args.variant,
        "checkpoint": Path(args.checkpoint).name,
        "gpu": {"name": meta["device"], "index": meta["device_index"]},
        "timing": {
            "seconds": meta["seconds"],
            "inference_seconds": meta["inference_seconds"],
            "peak_vram_bytes": meta["peak_vram_bytes"],
        },
        "points": points,
        "density_map": {
            "size": [MAP_SIZE, MAP_SIZE],
            # padded bounding box used for the projection; pixel-to-meter basis
            "min_xy": [float(norm["min_coords"][0]), float(norm["min_coords"][1])],
            "max_xy": [float(norm["max_coords"][0]), float(norm["max_coords"][1])],
            "brighter_than_128": round(tune_meta["bright_fraction"], 4),
        },
        "min_area_px": args.min_area_px,
        "corner_threshold": args.corner_threshold,
        "density_gamma": args.density_gamma,
        "target_rooms": args.target_rooms,
        "rooms": [
            {
                "id": r["id"],
                "type": r["type"],
                "corners_px": [[int(x), int(y)] for x, y in r["corners_px"]],
                "corners_xy": [[round(x, 3), round(y, 3)] for x, y in r["corners_px_m"]],
                "area_m2": round(r["area_m2"], 3),
            }
            for r in rooms
        ],
        "doors": [
            {
                "id": d["id"],
                "type": d["type"],
                "p0_xy": [round(d["p0_px_m"][0], 3), round(d["p0_px_m"][1], 3)],
                "p1_xy": [round(d["p1_px_m"][0], 3), round(d["p1_px_m"][1], 3)],
            }
            for d in doors
        ],
        "windows": [
            {
                "id": w["id"],
                "type": w["type"],
                "p0_xy": [round(w["p0_px_m"][0], 3), round(w["p0_px_m"][1], 3)],
                "p1_xy": [round(w["p1_px_m"][0], 3), round(w["p1_px_m"][1], 3)],
            }
            for w in windows
        ],
    }
    path.write_text(json.dumps(data, indent=2))


def _pillow_save(path: Path, img) -> None:
    from PIL import Image

    Image.fromarray(img).save(str(path))


def main() -> None:
    args = _parse_args()
    try:
        import numpy as np
        import torch
        from types import SimpleNamespace
        from shapely.geometry import Polygon

        import open3d as o3d

        t0 = time.perf_counter()
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        random.seed(args.seed)
        np.random.seed(args.seed)
        torch.manual_seed(args.seed)
        torch.cuda.manual_seed_all(args.seed)

        # repo root on sys.path first, then a native_rasterizer placeholder so
        # that the losses import chain survives the missing CUDA extension
        sys.path.insert(0, str(args.codero))
        _install_native_rasterizer_stub()
        from models import build_model  # noqa: E402

        # exact model hyperparameters from eval.py + tools/eval_stru3d.sh
        ns = SimpleNamespace(
            backbone="resnet50",
            dilation=False,
            lr_backbone=0,
            position_embedding="sine",
            num_feature_levels=4,
            hidden_dim=256,
            nheads=8,
            enc_layers=6,
            dec_layers=6,
            dim_feedforward=1024,
            dropout=0.1,
            with_poly_refine=True,
            aux_loss=True,
            dec_n_points=4,
            enc_n_points=4,
            query_pos_type="sine",
            masked_attn=False,
            num_queries=args.num_queries,
            num_polys=args.num_polys,
            semantic_classes=args.semantic_classes,
        )
        model = build_model(ns, train=False)
        model.to("cuda")
        model.eval()
        ckpt = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
        load_report = model.load_state_dict(ckpt["model"], strict=False)
        print(
            f"[runner] checkpoint: {len(load_report.missing_keys)} missing, "
            f"{len(load_report.unexpected_keys)} unexpected keys",
            flush=True,
        )
        device_name = torch.cuda.get_device_name(0)
        print(f"[runner] device: cuda:0 -> {device_name}", flush=True)

        # point cloud + outlier cleanup for the uncleaned COLMAP dense cloud
        pcd = o3d.io.read_point_cloud(str(args.input))
        pts = np.asarray(pcd.points)
        pts = pts[np.isfinite(pts).all(axis=1)]
        n_input = int(len(pts))
        if n_input == 0:
            raise RuntimeError("no finite points in the input cloud")
        pcd.points = o3d.utility.Vector3dVector(pts)
        filtered_pcd, _ = pcd.remove_statistical_outlier(
            nb_neighbors=args.sor_neighbors, std_ratio=args.sor_std
        )
        pts = np.asarray(filtered_pcd.points)
        if args.z_min is not None:
            pts = pts[pts[:, 2] >= args.z_min]
        if args.z_max is not None:
            pts = pts[pts[:, 2] <= args.z_max]
        if len(pts) == 0:
            raise RuntimeError(
                "no points after cleanup and z-filter; check --z-min/--z-max"
            )
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(pts)
        # voxel pre-pass on the cleaned cloud: raw COLMAP sampling is very uneven
        # (close surfaces dominate the counts), which skews the density
        # normalization so walls render faint. Equalize to about half the
        # density cell before the histogram.
        if args.voxel_size != 0:
            if args.voxel_size > 0:
                voxel = args.voxel_size
            else:
                spread = float(np.max(np.max(pts[:, :2], axis=0) - np.min(pts[:, :2], axis=0)))
                voxel = max(spread / 512.0, 0.005)
            pcd = pcd.voxel_down_sample(voxel)
            print(f"[runner] voxel pre-pass {voxel*1000:.1f} mm -> {len(pcd.points)} points", flush=True)
        pts = np.asarray(pcd.points)
        n_clean = int(len(pts))
        if n_clean < 100:
            raise RuntimeError(f"too few points after cleanup: {n_clean}")
        print(f"[runner] points: input={n_input}, after cleanup={n_clean}", flush=True)

        # density projection: orthographic histogram of xy over a padded bbox
        counts, norm = _generate_density(pts[:, :2])

        if args.density_only:
            # export the density image at the requested share and stop
            if args.bright_fraction > 0:
                density, tune_meta = _tune_density(counts, bright_target=float(args.bright_fraction))
            else:
                mx = max(float(np.max(counts)), 1.0)
                density = np.clip(counts / mx, 0.0, 1.0).astype("float32")
                tune_meta = {"mode": "max", "blur_sigma": 0.0, "scale": mx,
                             "bright_fraction": float(((density * 255.0) >= 128.0).sum()) / density.size}
            img_uint8 = (density * 255).astype("uint8")
            density_png = output_dir / "density.png"
            _pillow_save(density_png, img_uint8)
            print(
                f"[runner] density-only: mode={tune_meta['mode']}, "
                f"bright={tune_meta['bright_fraction']*100:.1f}% -> {density_png}",
                flush=True,
            )
            print(RESULT_PREFIX + json.dumps({
                "density_png": str(density_png.resolve()),
                "mode": tune_meta["mode"],
                "bright_fraction": tune_meta["bright_fraction"],
                "points": {"input": n_input, "after_cleanup": n_clean},
            }), flush=True)
            return

        # iterative contrast search: start at --bright-fraction, run the model,
        # halve the share while the model splits the scene into more rooms than
        # --target-rooms, raise it (capped at the start value) when it finds
        # none, and stop at the target. 0 skips the search and uses the
        # official max normalization.
        t_inf = time.perf_counter()
        best = None  # (score, tune_meta, img_uint8, rooms, doors, windows, semantic)
        attempts = []
        share = float(args.bright_fraction)
        lo = None  # share whose attempt found fewer rooms than the target
        hi = None  # share whose attempt found more rooms than the target
        max_mode_tried = False
        while len(attempts) < args.max_density_iters:
            if share <= 0.0:
                # official max normalization ( RoomFormer data_preprocess)
                mx = max(float(np.max(counts)), 1.0)
                density = np.clip(counts / mx, 0.0, 1.0).astype("float32")
                tune_meta = {"mode": "max", "blur_sigma": 0.0, "scale": mx,
                             "bright_fraction": float(((density * 255.0) >= 128.0).sum()) / density.size}
            else:
                density, tune_meta = _tune_density(counts, bright_target=share)
            if args.density_gamma != 1.0:
                # extra contrast adaptation on top of the tuning
                density = np.clip(density.astype("float32") ** float(args.density_gamma), 0.0, 1.0)
            # PNG round-trip value basis (export writes uint8, dataset reload gives /255)
            img_uint8 = (density * 255).astype("uint8")
            image_t = (1 / 255) * torch.as_tensor(np.ascontiguousarray(np.expand_dims(img_uint8, 0)))
            with torch.no_grad():
                outputs = model([image_t.to("cuda")])
                torch.cuda.synchronize()
            rooms, doors, windows, semantic = _decode_polys(
                outputs, norm, args.min_area_px, args.corner_threshold
            )
            attempts.append({"bright": tune_meta["bright_fraction"], "rooms": len(rooms)})
            # keep the attempt closest to the target; treat an empty plan as worse
            score = abs(len(rooms) - args.target_rooms) + (1 if len(rooms) == 0 else 0)
            if best is None or score < best[0]:
                best = (score, tune_meta, img_uint8, rooms, doors, windows, semantic)
            if len(rooms) == args.target_rooms:
                break
            if len(rooms) > args.target_rooms:
                hi = share
            else:
                lo = share
            # choose the next share: bisect between the known bounds
            if lo is None and hi is not None:
                share = hi / 2.0  # too many rooms at the initial share
            elif hi is None and lo is not None:
                # fewer rooms already at the initial (brightest tuned) share
                if max_mode_tried:
                    break
                share = 0.0  # official normalization as the last candidate
                max_mode_tried = True
            elif lo is not None and hi is not None:
                if hi - lo <= 0.005 or len(attempts) >= args.max_density_iters - 1:
                    # bisection stalled or the attempt budget is nearly out
                    if max_mode_tried:
                        break  # keep the best attempt
                    share = 0.0  # official normalization as the final candidate
                    max_mode_tried = True
                else:
                    share = (lo + hi) / 2.0
            else:
                break
        inference_seconds = time.perf_counter() - t_inf
        _, tune_meta, img_uint8, rooms, doors, windows, semantic = best
        print(
            f"[runner] bright-search: target_rooms={args.target_rooms}, "
            f"chosen bright={tune_meta['bright_fraction']*100:.1f}% "
            f"(mode={tune_meta['mode']}, attempts={len(attempts)})",
            flush=True,
        )
        for a in attempts:
            print(
                f"[runner] attempt bright={a['bright']*100:.1f}% -> rooms={a['rooms']}",
                flush=True,
            )
        density_png = output_dir / "density.png"
        _pillow_save(density_png, img_uint8)
        tune_meta = dict(tune_meta)
        tune_meta["search"] = {
            "initial_bright": float(args.bright_fraction),
            "target_rooms": int(args.target_rooms),
            "attempts": attempts,
        }

        print(
            f"[runner] rooms={len(rooms)} doors={len(doors)} windows={len(windows)} "
            f"(semantic={semantic})",
            flush=True,
        )

        svg_path = output_dir / "plan_2d.svg"
        json_path = output_dir / "plan_2d.json"
        meta = {
            "device": device_name,
            "device_index": int(args.gpu_index_used),
            "seconds": time.perf_counter() - t0,
            "inference_seconds": inference_seconds,
            "peak_vram_bytes": int(torch.cuda.max_memory_allocated()),
        }
        _write_svg(svg_path, rooms, doors, windows)
        _write_json(
            json_path, rooms, doors, windows, norm, args, meta,
            {"input": n_input, "after_cleanup": n_clean},
            tune_meta,
        )

        result = {
            "density_png": str(density_png.resolve()),
            "svg": str(svg_path.resolve()),
            "json": str(json_path.resolve()),
            "rooms": len(rooms), "doors": len(doors), "windows": len(windows),
            "seconds": meta["seconds"],
            "inference_seconds": inference_seconds,
            "peak_vram_bytes": meta["peak_vram_bytes"],
            "device": device_name,
            "points": {"input": n_input, "after_cleanup": n_clean},
        }
        print(RESULT_PREFIX + json.dumps(result), flush=True)
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
