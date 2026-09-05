from api.lib.workflows.splat_generation import splat_generation_flow


def serve_workflows() -> None:
    splat_generation_flow.serve(name="default", limit=1)


if __name__ == "__main__":
    serve_workflows()
