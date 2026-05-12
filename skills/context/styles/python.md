# Python — project code style

This file is project-local at `.artifacts/styles/python.md`. The conductor injects its content into every coder brief whose `[FILE-SCOPE]` includes Python files. Edit freely; lives next to the project, not the user.

## Error handling
- Never use bare `except:` or `except Exception:` without re-raising. Catch the narrowest exception that the call site can recover from.
- Wrap third-party exceptions at module boundaries — surface domain-specific errors, not implementation leakage.
- `raise X from e` to preserve the cause chain. Never swallow with `pass`.
- Use `contextlib.suppress(...)` only for explicit, single-line "expected miss" cases (e.g. `FileNotFoundError` on best-effort cleanup).
- Library code does not call `sys.exit()`; it raises. Only top-level entry points exit.

## Ownership & state
- `@dataclass(frozen=True, slots=True)` over plain dicts when the shape is known. `TypedDict` for JSON-shaped boundary data.
- `pathlib.Path` everywhere — never raw strings for paths. `Path` objects flow through APIs; `str(p)` only at OS-call boundaries.
- No mutable default arguments. `def f(x: list[int] | None = None)` and assign inside the body.
- Prefer immutability — `tuple` over `list` for fixed-length records, `frozenset` for membership-only sets.
- Module-level state is forbidden in libraries. Configuration flows through constructors / function arguments.

## Layout
- Public functions have type hints on every parameter and return. Internal helpers are typed when they cross > 20 lines or two callers.
- One module = one cohesive responsibility. Split when a file passes ~400 LOC or grows two unrelated public surfaces.
- `__all__` declared explicitly in any module that is re-exported.
- `from __future__ import annotations` at the top of every module to enable lazy annotation eval.
- f-strings for all string interpolation. `%`-formatting and `.format()` only for logging templates that defer evaluation.

## Tooling
- `ruff check` and `ruff format` MUST pass before commit. Configure in `pyproject.toml` under `[tool.ruff]`.
- `mypy --strict` MUST pass on the full package. New `# type: ignore` requires `# type: ignore[reason]` and a tracking note.
- `pytest` is the only test runner. Use `pytest.mark.parametrize` for table-driven cases, fixtures over class-based setup.
- `pytest --cov` target ≥ 85% line coverage on library packages; binaries are excluded.
- `python -m <pkg>` is the run convention; avoid bare scripts in `bin/`.

## Documentation
- Every public function/class has a docstring. Google or NumPy style — pick one per project and keep consistent.
- Docstrings document `Args`, `Returns`, `Raises`. Examples in `Examples:` blocks for non-trivial APIs.
- Module docstrings state the module's single responsibility in one sentence.

## Common patterns to AVOID (operator-flagged)
- Bare `except:` or `except Exception:` without re-raise — catches `KeyboardInterrupt`, masks bugs.
- Mutable default arguments (`def f(x=[])`) — shared state across calls.
- `os.path` over `pathlib.Path` — string paths lose type information.
- `dict` as a struct when the shape is fixed — use `dataclass` or `TypedDict`.
- `print()` for diagnostics in library code — use `logging` with a module-level logger.
- `assert` for runtime validation — `assert` is stripped under `-O`. Use explicit `raise ValueError(...)`.
- Wildcard imports (`from x import *`) outside `__init__.py` curated re-exports.
- Returning `None` to signal "missing" when the function also returns objects — use `Optional[T]` in the type hint and document the contract.
