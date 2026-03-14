# Claude Code Configuration

## Sandbox Settings
- **Sandbox**: `none` - Allows AI to execute commands directly as your user, which is necessary for tools like poetry that manage environments.

## Approval Settings
- **Ask for approval**: `never` - Commands execute without requiring user approval.

## Allowed Domains
The following domains are whitelisted for downloads and API access:
- `github.com`
- `raw.githubusercontent.com`
- `*.github.com`
- `api.github.com`
- `borsdata.se`
- `*.borsdata.se`
- `apidoc.borsdata.se`

## Development Environment
This configuration supports the AI hedge fund project's development workflow, including:
- Poetry environment management
- GitHub repository access
- Börsdata API integration

---

# Repository Guidelines

## Start Here
At the start of every session:
1. Read `logs/PROJECT_SUMMARY.md` for current status, goals, and architecture overview
2. Read the latest session file (currently `logs/sessions/session_061.md`) for recent context
3. Check any agent-specific logs and reconcile conflicts before proceeding

When wrapping up a session:
1. Add your session entry to the current session file (e.g., `logs/sessions/session_061.md`)
2. Update `logs/PROJECT_SUMMARY.md` if there are significant status changes
3. When a session file reaches 10 sessions, create the next file (e.g., `session_071.md`)

**Session file structure**: `logs/sessions/session_NNN.md` contains sessions N through N+9.

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

## Verification Policy
Always verify your work by running it before considering a task complete. This means:
- **Scripts**: Run the script with a small `--limit` or dry-run flag to confirm it parses, imports resolve, and the happy path executes without errors.
- **Pure functions**: Test new logic inline with `poetry run python -c "..."` to confirm expected behavior (e.g., tokenization, matching, parsing).
- **CLI changes**: Run `--help` to verify argument parsing, then a real invocation.
- **IBKR scripts**: If the gateway is not running, at minimum run with `--skip-isin --limit 2` to verify the script runs end-to-end (errors from missing gateway are expected and OK). For full verification, start the gateway: `cd clientportal.gw && bin/run.sh root/conf.yaml`, authenticate at `https://localhost:5001`, then run the script with `--ibkr-port 5001`.
- **Tests**: Run `poetry run pytest` (or the relevant subset) after any code change.
- If a script or test requires external services (IBKR gateway, APIs), note what was verified offline vs what needs live testing.

## Börsdata Integration Focus
Every contribution must advance or respect the ongoing migration to Börsdata. Verify `.env` handling for `BORSDATA_API_KEY`, retire legacy FinancialDatasets code paths, and document new endpoint usage in the session log before concluding work.