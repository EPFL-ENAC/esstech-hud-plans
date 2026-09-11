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
	echo "Frontend not set up yet"
	cd frontend && npm run dev

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

test:
	cd backend && make test
