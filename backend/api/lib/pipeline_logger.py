import json
import os
import re
from datetime import datetime
from typing import Any, Callable

MAX_HEADING_LEVEL = 3


class PipelineLogger:
    def __init__(self, name: str, initial_settings: dict, steps_list: list[str]):
        self.file_path: str | None = None
        self.data: dict[str, Any] = {
            "overall_status": "running",
            "name": name,
            "settings": initial_settings,
            "progress": 0,
            "message": "",
            "started_at": None,
            "finished_at": None,
            "output": None,
            "steps_list": steps_list,
            "steps": {},
            "colmap_geometric_data": None,
            "ip_address": initial_settings.get("ip_address", ""),
            "browser_info": initial_settings.get("browser_info", ""),
        }
        self.save()

    def load_from_file(self, file_path: str):
        """Load existing status data from a file."""
        self.file_path = file_path
        with open(file_path, "r") as f:
            self.data = json.load(f)

    def set_file_path(self, file_path: str):
        self.file_path = file_path

    def save(self):
        if self.file_path is None:
            return

        with open(self.file_path, "w") as f:
            json.dump(self.data, f, indent=2)

    def start(self):
        self.data["overall_status"] = "running"
        self.data["started_at"] = datetime.utcnow().isoformat() + "Z"
        self.data["progress"] = 0

        print(
            f"[Pipeline #{self.data['name']}] Started at {self.data['started_at']}",
            flush=True,
        )
        self.save()

    def fail(self, message: str):
        print(f"[Pipeline #{self.data['name']}] Failed: {message}", flush=True)
        self.data["overall_status"] = "failed"
        self.data["message"] = message
        self.data["finished_at"] = datetime.utcnow().isoformat() + "Z"
        self.save()

    def complete(self, output: dict, message: str = ""):
        print(f"[Pipeline #{self.data['name']}] Completed: {message}", flush=True)
        self.data["overall_status"] = "completed"
        self.data["message"] = message
        self.data["finished_at"] = datetime.utcnow().isoformat() + "Z"
        self.data["progress"] = 100
        self.data["output"] = output
        self.save()

    def submit_step(
        self,
        step: str,
        settings: dict | None = None,
        command: str | list[str] | None = None,
    ):
        self.data["steps"][step] = {
            "status": "submitted",
            "progress": 0,
            "submitted_at": datetime.utcnow().isoformat() + "Z",
            "started_at": None,
            "finished_at": None,
            "settings": settings if settings is not None else {},
            "command": command if command is not None else "",
            "logs": [],
            "return_code": None,
        }

        self.save()

    def has_started(self, step: str) -> bool:
        return step in self.data["steps"] and self.data["steps"][step]["status"] in {
            "running",
            "completed",
            "failed",
        }

    def has_failed(self, step: str) -> bool:
        return (
            step in self.data["steps"]
            and self.data["steps"][step]["status"] == "failed"
        )

    def get_fail_message(self, step: str) -> str | None:
        if self.has_failed(step):
            return self.data["steps"][step].get("message")
        return None

    def start_step(
        self,
        step: str,
        settings: dict | None = None,
        command: str | list[str] | None = None,
    ):
        if step not in self.data["steps"]:
            self.submit_step(
                step=step,
                settings=settings,
                command=command,
            )
        self.data["steps"][step]["status"] = "running"
        self.data["steps"][step]["started_at"] = datetime.utcnow().isoformat() + "Z"

    def step_completed(self, step: str, return_code: int | None = None):
        self.data["steps"][step]["status"] = "completed"
        self.data["steps"][step]["finished_at"] = datetime.utcnow().isoformat() + "Z"
        self.data["steps"][step]["progress"] = 1
        if return_code is not None:
            self.data["steps"][step]["return_code"] = return_code

        self.save()

    def step_failed(self, step: str, message: str, return_code: int | None = None):
        self.data["steps"][step]["status"] = "failed"
        self.data["steps"][step]["finished_at"] = datetime.utcnow().isoformat() + "Z"
        self.data["steps"][step]["progress"] = 1
        self.data["steps"][step]["message"] = message
        if return_code is not None:
            self.data["steps"][step]["return_code"] = return_code

        self.save()

    def evaluate_step(self, step: str, evaluation: dict):
        self.data["steps"][step]["evaluation"] = evaluation
        self.save()

    def reset_step(self, step: str):
        if step in self.data["steps"]:
            del self.data["steps"][step]
            self.save()

    def add_log(
        self,
        step: str,
        line: str,
        heading_level: int = 0,
        cleanup_for_file: Callable[[str], str | None] | None = None,
    ):
        cleaned_line = _strip_ansi(line)
        if cleanup_for_file:
            cleaned_line_or_none: str | None = cleanup_for_file(cleaned_line)
        else:
            cleaned_line_or_none = cleaned_line

        if cleaned_line_or_none is not None:
            self.data["steps"][step]["logs"].append(cleaned_line_or_none)

        extra_lines = (
            max(0, MAX_HEADING_LEVEL - heading_level) if heading_level > 0 else 0
        )
        text = (
            ("\n" * extra_lines)
            + f"[#{self.data['name']}/{step}] "
            + line
            + ("\n" * max(extra_lines - 1, 0))
        )
        print(text, flush=True)

        self.save()

    def get_full_log_from_step(self, step: str) -> str:
        if step not in self.data["steps"]:
            return ""

        return "\n".join(self.data["steps"][step]["logs"])

    def update_step_progress(self, step: str, progress: float):
        self._on_step_progress(step, progress)
        self.save()

    def _on_step_progress(self, step: str, progress: float):
        self.data["steps"][step]["progress"] = progress
        # update overall progress here based on all steps
        overall_progress = 0
        for s in self.data["steps_list"]:
            step_data = self.data["steps"].get(s)
            if step_data:
                overall_progress += step_data["progress"] / len(self.data["steps_list"])
        self.data["progress"] = overall_progress

    def set_colmap_geometric_data(self, geometric_data: dict):
        self.data["colmap_geometric_data"] = geometric_data
        self.save()

    def get_colmap_geometric_data(self) -> dict | None:
        return self.data.get("colmap_geometric_data")

    def set_interactive_blueprint_params(self, params: dict):
        self.data["interactive_blueprint_params"] = params
        self.save()

    def get_interactive_blueprint_params(self) -> dict | None:
        return self.data.get("interactive_blueprint_params")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes and control characters"""
    # Remove ANSI escape sequences
    ansi_escape = re.compile(r"\x1b\[[0-9;]*[mGKHf]|\x1b\][0-9];.*?\x07|\r")
    return ansi_escape.sub("", text).strip()


# def _should_log(step_name: str, cleaned_line: str) -> bool:
#     """Check if this line is different enough from the last to log"""
#     if not cleaned_line:
#         return False
#
#     last = self._last_log.get(step_name, '')
#
#     # Log if it's different from the last line
#     if cleaned_line != last:
#         self._last_log[step_name] = cleaned_line
#         return True
#
#     return False
