install:
	uvx pre-commit install --install-hooks
	cd backend && make install
	cd frontend && npm install
	test -f .env || cp .env.example .env
	make run-db && make db-upgrade && make stop-db

lint:
	uvx pre-commit run --all-files
	cd frontend && npm run lint && npm run format

run-backend:
	cd backend && make run

run-workflows:
	cd backend && make run-workflows

run-frontend:
	cd frontend && bash -c 'trap "exit 0" INT TERM HUP; while true; do npm run dev:pwa; code=$$?; if [ "$$code" -eq 0 ] || [ "$$code" -ge 128 ]; then break; fi; echo "npm run dev:pwa exited unexpectedly (code $$code), restarting..."; sleep 1; done'

tusd-dir:
	@dir=$$(sed -n 's/^TUSD_UPLOAD_DIR=//p' .env 2>/dev/null); dir=$${dir:-/tmp/hud-tusd-uploads}; mkdir -p "$$dir"; test -w "$$dir" || echo "WARNING: $$dir is not writable by the current user; fix ownership (see README)" >&2

run-db: tusd-dir
	docker compose up -d

stop-db:
	docker compose down

drop-db:
	docker compose down --volumes

db-upgrade:
	cd backend && make db-upgrade

db-downgrade:
	cd backend && make db-downgrade

db-revision:
	cd backend && make db-revision name="$(name)"

run-all:
	make run-db && trap 'kill "$${backend_pid}" "$${frontend_pid}" "$${workflows_pid}" 2>/dev/null; make stop-db' INT TERM HUP && { make run-workflows & workflows_pid=$$!; make run-backend & backend_pid=$$!; make run-frontend & frontend_pid=$$!; wait; }

test:
	cd backend && make test
