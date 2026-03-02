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

> [!NOTE]
> By default, dependencies to generate blueprints in the backend are not installed. To install them, run `cd backend && uv pip install -e .[blueprint]`.


### Backend

In one shell, run:

```bash
make run-backend
```

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
docker build -t hud-colmap -f docker/Dockerfile.colmap . \
    --build-arg LDAP_GROUPNAME=<group-name> \
    --build-arg LDAP_GID=<group-id> \
    --build-arg LDAP_USERNAME=<username> \
    --build-arg LDAP_UID=<user-id>
```

To get the user and group information, run the following command:
```bash
ssh <username>@jumphost.rcp.epfl.ch -o StrictHostKeychecking=no 'echo -e "-> uid: $(id -u)\n-> gid: $(id -g)\n-> groups $(id)"'
```
