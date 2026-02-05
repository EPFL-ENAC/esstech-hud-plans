import cv2
import numpy as np


def save_histogram(coords_a, coords_b, accentuation=0.5, output_png="histogram.png"):
    # 1. RESOLUTION & BOUNDS
    scale = 100  # 100 pixels per meter
    # Shift coordinates to start at 0 for the histogram bins
    a_min, b_min = coords_a.min(), coords_b.min()
    a_rel = coords_a - a_min
    b_rel = coords_b - b_min

    width = int((a_rel.max()) * scale) + 1
    height = int((b_rel.max()) * scale) + 1

    # 2. THE "SUM" LOGIC (Histogram2D)
    density, a_edges, b_edges = np.histogram2d(coords_a, coords_b, bins=[width, height])

    accentuated = np.power(density, accentuation)

    # 3. NORMALIZE & INVERT (To get white background, black walls)
    if accentuated.max() > 0:
        normalized = (accentuated / accentuated.max()) * 255
    else:
        normalized = accentuated

    final_image = 255 - normalized.astype(np.uint8)

    # Flip or Rotate if necessary (X,Z orientation can sometimes be mirrored)
    # We transpose because histogram2d outputs (Nx, Ny) and images are (Rows, Cols)
    final_image = np.transpose(final_image)

    # 4. Flip vertically to fix the "view from bottom" issue
    final_image = np.flipud(final_image)

    cv2.imwrite(output_png, final_image)


# def extract_blueprint_volumetric(ply_path, output_png="blueprint.png",
#                                  density_strength=0.5, resolution=100):
#     """
#     Uses volumetric ray marching to integrate Gaussian densities.
#     This is more accurate than just counting point centers.
#     """
#     # 1. Load the PLY with full Gaussian Splat data
#     plydata = PlyData.read(ply_path)
#     vertices = plydata['vertex']
#
#     # Extract properties
#     positions = np.vstack([vertices['x'], vertices['y'], vertices['z']]).T
#
#     # Check if Gaussian Splat properties exist
#     has_splat_data = 'opacity' in vertices.data.dtype.names
#
#     if has_splat_data:
#         opacity = np.array(vertices['opacity'])
#         # Opacity is often stored as logit, convert to [0,1]
#         opacity = 1 / (1 + np.exp(-opacity))
#
#         # Scales (3D ellipsoid radii)
#         scales = np.vstack([
#             vertices['scale_0'],
#             vertices['scale_1'],
#             vertices['scale_2']
#         ]).T
#         # Scales are often in log space
#         scales = np.exp(scales)
#     else:
#         # Fallback if it's just a point cloud
#         opacity = np.ones(len(positions))
#         scales = np.ones((len(positions), 3)) * 0.01
#
#     # 2. Align to Y-up (same as before)
#     pcd = o3d.geometry.PointCloud()
#     pcd.points = o3d.utility.Vector3dVector(positions)
#
#     plane_model, inliers = pcd.segment_plane(0.1, 3, 1000)
#     [a, b, c, d] = plane_model
#     floor_normal = np.array([a, b, c]) / np.linalg.norm([a, b, c])
#
#     rotation_axis = np.cross(floor_normal, [0, 1, 0])
#     if np.linalg.norm(rotation_axis) > 1e-6:
#         angle = np.arccos(np.dot(floor_normal, [0, 1, 0]))
#         R = o3d.geometry.get_rotation_matrix_from_axis_angle(
#             rotation_axis * angle / np.linalg.norm(rotation_axis)
#         )
#         positions = (R @ positions.T).T
#
#     # 3. Define the 2D grid (Top-down view on X-Z plane)
#     x_min, x_max = positions[:, 0].min(), positions[:, 0].max()
#     z_min, z_max = positions[:, 2].min(), positions[:, 2].max()
#
#     width = int((x_max - x_min) * resolution)
#     height = int((z_max - z_min) * resolution)
#
#     density_map = np.zeros((height, width), dtype=np.float32)
#
#     # 4. Ray Marching: For each pixel, integrate density along Y
#     x_coords = np.linspace(x_min, x_max, width)
#     z_coords = np.linspace(z_min, z_max, height)
#
#     print("Ray marching through Gaussian field...")
#
#     for i, z in enumerate(z_coords):
#         for j, x in enumerate(x_coords):
#             # Cast a vertical ray at this (x, z) position
#             ray_density = 0.0
#
#             # Find all Gaussians near this ray
#             # Using a spatial filter for efficiency
#             distances_xz = np.sqrt((positions[:, 0] - x)**2 +
#                                    (positions[:, 2] - z)**2)
#
#             # Only consider Gaussians within 3 sigma of the ray
#             nearby = distances_xz < (scales[:, [0, 2]].max(axis=1) * 3)
#
#             for idx in np.where(nearby)[0]:
#                 pos = positions[idx]
#                 scale = scales[idx]
#                 opa = opacity[idx]
#
#                 # Calculate 2D Gaussian density at this (x,z) from the Gaussian's center
#                 dx = x - pos[0]
#                 dz = z - pos[2]
#
#                 # Simplified: Use XZ scales to calculate 2D distance
#                 dist_sq = (dx / (scale[0] + 1e-6))**2 + (dz / (scale[2] + 1e-6))**2
#
#                 # Gaussian density function: exp(-0.5 * distance²)
#                 # Multiply by opacity and Y-scale (height contribution)
#                 contribution = opa * np.exp(-0.5 * dist_sq) * scale[1]
#                 ray_density += contribution
#
#             density_map[i, j] = ray_density
#
#         if i % 10 == 0:
#             print(f"Progress: {i}/{height} rows")
#
#     # 5. Apply strength and normalize
#     accentuated = np.power(density_map, density_strength)
#     print(accentuated.max(), accentuated.min())
#     if accentuated.max() > 0:
#         normalized = (accentuated / accentuated.max()) * 255
#     else:
#         normalized = accentuated
#
#     final_blueprint = 255 - normalized.astype(np.uint8)
#     final_blueprint = np.flipud(final_blueprint)
#
#     cv2.imwrite(output_png, final_blueprint)
#     print(f"Volumetric blueprint saved to {output_png}")


# trash
# def extract_blueprint_with_gaussian_density(ply_path, output_png="blueprint.png", density_strength=0.5):
#     plydata = PlyData.read(ply_path)
#     vertices = plydata['vertex']
#
#     # Extract positions
#     x = vertices['x']
#     y = vertices['y']  # Vertical axis in your case
#     z = vertices['z']
#     points = np.stack([x, y, z], axis=1)
#
#     # Extract Gaussian properties (if available)
#     try:
#         opacity = vertices['opacity']
#     except:
#         print("No opacity found, using uniform weights")
#         opacity = np.ones(len(x))
#
#     try:
#         scale_0 = vertices['scale_0']
#         scale_1 = vertices['scale_1']
#         scale_2 = vertices['scale_2']
#         # Approximate "volume" of the Gaussian ellipsoid
#         volume = scale_0 * scale_1 * scale_2
#     except:
#         print("No scale found, using uniform volume")
#         volume = np.ones(len(x))
#
#     # 2. CREATE WEIGHTS
#     # The "density" of a Gaussian is approximately its opacity × volume
#     # We use sigmoid(opacity) because raw opacity can have extreme values
#     weights = (1 / (1 + np.exp(-opacity))) * volume
#
#     # 3. FILTER BY HEIGHT (Y is vertical)
#     # Only take Gaussians that overlap the 0.5m to 2.0m range
#     mask = (points[:, 1] > 0.5) & (points[:, 1] < 2.0)
#     mask = np.ones(len(y), dtype=bool)  # Use all points
#
#     coords_x = points[mask, 0]
#     coords_z = points[mask, 2]
#     point_weights = weights[mask]
#
#     # 4. RESOLUTION
#     scale = 100
#     width = int((coords_x.max() - coords_x.min()) * scale) + 100
#     height = int((coords_z.max() - coords_z.min()) * scale) + 100
#
#     # 5. WEIGHTED HISTOGRAM (The key improvement)
#     # Instead of counting points, we sum their "density contribution"
#     density, x_edges, z_edges = np.histogram2d(
#         coords_x,
#         coords_z,
#         bins=[width, height],
#         weights=point_weights  # This is the critical parameter
#     )
#
#     # 6. ACCENTUATE
#     accentuated = np.power(density, density_strength)
#
#     # 7. NORMALIZE & OUTPUT
#     if accentuated.max() > 0:
#         normalized = (accentuated / accentuated.max()) * 255
#     else:
#         normalized = accentuated
#
#     final_blueprint = 255 - normalized.astype(np.uint8)
#     final_blueprint = np.transpose(final_blueprint)
#     final_blueprint = np.flipud(final_blueprint)
#
#     cv2.imwrite(output_png, final_blueprint)
#     print(f"Density-weighted blueprint saved (strength={density_strength})")

# trash
# def extract_blueprint_real_splats(ply_path, output_png="blueprint.png", density_strength=0.5):
#     print(f"Extracting blueprint from splat PLY: {ply_path}...")
#
#     # 1. Load the raw PLY data
#     plydata = PlyData.read(ply_path)
#     v_data = plydata['vertex']
#
#     print("Done loading PLY data.")
#
#     # Extract positions
#     x = np.asarray(v_data['x'])
#     y = np.asarray(v_data['y']) # Vertical axis
#     z = np.asarray(v_data['z'])
#     print(f"Loaded {len(x)} points from PLY. (x: {len(x)}, y: {len(y)}, z: {len(z)})")
#
#
#     # Extract Opacity (Usually stored as 'opacity')
#     # Note: In raw 3DGS, this is often 'inv_sigmoid' form,
#     # but most exported PLYs have it as 0.0-1.0
#     opacities = np.asarray(v_data['opacity'])
#     print("Extracted opacities from PLY data.")
#
#     # Extract Scales (scale_0, scale_1, scale_2)
#     # 3DGS stores these as logs, so we need np.exp()
#     s0 = np.exp(np.asarray(v_data['scale_0']))
#     s1 = np.exp(np.asarray(v_data['scale_1']))
#     s2 = np.exp(np.asarray(v_data['scale_2']))
#     print("Extracted scales from PLY data.")
#
#     # 2. Filter for the height slice (Y is vertical)
#     # mask = (y > 0.5) & (y < 2.0)
#     mask = np.ones(len(y), dtype=bool)  # Use all points
#
#     # 3. Setup Coordinate Space
#     scale_factor = 100 # Pixels per meter
#     pad = 50
#
#     pos_x = (x[mask] - x[mask].min()) * scale_factor
#     pos_z = (z[mask] - z[mask].min()) * scale_factor
#
#     # For a blueprint, we care about the "footprint" on the XZ plane.
#     # We take the max of the X and Z scales to represent the splat size.
#     splat_sizes = np.maximum(s0[mask], s2[mask]) * scale_factor
#     slice_opacities = opacities[mask]
#
#     print(f"Filtered to {len(pos_x)} points in the height slice.")
#
#     # Create Canvas
#     w, h = int(pos_x.max()) + (pad * 2), int(pos_z.max()) + (pad * 2)
#     canvas = np.zeros((h, w), dtype=np.float32)
#
#     print(f"Initialized canvas of size {w}x{h}.")
#     # 4. Rasterize the Splats
#     # We use a vectorized approach or a fast loop to "paint" the density
#     for i in range(len(pos_x)):
#         center = (int(pos_x[i] + pad), int(pos_z[i] + pad))
#         radius = max(1, int(splat_sizes[i]))
#
#         # Draw the Gaussian influence on the 2D plane
#         # We use a small circle filled with the opacity value
#         # We add (+) to accumulate density where splats overlap
#         cv2.circle(canvas, center, radius, float(slice_opacities[i]), -1)
#
#     print("Completed rasterizing splats onto canvas.")
#
#     # 5. Post-Process Density
#     # Normalize and apply the "Strength" curve
#     max_val = np.percentile(canvas, 99.5)
#     canvas = np.clip(canvas / (max_val + 1e-6), 0, 1)
#
#     # Strength shifts the gamma (0.1 = harsh/walls only, 0.9 = soft/all details)
#     canvas = np.power(canvas, 1.0 / (density_strength + 0.1))
#
#     # 6. Final Export
#     final = (255 - (canvas * 255)).astype(np.uint8)
#     final = np.flipud(final) # Correct the vertical orientation
#
#     cv2.imwrite(output_png, final)


# def get_density_map(points_2d, density_strength=0.5):
#     # Calculate density (the sum of points at each pixel)
#     # histogram2d effectively "stacks" the points vertically
#     density, x_e, y_e = np.histogram2d(points_2d[:, 0], points_2d[:, 1], bins=1000)
#
#     # ACCENTUATE FEATURE:
#     # We take the density and raise it to a power
#     # High density (walls) grows exponentially larger than low density (noise)
#     accentuated = np.power(density, density_strength * 2)
#
#     # Normalize to 0-255 for PNG
#     img = (255 - (accentuated / accentuated.max() * 255)).astype(np.uint8)
#     return img
#
# def render_to_png(points_2d, output_path: str):
#     print(f"Rendering {len(points_2d)} points to {output_path}...")
#     # Scale points to pixel coordinates
#     # 100 pixels per meter
#     scale = 100
#     padding = 100
#
#     pts = (points_2d - points_2d.min(axis=0)) * scale
#     w, h = pts.max(axis=0).astype(int) + (padding * 2)
#
#     img = np.full((h, w, 3), 255, dtype=np.uint8)
#
#     for p in pts.astype(int):
#         cv2.circle(img, (p[0] + padding, p[1] + padding), 1, (0, 0, 0), -1)
#
#     cv2.imwrite(output_path.replace(".png", "_points.png"), img)
#     cv2.imwrite(output_path, get_density_map(points_2d, density_strength=0.5))


# def extract_blueprint_with_density(ply_path, output_path="blueprint.png", density_strength=0.5):
#     """
#     :param density_strength: 0.0 to 1.0.
#                              Higher makes the blueprint more sensitive to sparse points.
#                              Lower ignores everything except very dense walls.
#     """
#     pcd = o3d.io.read_point_cloud(ply_path)
#
#     # 1. Level the cloud (Using the logic from the previous step)
#     plane_model, inliers = pcd.segment_plane(0.1, 3, 1000)
#     [a, b, c, d] = plane_model
#
#     # ... [Insert the Rotation logic from previous answer here to align to Z-axis] ...
#     # (For brevity, assuming pcd is now leveled and translated so floor is Z=0)
#
#     # 2. Define the Projection Range
#     # We take everything from 0.1m (above floor dust) to 2.5m (typical ceiling height)
#     points = np.asarray(pcd.points)
#     mask = (points[:, 2] > 0.1) & (points[:, 2] < 2.5)
#     points_2d = points[mask][:, :2]
#
#     # 3. Setup Canvas and Scaling
#     scale = 100
#     padding = 50
#
#     # Normalize points
#     min_xy = points_2d.min(axis=0)
#     pts_scaled = (points_2d - min_xy) * scale
#
#     w, h = pts_scaled.max(axis=0).astype(int) + (padding * 2)
#
#     # 4. Create an ACCUMULATION MAP (Floating point for precision)
#     # This stores the "count" of points in every pixel
#     accumulation_map = np.zeros((h, w), dtype=np.float32)
#
#     print(f"Accumulating {len(pts_scaled)} points into density map...")
#     for p in pts_scaled:
#         x, y = (p + padding).astype(int)
#         if 0 <= x < w and 0 <= y < h:
#             accumulation_map[y, x] += 1
#     print("Accumulation completed.")
#
#     # 5. Apply the STRENGTH parameter
#     # We use a percentile-based normalization so the contrast is robust.
#     # We find the "max density" in the image.
#     max_val = np.percentile(accumulation_map, 99.9) # Avoid hot-pixel outliers
#
#     # The 'density_strength' shifts the gamma curve
#     # Low strength: Only the most dense points (walls) survive
#     # High strength: Brings out lower density details
#     if max_val > 0:
#         # Normalize 0 to 1
#         normalized = np.clip(accumulation_map / max_val, 0, 1)
#         # Power function (Gamma) to control sensitivity
#         # strength 0.1 -> steep curve (only walls)
#         # strength 1.0 -> linear
#         gamma = 1.0 / (density_strength + 0.001)
#         adjusted = np.power(normalized, gamma)
#     else:
#         adjusted = normalized
#
#     # 6. Convert to Image (White background, Black walls)
#     # Invert: 1.0 (Dense) becomes 0 (Black), 0 (Empty) becomes 255 (White)
#     final_img = ((1.0 - adjusted) * 255).astype(np.uint8)
#
#     # 7. Optional: Denoise the final blueprint
#     # This merges nearby wall points into solid lines
#     final_img = cv2.medianBlur(final_img, 3)
#
#     cv2.imwrite(output_path, final_img)
#     print(f"Density blueprint saved with strength {density_strength}")
