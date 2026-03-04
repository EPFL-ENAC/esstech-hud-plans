FROM python:3.13.6-bookworm
ENV UV_VERSION=0.9.13

# RunAI
RUN curl -sLo /tmp/runai https://rcp-caas-prod.rcp.epfl.ch/cli/linux \
	&& install /tmp/runai /usr/local/bin/runai \
	&& rm /tmp/runai \
	&& mkdir -p ~/.kube \
	&& curl https://wiki.rcp.epfl.ch/public/files/kube-config.yaml -o ~/.kube/config && chmod 600 ~/.kube/config

# How to run `runai login` (in Python backend)? Requires web browser interaction

# System dependencies
RUN apt update \
	&& apt install -y libglew-dev \
	sshfs \
	rclone \
	&& rm -rf /var/lib/apt/lists/*

RUN pip install "uv==$UV_VERSION"

WORKDIR /app

COPY uv.lock pyproject.toml /app/
COPY start.sh /app/
COPY api /app/api
COPY data /app/data

RUN uv pip install --system --no-cache-dir -e /app

ENTRYPOINT ["sh", "start.sh"]
