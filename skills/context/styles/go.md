# Go — project code style

Project-local at `.shepherd/styles/go.md` (`.artifacts/` legacy); injected as `[CODE-STYLE]` into briefs scoping Go files. Edit freely — lives next to the project.

## Error handling
- Errors are values — return them, never `panic` for recoverable conditions; `panic` only for impossible states, reserved for the top of a goroutine, never control flow.
- Wrap with `fmt.Errorf("op failed: %w", err)` — reviewer rejects `%v` when the cause matters. Match with `errors.Is`/`errors.As`; never `==` except documented sentinel comparisons.
- Sentinel errors: package-level `var ErrNotFound = errors.New("not found")`. Typed errors: exported structs implementing `Error()`.

## Ownership & state
- Struct embedding only when the embedded interface is "is-a"; prefer composition otherwise.
- Pointer receivers when the method mutates or the struct is large; value receivers otherwise, consistent per type.
- Every goroutine has a clear owner and exit path (`ctx` cancellation, channel close, `sync.WaitGroup`); channels typed/directional (`chan<- T`, `<-chan T`). No global mutable state — config via constructors; `sync.Once` for lazy init only.

## Layout
- Package names short, lowercase, no underscores/camelCase; single responsibility. Files group by feature not construct (no `types.go`/`funcs.go` split); public API at top, helpers below, tests in `_test.go` siblings.
- `internal/` for package-private surface. One module per repo by default; multi-module repos need an explicit reason.

## Concurrency
- `context.Context` is the first argument of every I/O or blocking function; cancellation flows top-down via `ctx.Done()`.
- `sync.Mutex` unexported, embedded near the field it protects, with a comment naming the invariant. `time.After` in a `select` leaks until the timer fires — use `time.NewTimer` + `Stop()`.

## Tooling
- `gofmt`/`goimports` mandatory pre-commit; CI rejects unformatted code. `golangci-lint run` MUST pass — new lint disables need inline `//nolint:rule // reason` + a tracking note.
- `go vet ./...` and `go test -race ./...` run in CI on every PR. Tests table-driven (`tests := []struct{...}` + `t.Run`); `testify` only when stdlib is genuinely insufficient.

## Documentation
- Every exported identifier has a doc comment starting with its own name; package doc comment in `doc.go` or the primary file. `Example_*` functions in `_test.go` so examples appear in `go doc` and run as tests.

## Common patterns to AVOID (operator-flagged)
- `init()` for non-trivial work (use explicit constructors); naked returns from long functions; empty `interface{}`/`any` without immediate type assertion.
- Returning concrete types when the consumer only needs an interface; goroutine leaks via unbuffered channel writes with no reader.
- `time.Sleep` in tests (use channels/fake clocks); exporting fields settable only via a constructor — provide `NewFoo(...)`, keep fields unexported.
