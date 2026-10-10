# Makefile for keel
# All commands run inside the Docker container to maintain host hygiene

.PHONY: test lint demo inject eval clean

test:
	docker compose run --rm keel-dev pytest -q

lint:
	docker compose run --rm keel-dev ruff check .

demo:
	@echo "demo target not yet implemented (Phase 6)"

inject:
	@echo "inject target not yet implemented (Phase 2)"

eval:
	@echo "eval target not yet implemented (Phase 3)"

clean:
	docker compose down -v
	docker volume rm keel-keel-data 2>/dev/null || true