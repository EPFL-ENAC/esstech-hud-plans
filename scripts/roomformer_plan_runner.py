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
    10 percent padding on each side, round to a (width, height) grid, clamp,
    then normalize bin counts by their maximum. Returns the density map and the
    padded bbox needed to map pixels back to meters.
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
    density = density / np.max(density)
    norm = {"min_coords": min_coords, "max_coords": max_coords, "image_res": image_res}
    return density, norm


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


def _write_json(path: Path, rooms, doors, windows, norm, args, meta: dict, points: dict) -> None:
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
        },
        "min_area_px": args.min_area_px,
        "corner_threshold": args.corner_threshold,
        "density_gamma": args.density_gamma,
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
        density, norm = _generate_density(pts[:, :2])
        if args.density_gamma != 1.0:
            # contrast adaptation for sparse clouds; the trained density maps are
            # wall-dominant, our cloud histogram is not
            density = density.astype("float32") ** float(args.density_gamma)
        # PNG round-trip value basis (export writes uint8, dataset reload gives /255)
        img_uint8 = (density * 255).astype("uint8")
        density_png = output_dir / "density.png"
        _pillow_save(density_png, img_uint8)

        image_t = (1 / 255) * torch.as_tensor(np.ascontiguousarray(np.expand_dims(img_uint8, 0)))
        samples = [image_t.to("cuda")]

        t_inf = time.perf_counter()
        with torch.no_grad():
            outputs = model(samples)
            torch.cuda.synchronize()
        inference_seconds = time.perf_counter() - t_inf

        # polygon decode, following engine.py:evaluate_floor
        pred_logits = outputs["pred_logits"][0]  # [num_polys, num_queries_per_poly]
        pred_corners = outputs["pred_coords"][0]  # [num_polys, num_queries_per_poly, 2]
        fg_mask = torch.sigmoid(pred_logits) > args.corner_threshold
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
                    if poly.area >= args.min_area_px:
                        rooms.append(
                            {"id": len(rooms), "type": None if not semantic else type_name,
                             "corners_px": b,
                             "corners_px_m": [tuple(to_meters(c)) for c in b],
                             "area_m2": float(poly.area) * float(extent[0]) * float(extent[1]) / (image_res ** 2)}
                        )

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
