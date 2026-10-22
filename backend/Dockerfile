FROM python:3.12-bookworm
ENV UV_VERSION=0.9.13

# System dependencies
RUN apt update \
	&& apt install -y libglew-dev \
	ffmpeg \
	rclone \
	rsync \
	&& rm -rf /var/lib/apt/lists/*

RUN pip install "uv==$UV_VERSION"

WORKDIR /app

COPY uv.lock pyproject.toml /app/
COPY alembic.ini /app/
COPY start.sh /app/
COPY api /app/api
COPY migrations /app/migrations

RUN uv sync --frozen --no-dev --no-cache
ENV PATH="/app/.venv/bin:$PATH"
RUN mkdir -p /app/external/bin && ln -s $(which ffmpeg) /app/external/bin/ffmpeg

ENTRYPOINT ["sh", "start.sh"]
