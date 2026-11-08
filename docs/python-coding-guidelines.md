# Python coding guidelines

## Unit testing

- All unit tests shall follow the AAA pattern: Arrange, Act, Assert.
- Unit tests shall test a unit in isolation.
  - Mock or fake external boundaries (filesystem/network/time/process), not internal implementation details.
  - Do not call real external services in unit tests.
- Prefer dependency injection over patching/mocking global functions or modules.
  - Design code so dependencies can be provided explicitly in tests.
- Test behavior and outcomes, not implementation details.
- If a test mainly validates calls on mocks, reconsider the test design and prefer asserting observable behavior.
- Tests must be deterministic and isolated.
  - Avoid hidden dependencies on wall-clock time, timezones, randomness, or network, unless explicitly marked as integration tests.
  - Use fixed seeds for tests involving random behavior.
  - Real external service calls are only allowed in explicit integration tests.

## Running tests

- Name integration test files `test_*_integration.py`. In mixed suites, prefix individual integration test names with `test_integration_`.
- Pytest applies the `integration` marker to these names, including tests written with the standard library's `unittest`.
- Run isolated unit tests with `uv run --locked pytest -m "not integration"` and integration tests with `uv run --locked pytest -m integration`.
- Run both suites with `uv run --locked pytest`.
