.PHONY: help install run docker docker-down clean

help:
	@echo "Grain Size Analyzer - available targets:"
	@echo "  make install      Create .venv and install dependencies"
	@echo "  make run          Start the app (installs first if needed)"
	@echo "  make docker       Build and start via docker compose"
	@echo "  make docker-down  Stop the docker compose stack"
	@echo "  make clean        Remove .venv and Python build artifacts"

install:
	./install.sh

run:
	./run.sh

docker:
	docker compose up --build

docker-down:
	docker compose down

clean:
	rm -rf .venv
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
