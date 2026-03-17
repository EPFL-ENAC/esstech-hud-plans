import json
import os
import shutil

from api.lib.splat_pipeline import BasePipeline
from api.models.splats import RestartBrushInputs


class RestartBrushPipeline(BasePipeline):
    def __init__(self, job_name: str, inputs: RestartBrushInputs):
        self.inputs: RestartBrushInputs
        super().__init__(job_name=job_name, inputs=inputs)

    def prepare_dirs(self, root_path: str):
        source_path = os.path.join(
            os.path.dirname(root_path), self.inputs.colmap_generation_id
        )

        if not os.path.exists(source_path):
            raise ValueError(
                f"Source generation {self.inputs.colmap_generation_id} not found"
            )

        source_status_file = os.path.join(source_path, "status.json")
        if not os.path.exists(source_status_file):
            raise ValueError(
                f"Source status file not found for generation {self.inputs.colmap_generation_id}"
            )

        with open(source_status_file, "r") as f:
            source_status = json.load(f)

        os.makedirs(root_path, exist_ok=True)
        new_status_file = os.path.join(root_path, "status.json")

        steps_list = ["ffmpeg", "colmap", "brush"]
        if self.inputs.blueprint is not None:
            steps_list.append("blueprint_extraction")

        new_status = {
            "name": self.job_name,
            "overall_status": "pending",
            "progress": 0.0,
            "message": "Starting brush restart...",
            "started_at": source_status.get("started_at"),
            "finished_at": None,
            "output": None,
            "settings": {
                **source_status.get("settings", {}),
                "brush": self.inputs.brush.model_dump(),
                "blueprint": self.inputs.blueprint.model_dump()
                if self.inputs.blueprint
                else None,
            },
            "steps_list": steps_list,
            "steps": {},
            "colmap_geometric_data": source_status.get("colmap_geometric_data"),
        }

        source_steps = source_status.get("steps", {})
        for step in ["ffmpeg", "colmap"]:
            if step in source_steps:
                new_status["steps"][step] = source_steps[step]

        with open(new_status_file, "w") as f:
            json.dump(new_status, f, indent=2)

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

        self.directories = {
            "workspace": root_path,
            "images": os.path.join(root_path, "images"),
            "colmap": os.path.join(root_path, "colmap"),
        }

        self._prepare_symlinks(source_path)

    def _prepare_symlinks(self, source_path: str):
        source_images_dir = os.path.join(source_path, "images")
        source_colmap_dir = os.path.join(source_path, "colmap")

        if not os.path.exists(source_images_dir):
            raise ValueError(
                f"Source images directory not found at {source_images_dir}"
            )
        if not os.path.exists(source_colmap_dir):
            raise ValueError(
                f"Source COLMAP directory not found at {source_colmap_dir}"
            )

        workspace_images_link = self.directories["images"]
        workspace_colmap_link = self.directories["colmap"]

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

    def _run(self) -> dict[str, str | list[str] | list]:
        self.logger.set_file_path(
            os.path.join(self.directories["workspace"], "status.json")
        )
        self.logger.start()

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
