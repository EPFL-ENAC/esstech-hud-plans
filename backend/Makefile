env_path=../.env

install:
	uv venv --python 3.13 --allow-existing
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

test:
	uv run dotenv -f "$(env_path)" run pytest

lint:
	uv run pre-commit run --all-files
