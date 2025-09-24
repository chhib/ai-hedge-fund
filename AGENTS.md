# Repository Guidelines

## Start Here
Always open `PROJECT_LOG.md` at the start of every session to capture current context. Check any agent-specific logs or instructions after reviewing the project log and reconcile conflicts before proceeding; update the relevant log when you wrap up.

## Project Structure & Module Organization
Core Python sources live under `src/` (agents, tools, backtesting). CLI entry points are in `src/main.py` and `src/backtester.py`. The web app sits in `app/` with FastAPI backend code in `app/backend/` and the Vite/React frontend in `app/frontend/`. Tests mirror runtime code in `tests/`, with Börsdata work tracked via fixtures under `tests/backtesting/`.

## Build, Test, and Development Commands
Install dependencies with `poetry install`. Run the hedge fund CLI via `poetry run python src/main.py --ticker AAPL`. Launch the backtesting runner with `poetry run backtester --help` to explore options. For the web UI, execute `npm install` then `npm run dev` inside `app/frontend/`, and `poetry run uvicorn main:app --reload` inside `app/backend/`.

## Coding Style & Naming Conventions
Use 4-space indentation and follow Black formatting (`poetry run black .`), respecting the configured 420-character line limit. Keep imports sorted with `poetry run isort .` and lint Python with `poetry run flake8`. Frontend code follows the default Vite + ESLint + Prettier conventions; prefer PascalCase for components and camelCase for hooks/utilities.

## Testing Guidelines
Run `poetry run pytest` from the repo root; backtesting suites live in `tests/backtesting/`. Add Börsdata fixtures or mocks when covering new endpoints, and ensure rate-limit behavior (100 calls/10 seconds) is validated. Name test modules with the `test_*.py` pattern and keep assertions focused on Börsdata data shapes.

## Commit & Pull Request Guidelines
Follow the existing Conventional Commit style (`fix:`, `feat:`, `chore:`) observed in `git log`. Each PR should summarize scope, link any tracked issues, and note updates to Börsdata integration or rate-limiting logic. Include screenshots or CLI output when changes affect user-visible behavior.

## Börsdata Integration Focus
Every contribution must advance or respect the ongoing migration to Börsdata. Verify `.env` handling for `BORSDATA_API_KEY`, retire legacy FinancialDatasets code paths, and document new endpoint usage in `PROJECT_LOG.md` before concluding work.
