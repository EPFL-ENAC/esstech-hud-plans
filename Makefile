install:
	uvx pre-commit install --install-hooks
	cd backend && make install
	cd frontend && npm install
	touch .env

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

reset-db:
	docker compose down --volumes
	docker compose up -d

test:
	cd backend && make test
