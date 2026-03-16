import os
import shutil
from typing import Union

from api.lib.splat_pipeline import SplatPipeline
from api.models.splats import (
    BlueprintConfig,
    BrushTrainingConfig,
    ColmapAutoConfig,
    ColmapManualConfig,
    FFMPEGExtractionConfig,
    GenerationInputs,
    RestartBrushInputs,
)


class RestartBrushPipeline(SplatPipeline):
    def __init__(
        self,
        job_name: str,
        inputs: RestartBrushInputs,
        workspace_dir: str,
        source_dir: str,
        source_status: dict | None = None,
    ):
        self.source_dir = source_dir

        placeholder_ffmpeg = FFMPEGExtractionConfig(
            fps=1, fitInWidth=1920, fitInHeight=1080
        )
        placeholder_colmap: Union[ColmapAutoConfig, ColmapManualConfig] = (
            ColmapAutoConfig(
                data_type="video",
                quality="medium",
                camera_model="OPENCV",
                max_image_size=1920,
                single_camera=True,
                dense=False,
            )
        )

        minimal_inputs = GenerationInputs(
            video_path="",
            ffmpeg=placeholder_ffmpeg,
            colmap=placeholder_colmap,
            brush=inputs.brush,
            blueprint=inputs.blueprint,
        )

        super().__init__(job_name=job_name, inputs=minimal_inputs)

        self.prepare_dirs(workspace_dir)

        if source_status:
            self.logger.data["steps_list"] = source_status.get(
                "steps_list", ["ffmpeg", "colmap", "brush"]
            )
            self.logger.data["colmap_geometric_data"] = source_status.get(
                "colmap_geometric_data"
            )
            source_steps = source_status.get("steps", {})
            for step in ["ffmpeg", "colmap"]:
                if step in source_steps:
                    self.logger.data["steps"][step] = source_steps[step]

        self._prepare_symlinks()

    def _prepare_symlinks(self):
        source_images_dir = os.path.join(self.source_dir, "images")
        source_colmap_dir = os.path.join(self.source_dir, "colmap")

        if not os.path.exists(source_images_dir):
            raise ValueError(
                f"Source images directory not found at {source_images_dir}"
            )
        if not os.path.exists(source_colmap_dir):
            raise ValueError(
                f"Source COLMAP directory not found at {source_colmap_dir}"
            )

        workspace_images_link = os.path.join(self.directories["images"])
        workspace_colmap_link = os.path.join(self.directories["colmap"])

        if os.path.lexists(workspace_images_link):
            if os.path.isdir(workspace_images_link) and not os.path.islink(
                workspace_images_link
            ):
                shutil.rmtree(workspace_images_link)
            else:
                os.remove(workspace_images_link)
        if os.path.lexists(workspace_colmap_link):
            if os.path.isdir(workspace_colmap_link) and not os.path.islink(
                workspace_colmap_link
            ):
                shutil.rmtree(workspace_colmap_link)
            else:
                os.remove(workspace_colmap_link)

        os.symlink(
            os.path.relpath(source_images_dir, self.directories["workspace"]),
            workspace_images_link,
        )
        os.symlink(
            os.path.relpath(source_colmap_dir, self.directories["workspace"]),
            workspace_colmap_link,
        )

    def run(self):
        status_file = os.path.join(self.directories["workspace"], "status.json")
        self.logger.set_file_path(status_file)

        from datetime import datetime

        self.logger.data["overall_status"] = "running"
        self.logger.data["started_at"] = datetime.utcnow().isoformat() + "Z"
        self.logger.data["progress"] = 0
        self.logger.save()

        try:
            self.run_brush(self.inputs.brush)

            pipeline_output: dict[str, str | list[str] | list] = {
                "splat_path": os.path.join(self.directories["workspace"], "splat.ply"),
                "blueprints": [],
            }

            if self.inputs.blueprint is not None:
                self.extract_blueprint_from_splat(
                    os.path.join(self.directories["workspace"], "splat.ply"),
                    self.inputs.blueprint,
                    output_prefix=os.path.join(
                        self.directories["workspace"], "blueprint"
                    ),
                )
                pipeline_output["blueprints"] = [
                    os.path.join(self.directories["workspace"], "blueprint_top.png"),
                ]

            self.logger.complete(output=pipeline_output)

            return pipeline_output
        except Exception as e:
            self.logger.fail(message=str(e))
            raise e
