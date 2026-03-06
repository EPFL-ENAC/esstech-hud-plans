FROM python:3.13.6-bookworm
ENV UV_VERSION=0.9.13

# System dependencies
RUN apt update \
	&& apt install -y libglew-dev \
	ffmpeg \
	rclone \
	&& rm -rf /var/lib/apt/lists/*

RUN pip install "uv==$UV_VERSION"

WORKDIR /app

COPY uv.lock pyproject.toml /app/
COPY start.sh /app/
COPY api /app/api

RUN uv pip install --system --no-cache-dir -e /app
RUN mkdir -p /app/external/bin && ln -s $(which ffmpeg) /app/external/bin/ffmpeg

ENTRYPOINT ["sh", "start.sh"]
