# EssentialTech HUD Planning App

## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/) Python package and project manager
- [npm](https://docs.npmjs.com/) Node.js package manager
- Make


## Deploying locally

Setup your environment by running:

```bash
make install
```

Install the external FFmpeg, COLMAP, and Brush executables used by the local
workflow runner:

```bash
cd backend
make install-external-softwares-macos
# On Linux, use: make install-external-softwares-linux
```

> [!NOTE]
> By default, dependencies to generate blueprints in the backend are not installed. To install them, run `cd backend && uv pip install -e .[blueprint]`.


### Backend and workflows

In one shell, run:

```bash
make run-db
make run-backend
```

The Prefect server is included in `make run-db`. In another shell, start the
local workflow deployment process:

```bash
make run-workflows
```

The Prefect container enables live log publishing and websocket streaming for
workflow log subscribers. Recreate or restart the Prefect container after
changing these settings.

The API and workflow process must share the `backend/data/workflows` directory.
The `splat-generation/default` deployment runs FFmpeg, optionally selects frames
locally with the frame picker, then runs COLMAP and Brush. It is submitted through
`POST /workflows/splat-generation`. Submitted videos, extracted frames (including
raw frames when selection is enabled), sparse COLMAP reconstructions, and generated
`splat.ply` files are retained there until removed manually.

The interactive API documentation will be available at [http://localhost:8000/docs](http://localhost:8000/docs).

### Frontend

In another shell, run:

```bash
make run-frontend
```

The website will be available at [http://localhost:9000](http://localhost:9000).


## Build and push Docker images

From the project root, run:
```bash
docker build -t registry.rcp.epfl.ch/enac-it-poh/hud-<TOOL>:latest -f docker/Dockerfile.<TOOL> . \
    --build-arg LDAP_GROUPNAME=<GROUP-NAME> \
    --build-arg LDAP_GID=<GROUP-ID> \
    --build-arg LDAP_USERNAME=<USERNAME> \
    --build-arg LDAP_UID=<USER-ID>
```

where `<TOOL>` is:
- `ffmpeg` for the FFmpeg image
- `colmap` for the COLMAP image
- `brush` for the Brush image

To get the user and group information, run the following command:
```bash
ssh <username>@jumphost.rcp.epfl.ch -o StrictHostKeychecking=no 'echo -e "-> uid: $(id -u)\n-> gid: $(id -g)\n-> groups $(id)"'
```

Then, push the image to the registry:
```bash
docker login registry.rcp.epfl.ch
docker push registry.rcp.epfl.ch/enac-it-poh/hud-<TOOL>:latest
```


## Pull images with Apptainer

To pull the images with Apptainer, run:
```bash
apptainer remote login --username <username> registry.rcp.epfl.ch
apptainer pull docker://registry.rcp.epfl.ch/enac-it-poh/hud-<TOOL>:latest
```

Alternatively, you can build the SIF image locally:
```bash
apptainer build hud-<TOOL>_latest.sif docker://registry.rcp.epfl.ch/enac-it-poh/hud-<TOOL>:latest
```
