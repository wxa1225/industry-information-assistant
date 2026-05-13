.PHONY: help install test test-cov lint format migrate migrate-new run docker-build docker-up docker-down seed

# Default target
help:
	@echo "Available commands:"
	@echo "  install        Install all dependencies"
	@echo "  test           Run unit tests"
	@echo "  test-cov       Run tests with coverage report"
	@echo "  lint           Run linter (ruff)"
	@echo "  format         Format code with ruff"
	@echo "  migrate        Run pending database migrations"
	@echo "  migrate-new    Create a new migration (MSG='description')"
	@echo "  run            Start the development server"
	@echo "  docker-build   Build Docker image"
	@echo "  docker-up      Start all services with docker-compose"
	@echo "  docker-down    Stop all services"
	@echo "  seed           Seed the database with sample data"

# Dependencies
install:
	pip install -r backend/requirements.txt
	pip install -r backend/requirements-dev.txt

# Testing
test:
	cd backend && pytest app/tests/ -v

test-cov:
	cd backend && pytest app/tests/ -v --cov=app --cov-report=html --cov-report=term-missing

# Linting and formatting
lint:
	ruff check backend/app/

format:
	ruff format backend/app/
	ruff check backend/app/ --fix

# Database migrations
migrate:
	cd backend && alembic upgrade head

migrate-new:
ifndef MSG
	$(error MSG is required. Usage: make migrate-new MSG="add_user_table")
endif
	cd backend && alembic revision --autogenerate -m "$(MSG)"

# Development server
run:
	cd backend && uvicorn app.app_main:app --reload --host 0.0.0.0 --port 8000

# Docker
docker-build:
	docker build -t industry-info-assistant:latest -f backend/Dockerfile backend/

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

# Database seeding
seed:
	cd backend && python app/scripts/seed_industry_data.py

# Security scan
security:
	bandit -r backend/app/ -f json -o bandit-report.json
	safety check -r backend/requirements.txt
