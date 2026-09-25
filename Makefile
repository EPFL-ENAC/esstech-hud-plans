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
	cd frontend && bash -c 'trap "exit 0" INT TERM HUP; while true; do npm run dev; code=$$?; if [ "$$code" -eq 0 ] || [ "$$code" -ge 128 ]; then break; fi; echo "npm run dev exited unexpectedly (code $$code), restarting..."; sleep 1; done'

run-frontend-pwa:
	cd frontend && bash -c 'trap "exit 0" INT TERM HUP; while true; do npm run dev:pwa; code=$$?; if [ "$$code" -eq 0 ] || [ "$$code" -ge 128 ]; then break; fi; echo "npm run dev:pwa exited unexpectedly (code $$code), restarting..."; sleep 1; done'

run-db:
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
	make run-db && make db-upgrade && trap 'kill $(jobs -p) 2>/dev/null; make stop-db' INT && { make run-workflows & make run-backend & make run-frontend & wait; }

run-all-pwa:
	make run-db && make db-upgrade && trap 'kill $(jobs -p) 2>/dev/null; make stop-db' INT && { make run-workflows & make run-backend & make run-frontend-pwa & wait; }

test:
	cd backend && make test
