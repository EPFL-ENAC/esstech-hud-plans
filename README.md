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

Plan point-cloud dependencies are included in the backend installation.


### Backend and workflows

In one shell, run:

```bash
make run-db
make db-upgrade
make run-backend
```

Database schema changes are managed explicitly with Alembic. Use
`make db-revision name="description"` to generate a revision and
`make db-downgrade` to roll back one revision.

The Prefect server is included in `make run-db`. In another shell, start the
local workflow deployment process:

```bash
make run-workflows
```

In Kubernetes, the API and workflow runner use the same backend image in
separate Deployments. The image entrypoint prepares SSH access and executes its
arguments. Its default command runs `start-api.sh`, which applies migrations
before starting Uvicorn. The runner overrides the command arguments with
`python -m api.lib.workflows`; an init container checks
`alembic current --check-heads` before allowing it to start.

Both pods use `USE_SCITAS=true` and `DATA_DIR=/mnt/scitas`, mounting the existing
SCITAS PVC at `/mnt/scitas`. They also mount the tus upload PVC at
`/mnt/tus-uploads` with `TUSD_UPLOAD_DIR=/mnt/tus-uploads`, so the runner can clean
up abandoned uploads. The runner enables Prefect's monitoring server through
`PREFECT_RUNNER_SERVER_ENABLE=true`, `PREFECT_RUNNER_SERVER_HOST=0.0.0.0`, and
`PREFECT_RUNNER_SERVER_PORT=8080`. Kubernetes restarts the runner on exit or
prolonged polling failure. Runner shutdown leaves deployment schedules active.

For the first rollout, keep the runner at zero replicas in every environment.
Drain active reconstructions, deploy the new backend image, and wait for API
startup and migrations to complete. Then set the runner to one replica, starting
with staging. Verify that a queued reconstruction starts and that terminating
the runner causes an automatic restart while the API stays available. Repeat
for the remaining environments. Replacing a runner can interrupt active runs;
this change does not add retries for interrupted reconstructions.

The Prefect container enables live log publishing and websocket streaming for
workflow log subscribers. Recreate or restart the Prefect container after
changing these settings.

The compose stack also includes a tusd container for chunked, resumable video
uploads. tusd stores upload chunks and `.info` files in `TUSD_UPLOAD_DIR`
(default `/tmp/hud-tusd-uploads`). This directory must be shared between the
tusd container and the backend, and must stay on a local disk. On machines
where `/tmp` is not shared with the docker daemon, set `TUSD_UPLOAD_DIR` to a
path under the repo (for example `backend/data/tusd-uploads`).

Set `TUSD_HOOK_SECRET` in `.env` to a random value (generate one with
`openssl rand -hex 32`). The API injects this internal credential into tusd
requests, and tusd forwards it to the upload hooks. Recreate the tusd container
after changing its hook configuration. Starting a TUS upload creates its metadata
row; finishing it marks that row uploaded. Uploads cannot be deleted while pending.

Upload metadata includes `uploaded_bytes` alongside `size_bytes`. tusd reports
progress approximately every five seconds during transfers and at request end;
completion records the full size after the file is persisted. The upload list and
detail endpoints expose these counts, including while an upload is pending.

The daily `tus-cleanup` flow marks abandoned pending uploads and reconstructions
waiting for them as failed before deleting expired staging files. It uses
`TUSD_UPLOAD_RETENTION_DAYS` (seven days by default), preserves recently modified
binaries, and removes orphan binaries after one day. Old pending uploads whose
staging files are already missing also become failed. Permanent uploads are kept.
If staging deletion fails, the next run retries it; database failures prevent
deletion. A missing staging directory causes the run to skip cleanup.

The API and workflow process must share the permanent `DATA_DIR/uploads` files
and the generated `DATA_DIR/workflows` artifacts (`DATA_DIR` defaults to
`backend/data`). Each permanent video is stored once under
`uploads/<upload_id>/input.<extension>` and can be reused by multiple reconstructions.
The `splat-generation/default` deployment runs FFmpeg, optionally selects frames
locally with the frame picker, then runs COLMAP and Brush. Submit a user upload
through `POST /buildings/{building_id}/reconstructions/from-upload`, or create a
building and its first reconstruction through
`POST /buildings/from-reconstruction/from-upload`. Both endpoints accept an
`upload_id` and workflow settings. FFmpeg and frame selection read the permanent
video directly. Each `workflows/<reconstruction_id>` directory contains only
generated artifacts: extracted frames (including raw frames when selection is
enabled), sparse COLMAP reconstructions, and `splat.ply` files. The source video
is never copied into the reconstruction directory or staged to SCITAS scratch.

Deleting a reconstruction removes its generated artifacts and preserves the
source video. Deleting an upload removes its metadata while retaining the
permanent file, so existing reconstructions can still read and serve their source.
Existing reconstruction paths and files are not migrated to this layout.

Keep `USE_SCITAS=false` for local execution. Set `USE_SCITAS=true` to run COLMAP
and Brush on SCITAS through SSH, Slurm, and Apptainer. FFmpeg and frame selection
run locally in both modes.

SCITAS execution requires:

- SSH access to `SCITAS_HOST` using `SCITAS_SSH_USERNAME` and
  `SCITAS_SSH_KEY_PATH`, with Slurm and Apptainer available on the cluster.
- The cluster export directory (`SCITAS_REMOTE_EXPORT_PATH`) mounted on the
  backend and workflow host at `SCITAS_MOUNT_EXPORT_PATH`. Set `DATA_DIR` to this
  same local mount path so both processes share their workflow data with SCITAS.
- Writable remote export and scratch directories, a valid `SCITAS_ACCOUNT`, and
  access to the configured COLMAP and Brush partitions.
- `hud-colmap_latest.sif` and `hud-brush_latest.sif` installed under
  `SCITAS_REMOTE_IMAGES_PATH` (see the image instructions below).

Jobs copy their workspace from export to scratch, execute there, and copy results
back even when the command fails. Logs are written directly to the mounted export.

The interactive API documentation will be available at [http://localhost:8000/docs](http://localhost:8000/docs).

### Frontend

In another shell, run:

```bash
make run-frontend
```

The website will be available at [http://localhost:9000](http://localhost:9000).

For an installable PWA, run `make run-pwa` (port 9001).
Production containers default to PWA mode and still support normal browser tabs.
See the [frontend PWA guide](frontend/README.md#browser-and-installed-app) for build
modes, HTTPS requirements, offline behavior, and the release checklist.


## Updating the terms and conditions

Terms content lives in `backend/api/terms/<version>/{en,fr,es}.md`. To publish a
new version:

1. Create a new version directory, for example `backend/api/terms/v2/`, with the
   `en`, `fr`, and `es` markdown files. English is the fallback for missing locales.
2. Set `TERMS_VERSION` to the new version in `backend/api/config.py`.

Every user is asked to accept the new version at their next request.


## Build and push Docker images

From the project root, run:
```bash
docker build \
    -t registry.rcp.epfl.ch/enac-it-poh/hud-<TOOL>:latest \
    -f docker/Dockerfile.<TOOL> .
```

where `<TOOL>` is:
- `ffmpeg` for the FFmpeg image
- `colmap` for the COLMAP image
- `brush` for the Brush image

The RCP registry continues to host the tool images used by SCITAS. Image builds
use fixed installation paths and require no LDAP identity arguments. Apptainer
runs the tools as the submitting user. The COLMAP launcher seeds its packaged
vocabulary into that user's `~/.cache/colmap` when absent, avoiding runtime downloads.

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

Place the resulting SIF files in `SCITAS_REMOTE_IMAGES_PATH` on the cluster.
The reconstruction workflow needs the COLMAP and Brush images; FFmpeg runs
locally and does not require a SCITAS image.
