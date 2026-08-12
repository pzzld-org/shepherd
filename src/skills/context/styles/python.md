# Python — project code style

Project-local at `.shepherd/styles/python.md` (`.artifacts/` legacy); injected as `[CODE-STYLE]` into coder briefs scoping Python files. Edit freely — lives next to the project.

## Error handling
- Never bare `except:`/`except Exception:` without re-raising; catch the narrowest recoverable exception, and wrap third-party exceptions at module boundaries into domain-specific errors.
- `raise X from e` to preserve the cause chain — never swallow with bare `pass`. `contextlib.suppress(...)` only for explicit single-line "expected miss" cases.
- Library code never calls `sys.exit()` — only top-level entry points exit.

## Ownership & state
- `@dataclass(frozen=True, slots=True)` over plain dicts when shape is known; `TypedDict` for JSON-shaped boundary data. `pathlib.Path` everywhere, `str(p)` only at OS-call boundaries.
- No mutable default arguments — `def f(x: list[int] | None = None)`, assign inside the body; `tuple` over `list` for fixed-length records, `frozenset` for membership-only sets.
- Module-level state forbidden in libraries — config via constructors/arguments.

## Layout
- Public functions type-hinted on every parameter/return; helpers hinted past 20 lines or two callers. One module = one responsibility, split past ~400 LOC.
- `__all__` declared explicitly in re-exported modules; `from __future__ import annotations` at the top of every module; f-strings for interpolation, `%`/`.format()` only for deferred-eval logging templates.

## Tooling
- `ruff check`/`ruff format`, `mypy --strict` MUST pass; new `# type: ignore` requires `# type: ignore[reason]` + tracking note.
- `pytest` is the only test runner (`pytest.mark.parametrize` for table-driven cases, fixtures over class-based setup); `pytest --cov` target ≥ 85% (binaries excluded).
- `python -m <pkg>` is the run convention, not `bin/` scripts.

## Documentation
- Every public function/class has a docstring (Google or NumPy, one per project): `Args`, `Returns`, `Raises`, `Examples:` for non-trivial APIs. Module docstrings state the module's responsibility in one sentence.

## Common patterns to AVOID (operator-flagged)
- `print()` for diagnostics in library code (use `logging`); `assert` for runtime validation (stripped under `-O`, use `raise ValueError(...)`).
- Wildcard imports (`from x import *`) outside `__init__.py` curated re-exports; returning `None` to signal "missing" alongside real return values — use `Optional[T]` and document it.
