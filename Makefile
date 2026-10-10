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
	docker compose run --rm -e PYTHONPATH=/workspace keel-dev keel run triage "Server alert: disk at 90 percent"
	docker compose run --rm -e PYTHONPATH=/workspace keel-dev keel queue
	docker compose run --rm -e PYTHONPATH=/workspace keel-dev keel eval --gate

inject:
	docker compose run --rm -e PYTHONPATH=/workspace keel-dev pytest tests/test_capabilities.py::test_injection_cannot_write -q

eval:
	docker compose run --rm -e PYTHONPATH=/workspace keel-dev keel eval --gate

clean:
	docker compose down -v
	docker volume rm keel-keel-data 2>/dev/null || true