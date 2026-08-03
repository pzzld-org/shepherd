# Go — project code style

This file is project-local at `.artifacts/styles/go.md`. The conductor injects its content into every coder brief whose `[FILE-SCOPE]` includes Go files. Edit freely; lives next to the project, not the user.

## Error handling
- Errors are values. Return them; don't `panic`. Library code never calls `panic` for recoverable conditions — only for truly impossible states (`unreachable` invariant violations).
- Wrap with `fmt.Errorf("op failed: %w", err)` to preserve the chain. The `%w` verb is the project default; reviewer rejects `%v` when the cause matters.
- Match with `errors.Is(err, target)` for sentinel errors and `errors.As(err, &target)` for typed errors. Never compare with `==` except for sentinels documented as comparable.
- Define sentinel errors as package-level `var ErrNotFound = errors.New("not found")`. Define typed errors as exported structs implementing `Error()`.
- `panic`/`recover` is reserved for the top of a goroutine that must not crash the process. Never as control flow.

## Ownership & state
- Struct embedding sparingly — only when the embedded type's interface is genuinely "is-a". Prefer composition with named fields when in doubt.
- Pointer receivers when the method mutates or the struct is large; value receivers otherwise. Within a type, keep the receiver style consistent.
- Goroutines have a clear owner that is responsible for their termination. Every `go` statement has a documented exit path (`context.Context` cancellation, channel close, `sync.WaitGroup`).
- Channels are typed and directional in signatures (`chan<- T`, `<-chan T`).
- No global mutable state. Configuration flows through constructors. `sync.Once` for genuine lazy init only.

## Layout
- Package names are short, lowercase, no underscores or camelCase. Package = single responsibility.
- Files within a package group by feature, not by Go construct (no `types.go` / `funcs.go` split).
- Public API at the top of each file; helpers below. Tests in `_test.go` siblings.
- `internal/` for package-private surface. Exported items live at the path consumers should import from.
- One module per repo by default; multi-module repos require an explicit reason.

## Concurrency
- `context.Context` is the first argument of every function that does I/O or blocks.
- Cancellation flows from the top — every long-running call honors `ctx.Done()`.
- `sync.Mutex` is unexported and embedded near the field it protects, with a comment naming the invariant.
- `time.After` in a `select` leaks until the timer fires — use `time.NewTimer` with `Stop()` for hot paths.

## Tooling
- `gofmt` / `goimports` are mandatory pre-commit. CI rejects unformatted code.
- `golangci-lint run` MUST pass with the project's `.golangci.yml`. New lint disables require an inline `//nolint:rule // reason` and a tracking note.
- `go vet ./...` is part of CI. Race detector (`go test -race ./...`) runs in CI on every PR.
- Tests are table-driven: `tests := []struct{ name string; in T; want U }{...}` with `t.Run(tt.name, ...)`. Use `testify` only when the standard library is genuinely insufficient.

## Documentation
- Every exported identifier has a doc comment that begins with the identifier's name (Go convention).
- Package doc comment is in `doc.go` or at the top of the package's primary file. One paragraph stating the package's responsibility.
- Examples use `Example_*` functions in `_test.go` so they appear in `go doc` and run as part of the test suite.

## Common patterns to AVOID (operator-flagged)
- `init()` for non-trivial work — testability suffers. Use explicit constructors.
- Naked returns from functions longer than a few lines — they obscure what's returned.
- Empty interface `interface{}` (or `any` in modern Go) without immediate type assertion — pushes runtime checks up the stack.
- Returning concrete types when the consumer only needs an interface — accept interfaces, return structs (where it makes sense).
- `panic` in libraries — surfaces at the wrong layer and breaks compose-ability.
- Goroutine leaks via unbuffered channel writes with no reader — every `go` has a known exit.
- `time.Sleep` in tests — use channels, `time.Tick` mocked, or fake clocks.
- Exporting fields that should be set only via a constructor — provide `NewFoo(...)` and keep fields unexported.
