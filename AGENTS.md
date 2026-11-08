# Python development

- Follow [the Python coding guidelines](docs/python-coding-guidelines.md) for all Python code and tests.
- Use Arrange, Act, Assert; inject external dependencies and assert observable behavior.
- Keep unit tests independent of the filesystem, network, clock, environment, and local configuration.
- Name integration test files `test_*_integration.py`, or prefix integration tests in mixed files with `test_integration_`.
- Before finishing Python changes, run `uv run --locked ruff check .`, `uv run --locked ruff format --check .`, `uv run --locked pyrefly check`, and both pytest suites described in the guidelines.
