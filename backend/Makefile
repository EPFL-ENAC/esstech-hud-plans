env_path=../.env

install:
	uv venv --python 3.13 --allow-existing
	uv pip install -e .[dev]


.PHONY: install-external-softwares
install-external-softwares:
	./scripts/install_external_softwares.sh

run:
	uv run dotenv -f "$(env_path)" run uvicorn api.main:app --reload

test:
	uv run dotenv -f "$(env_path)" run pytest

lint:
	uv run pre-commit run --all-files
