from api.lib.workflows.frame_extraction import frame_extraction_flow


def serve_workflows() -> None:
    frame_extraction_flow.serve(name="default", limit=1)


if __name__ == "__main__":
    serve_workflows()
