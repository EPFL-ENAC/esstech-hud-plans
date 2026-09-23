#!/usr/bin/env python
"""SpatialLM runner: point cloud -> layout text -> 2D vector plan (SVG + JSON).

Must run inside the SpatialLM workspace venv (python 3.11, spatiallm installed).
Heavy imports stay inside main() so the module compiles fast outside the venv.
The layout parse and preprocessing reuse SpatialLM's own inference.py functions.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import time
import traceback
from pathlib import Path

RESULT_PREFIX = "SPATIALLM_PLAN_RESULT "


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run SpatialLM and export a 2D plan.")
    p.add_argument("--input", required=True, help="Input .ply point cloud.")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--workspace", required=True, help="SpatialLM workspace dir.")
    p.add_argument("--model-dir", required=True, help="Local model checkpoint dir.")
    p.add_argument("--model-id", default="manycore-research/SpatialLM1.1-Qwen-0.5B")
    p.add_argument("--detect-type", default="arch", choices=["arch", "object", "all"])
    p.add_argument("--seed", type=int, default=-1)
    p.add_argument("--temperature", type=float, default=0.6)
    p.add_argument("--top-p", type=float, default=0.95)
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--num-beams", type=int, default=1)
    p.add_argument("--max-new-tokens", type=int, default=4096)
    p.add_argument("--dtype", default="bfloat16", choices=["float16", "bfloat16", "float32"])
    p.add_argument("--default-wall-thickness", type=float, default=0.1)
    p.add_argument("--no-cleanup", action="store_true")
    return p.parse_args()


def _load_inference_module(workspace: Path):
    """Import SpatialLM's inference.py to reuse its exact preprocessing code."""
    path = workspace / "SpatialLM" / "inference.py"
    if not path.is_file():
        raise RuntimeError(f"missing inference module: {path}")
    spec = importlib.util.spec_from_file_location("spatiallm_inference", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _entities(layout):
    if hasattr(layout, "get_entities"):
        return list(layout.get_entities())
    return list(getattr(layout, "entities", []))


class _F:
    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y

    def __add__(self, o: "_F") -> "_F":
        return _F(self.x + o.x, self.y + o.y)

    def __sub__(self, o: "_F") -> "_F":
        return _F(self.x - o.x, self.y - o.y)

    def __mul__(self, k: float) -> "_F":
        return _F(self.x * k, self.y * k)

    __rmul__ = __mul__

    @property
    def len(self) -> float:
        return math.hypot(self.x, self.y)


def _num(obj, names, default=None):
    """First present numeric field, float-coerced (0.0 is valid)."""
    for n in names:
        if hasattr(obj, n):
            v = getattr(obj, n)
            if v is None:
                continue
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return default


def _wall_geom(e, default_t: float):
    ax = _num(e, ("ax", "a_x", "start_x"))
    ay = _num(e, ("ay", "a_y", "start_y"))
    bx = _num(e, ("bx", "b_x", "end_x"))
    by = _num(e, ("by", "b_y", "end_y"))
    h = _num(e, ("height", "wall_height"), 0.0)
    th = _num(e, ("thickness", "t"), 0.0)
    if None in (ax, ay, bx, by):
        return None
    a, b = _F(ax, ay), _F(bx, by)
    d = b - a
    if d.len < 1e-6:
        return None
    u = _F(d.x / d.len, d.y / d.len)
    n = _F(-u.y, u.x)
    t = th if th > 0.02 else default_t
    corners = [
        a + n * (t / 2), b + n * (t / 2), b - n * (t / 2), a - n * (t / 2),
    ]
    return {"id": int(_num(e, ("id",), -1)), "a": a, "b": b, "u": u, "n": n, "len": d.len,
            "thickness": t, "height": h, "corners": corners}


def _door_geom(e, walls_by_id, valid_walls):
    """Openings bind to a host wall by model id, else to the nearest wall."""
    cx = _num(e, ("position_x", "px", "x"))
    cy = _num(e, ("position_y", "py", "y"))
    cz = _num(e, ("position_z", "pz", "z"), 0.0)
    w = _num(e, ("width", "w"))
    h = _num(e, ("height", "h"), 0.0)
    wid = _num(e, ("wall_id", "wall", "container_id"))
    if None in (cx, cy, w) or not valid_walls:
        return None
    hw = None
    if wid is not None:
        hw = walls_by_id.get(int(wid))
    if hw is None:  # fallback: nearest wall centroid
        p = _F(cx, cy)
        hw = min(valid_walls, key=lambda g: ((g["a"] + g["b"]) * 0.5 - p).len)
    a, u, n, L = hw["a"], hw["u"], hw["n"], hw["len"]
    # projection of the opening center onto the host wall segment
    d = _F(cx, cy) - a
    s = max(0.0, min(L, d.x * u.x + d.y * u.y))
    center = a + u * s
    hinge = center - u * (w / 2)
    swing_start = center + u * (w / 2)
    open_dir = n  # open toward +normal side
    leaf_tip = hinge + open_dir * w
    cross = u.x * n.y - u.y * n.x
    sweep = 1 if cross > 0 else 0
    return {"id": int(_num(e, ("id",), -1)), "wall_id": int(wid) if wid is not None else None,
            "center": center, "width": w, "height": h, "cz": cz, "hinge": hinge,
            "swing_start": swing_start, "leaf_tip": leaf_tip, "sweep": sweep,
            "host": hw}


def _furniture_geom(e):
    cls = getattr(e, "class_name", None) or getattr(e, "category", None) or "object"
    cx = _num(e, ("position_x", "px", "x"))
    cy = _num(e, ("position_y", "py", "y"))
    ang = _num(e, ("angle_z", "rotation_z", "angle"), 0.0) or 0.0
    sx = _num(e, ("scale_x", "sx"), 0.0) or 0.0
    sy = _num(e, ("scale_y", "sy"), 0.0) or 0.0
    if None in (cx, cy):
        return None
    ca, sa = math.cos(ang), math.sin(ang)
    corners = []
    for dx, dy in ((-sx / 2, -sy / 2), (sx / 2, -sy / 2), (sx / 2, sy / 2), (-sx / 2, sy / 2)):
        # rotate the half-size box by angle_z around z at the center
        corners.append(_F(cx + ca * dx - sa * dy, cy + sa * dx + ca * dy))
    return {"id": int(_num(e, ("id",), -1)), "class": cls, "center": (cx, cy),
            "angle_z": ang, "corners": corners}


def _poly_attr(points) -> str:
    return " ".join(f"{p.x:.3f},{p.y:.3f}" for p in points)


def _write_svg(path: Path, walls, doors, windows, furniture) -> None:
    pts = []
    for g in walls:
        pts += g["corners"]
    for g in doors + windows:
        pts += [g["hinge"], g["swing_start"], g["leaf_tip"]]
    for g in furniture:
        pts += g["corners"]
    if pts:
        minx = min(p.x for p in pts) - 0.5
        maxx = max(p.x for p in pts) + 0.5
        miny = min(p.y for p in pts) - 0.5
        maxy = max(p.y for p in pts) + 0.5
    else:
        minx, maxx, miny, maxy = -0.5, 0.5, -0.5, 0.5

    maxy_raw = max((p.y for p in pts), default=0.0)

    def fy(y: float) -> float:
        # flip y for the SVG y-down system; hands of arcs flip with it
        return maxy_raw - y

    x0, y0 = minx, fy(maxy)  # padded bounds, y flipped
    w_m, h_m = maxx - minx, maxy - miny
    ppm = 100  # px per meter
    s = []
    s.append('<?xml version="1.0" encoding="UTF-8"?>')
    s.append("<!-- 2D vector plan exported by the SpatialLM pipeline (esstech-hud-plans) -->")
    s.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{x0:.3f} {y0:.3f} {w_m:.3f} {h_m:.3f}" '
        f'width="{max(400, int(w_m * ppm))}" height="{max(300, int(h_m * ppm))}">'
    )
    s.append(f'<rect x="{x0:.3f}" y="{y0:.3f}" width="{w_m:.3f}" height="{h_m:.3f}" fill="#fafafa"/>')

    if not pts:
        s.append(
            '<text x="0" y="0" font-family="sans-serif" font-size="0.2" fill="#666">'
            "no layout elements</text>"
        )
        s.append("</svg>")
        path.write_text("\n".join(s))
        return

    s.append('<g id="walls">')
    for i, g in enumerate(walls):
        s.append(
            f'<polygon id="wall_{g["id"]}" points="{_poly_attr([_F(p.x, fy(p.y)) for p in g["corners"]])}" '
            f'fill="#23272e"/>'
        )
    s.append("</g>")

    s.append('<g id="windows">')
    for i, g in enumerate(windows):
        hw = g["host"]
        u, n, t = hw["u"], hw["n"], hw["thickness"]
        c = g["center"]
        p0 = c - u * (g["width"] / 2)
        p1 = c + u * (g["width"] / 2)
        for o in (t / 4, -t / 4):
            l0, l1 = p0 + n * o, p1 + n * o
            s.append(
                f'<line x1="{l0.x:.3f}" y1="{fy(l0.y):.3f}" x2="{l1.x:.3f}" y2="{fy(l1.y):.3f}" '
                f'stroke="#0d47a1" stroke-width="0.015"/>'
            )
        s.append(
            f'<text x="{c.x:.3f}" y="{fy(c.y):.3f}" font-family="sans-serif" font-size="0.14" '
            f'fill="#8a8f98" text-anchor="middle">window_{i}</text>'
        )
    s.append("</g>")

    s.append('<g id="doors">')
    for i, g in enumerate(doors):
        hinge, leaf, start = g["hinge"], g["leaf_tip"], g["swing_start"]
        # y flip is a reflection: the arc hand flips too
        draw_sweep = 1 - g["sweep"]
        s.append(f'<path d="M {start.x:.3f} {fy(start.y):.3f} A {g["width"]:.3f} {g["width"]:.3f} '
                 f'0 0 {draw_sweep} {leaf.x:.3f} {fy(leaf.y):.3f}" fill="none" stroke="#e65100" stroke-width="0.02"/>')
        s.append(
            f'<circle cx="{hinge.x:.3f}" cy="{fy(hinge.y):.3f}" r="0.03" fill="#e65100"/>'
        )
        s.append(
            f'<text x="{g["center"].x:.3f}" y="{fy(g["center"].y):.3f}" font-family="sans-serif" '
            f'font-size="0.14" fill="#8a8f98" text-anchor="middle">door_{i}</text>'
        )
    s.append("</g>")

    if furniture:
        s.append('<g id="furniture">')
        for i, g in enumerate(furniture):
            s.append(
                f'<polygon points="{_poly_attr([_F(p.x, fy(p.y)) for p in g["corners"]])}" '
                f'fill="none" stroke="#616161" stroke-width="0.015" stroke-dasharray="0.08 0.05"/>'
            )
        s.append("</g>")

    s.append("</svg>")
    path.write_text("\n".join(s))


def _write_json(path: Path, walls, doors, windows, furniture, args, meta: dict) -> None:
    data = {
        "schema": "esstech-hud-plans/spatiallm-plan-2d",
        "units": "meters",
        "source_ply": args.input,
        "model": args.model_id,
        "detect_type": args.detect_type,
        "gpu": {"name": meta["device"], "index": meta["device_index"]},
        "timing": {"seconds": meta["seconds"], "inference_seconds": meta["inference_seconds"],
                   "peak_vram_bytes": meta["peak_vram_bytes"]},
        "num_points_after_cleanup": meta["num_points"],
        "walls": [
            {
                "id": g["id"],
                "centerline_xy": [[g["a"].x, g["a"].y], [g["b"].x, g["b"].y]],
                "corners_xy": [[p.x, p.y] for p in g["corners"]],
                "thickness": round(g["thickness"], 4),
                "height": round(g["height"], 4),
            }
            for i, g in enumerate(walls)
        ],
        "doors": [
            {
                "id": g["id"],
                "wall_id": g["wall_id"],
                "center_xy": [round(g["center"].x, 4), round(g["center"].y, 4)],
                "width": round(g["width"], 4),
                "height_m": round(g["height"], 4),
                "sill_z": round(g["cz"] - g["height"] / 2, 4),
                "lintel_z": round(g["cz"] + g["height"] / 2, 4),
                "leaf": [[round(g["hinge"].x, 4), round(g["hinge"].y, 4)],
                         [round(g["leaf_tip"].x, 4), round(g["leaf_tip"].y, 4)]],
                "arc": [[round(g["swing_start"].x, 4), round(g["swing_start"].y, 4)],
                        round(g["width"], 4), g["sweep"]],
            }
            for i, g in enumerate(doors)
        ],
        "windows": [
            {
                "id": g["id"],
                "wall_id": g["wall_id"],
                "center_xy": [round(g["center"].x, 4), round(g["center"].y, 4)],
                "width": round(g["width"], 4),
                "height_m": round(g["height"], 4),
                "sill_z": round(g["cz"] - g["height"] / 2, 4),
                "lintel_z": round(g["cz"] + g["height"] / 2, 4),
            }
            for i, g in enumerate(windows)
        ],
        "furniture": [
            {
                "id": g["id"],
                "class": g["class"],
                "center_xy": [round(g["center"][0], 4), round(g["center"][1], 4)],
                "angle_z": round(g["angle_z"], 4),
                "corners_xy": [[p.x, p.y] for p in g["corners"]],
            }
            for i, g in enumerate(furniture)
        ],
    }
    path.write_text(json.dumps(data, indent=2))


def main() -> None:
    args = _parse_args()
    try:
        # heavy imports stay here: the workspace venv provides all of them
        import numpy as np
        import torch
        import inspect
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from spatiallm import Layout, Wall, Door, Window, Bbox
        from spatiallm.pcd import (
            cleanup_pcd,
            get_points_and_colors,
            load_o3d_pcd,
        )

        t0 = time.perf_counter()
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        inf = _load_inference_module(Path(args.workspace))

        # num_bins comes from config.json, so no torch load is needed yet
        config = json.loads((Path(args.model_dir) / "config.json").read_text())
        num_bins = int(config["point_config"]["num_bins"])
        grid_size = Layout.get_grid_size(num_bins)
        print(f"[runner] num_bins={num_bins} grid_size={grid_size}", flush=True)

        pcd = load_o3d_pcd(args.input)
        if not args.no_cleanup:
            # voxel downsample + statistical outlier removal, needed for the
            # uncleaned COLMAP dense cloud
            ret = cleanup_pcd(pcd, voxel_size=grid_size)
            pcd = ret if ret is not None else pcd
        points, colors = get_points_and_colors(pcd)
        if points is None or len(points) < 100:
            raise RuntimeError(f"too few points after cleanup: {0 if points is None else len(points)}")
        min_extent = np.min(points, axis=0)
        print(f"[runner] points after cleanup: {len(points)}", flush=True)

        tokenizer = AutoTokenizer.from_pretrained(args.model_dir)
        model = AutoModelForCausalLM.from_pretrained(
            args.model_dir, torch_dtype=getattr(torch, args.dtype)
        )
        model.to("cuda")
        model.set_point_backbone_dtype(torch.float32)
        model.eval()
        device_name = torch.cuda.get_device_name(0)
        print(f"[runner] device: cuda:0 -> {device_name}", flush=True)

        point_cloud = inf.preprocess_point_cloud(points, colors, grid_size, num_bins)
        code_template_file = Path(args.workspace) / "SpatialLM" / "code_template.txt"
        call_kwargs = {}
        for key, val in (
            ("top_k", args.top_k), ("top_p", args.top_p),
            ("temperature", args.temperature), ("num_beams", args.num_beams),
            ("seed", args.seed), ("max_new_tokens", args.max_new_tokens),
            ("detect_type", args.detect_type), ("categories", []),
        ):
            if key in inspect.signature(inf.generate_layout).parameters:
                call_kwargs[key] = val
        # first token can outwait the stock 20 s streamer timeout on a cold
        # CUDA context; the driver also patches the stock timeout to 600 s
        layout = None
        inference_seconds = 0.0
        for attempt in range(3):
            try:
                t_inf = time.perf_counter()
                # generate_layout returns a parsed Layout, already un-discretized
                layout = inf.generate_layout(
                    model, point_cloud, tokenizer, code_template_file, **call_kwargs
                )
                inference_seconds = time.perf_counter() - t_inf
                break
            except Exception as gen_err:
                import gc
                gc.collect()
                torch.cuda.empty_cache()
                if attempt == 2:
                    raise
                print(f"[runner] generation attempt {attempt + 1} failed "
                      f"({gen_err.__class__.__name__}: {gen_err}); retrying", flush=True)

        if not hasattr(layout, "translate") or not hasattr(layout, "to_language_string"):
            raise RuntimeError(
                "generate_layout did not return a Layout object; got: "
                f"{type(layout).__name__}"
            )
        layout.translate(min_extent)
        layout_txt = layout.to_language_string()

        layout_path = output_dir / "layout.txt"
        layout_path.write_text(layout_txt)
        peak_vram = torch.cuda.max_memory_allocated()

        # 2D plan export; walls_by_id is keyed by the model wall id
        entities = _entities(Layout(layout_txt))
        walls, doors, windows, furniture = [], [], [], []
        walls_by_id: dict[int, dict | None] = {}
        for e in entities:
            if isinstance(e, Wall) and not isinstance(e, (Door, Window)):
                g = _wall_geom(e, args.default_wall_thickness)
                walls_by_id[int(_num(e, ("id",), -1))] = g
                if g:
                    walls.append(g)
            elif isinstance(e, Window):
                g = _door_geom(e, walls_by_id, walls)
                if g:
                    windows.append(g)
            elif isinstance(e, Door):
                g = _door_geom(e, walls_by_id, walls)
                if g:
                    doors.append(g)
            elif isinstance(e, Bbox):
                g = _furniture_geom(e)
                if g:
                    furniture.append(g)
        print(
            f"[runner] walls={len(walls)} doors={len(doors)} "
            f"windows={len(windows)} furniture={len(furniture)}",
            flush=True,
        )

        svg_path = output_dir / "plan_2d.svg"
        json_path = output_dir / "plan_2d.json"
        meta = {
            "device": device_name,
            "device_index": int(torch.cuda.current_device()),
            "seconds": time.perf_counter() - t0,
            "inference_seconds": inference_seconds,
            "peak_vram_bytes": int(peak_vram),
            "num_points": int(len(points)),
        }
        _write_svg(svg_path, walls, doors, windows, furniture)
        _write_json(json_path, walls, doors, windows, furniture, args, meta)

        result = {
            "layout_txt": str(layout_path.resolve()),
            "svg": str(svg_path.resolve()),
            "json": str(json_path.resolve()),
            "walls": len(walls), "doors": len(doors),
            "windows": len(windows), "furniture": len(furniture),
            "seconds": meta["seconds"],
            "inference_seconds": inference_seconds,
            "peak_vram_bytes": meta["peak_vram_bytes"],
            "device": device_name,
            "num_points_after_cleanup": meta["num_points"],
        }
        print(RESULT_PREFIX + json.dumps(result), flush=True)
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
