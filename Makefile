# Makefile for keel
# Container contract: the image is built by GitHub Actions and pulled
# from Docker Hub (see .github/workflows/build-image.yml). NEVER build
# locally. All test/lint commands run inside the pulled container.

.PHONY: test lint demo inject eval clean

# PYTHONPATH=/workspace ensures the bind-mounted source wins over the
# image's installed copy (editable in new images; belt-and-braces for old ones)
test:
	docker compose run --rm -e PYTHONPATH=/workspace keel-dev pytest -q

lint:
	docker compose run --rm -e PYTHONPATH=/workspace keel-dev ruff check .

demo:
	@echo "demo target not yet implemented (Phase 6)"

inject:
	@echo "inject target not yet implemented (Phase 2)"

eval:
	@echo "eval target not yet implemented (Phase 3)"

clean:
	docker compose down -v
	docker volume rm keel-keel-data 2>/dev/null || true