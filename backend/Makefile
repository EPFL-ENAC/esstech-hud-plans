env_path=../.env

install:
	uv venv --python 3.12 --allow-existing
	uv pip install -e .[dev]


.PHONY: install-external-softwares-macos
install-external-softwares-macos:
	./scripts/macos/install_ffmpeg.sh
	./scripts/macos/install_colmap.sh
	./scripts/macos/install_brush.sh

.PHONY: install-external-softwares-linux
install-external-softwares-linux:
	./scripts/linux/install_ffmpeg.sh
	./scripts/linux/install_colmap.sh
	./scripts/linux/install_brush.sh

run:
	uv run dotenv -f "$(env_path)" run uvicorn api.main:app --reload

run-workflows:
	uv run dotenv -f "$(env_path)" run python -m api.lib.workflows

test:
	uv run dotenv -f "$(env_path)" run pytest

db-upgrade:
	uv run dotenv -f "$(env_path)" run alembic upgrade head

db-downgrade:
	uv run dotenv -f "$(env_path)" run alembic downgrade -1

db-revision:
	uv run dotenv -f "$(env_path)" run alembic revision --autogenerate -m "$(name)"

lint:
	uv run pre-commit run --all-files
