#!/bin/sh
set -eu

alembic upgrade head

exec uvicorn \
    --host=0.0.0.0 \
    --timeout-keep-alive=0 \
    api.main:app
