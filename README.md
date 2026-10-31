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

The API and workflow process must share the `backend/data/workflows` directory.
The `splat-generation/default` deployment runs FFmpeg, optionally selects frames
locally with the frame picker, then runs COLMAP and Brush. Submit a user upload
through `POST /buildings/{building_id}/reconstructions/from-upload`, or create a
building and its first reconstruction through
`POST /buildings/from-reconstruction/from-upload`. Both endpoints accept an
`upload_id` and workflow settings. Submitted videos, extracted frames (including
raw frames when selection is enabled), sparse COLMAP reconstructions, and generated
`splat.ply` files are retained there until removed manually.

Keep `USE_SCITAS=false` for local execution. The retired RunAI backend and
`/splats/*` API are no longer available, along with the `/advanced`, `/splat/:id`,
and historical `/admin` export pages. Existing generation files are left on disk.

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
