#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
version=$(node -p "require('./package.json').version")

tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-packed-tar.XXXXXX")
server_pid=""
cleanup() {
  if [[ -n "$server_pid" ]]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  find "$tmp_dir" -depth -delete
}
trap cleanup EXIT
mkdir -p "$tmp_dir/package"
printf 'first member\n' > "$tmp_dir/package/early.txt"
for index in $(seq 1 5000); do
  printf 'member %s\n' "$index" > "$tmp_dir/package/member-${index}.txt"
done

archive="$tmp_dir/archive.tgz"
(cd "$tmp_dir" && tar -czf "$archive" package)

if tar --version 2>/dev/null | grep -q 'GNU tar'; then
  if (set -o pipefail; tar -tzf "$archive" | grep -q 'package/early.txt'); then
    printf 'GNU tar early-match pipeline unexpectedly succeeded\n' >&2
    exit 1
  fi
  printf 'ok: GNU tar + pipefail negative control reproduces producer SIGPIPE\n'
else
  printf 'skip: GNU tar is unavailable on this host; static workflow check covers the production pipeline\n'
fi

listing="$tmp_dir/archive.list"
tar -tzf "$archive" > "$listing"
grep -Fxq 'package/early.txt' "$listing"
grep -Fxq 'package/member-5000.txt' "$listing"
printf 'ok: full tar listing is drained before grep filtering\n'

fixture="$tmp_dir/cold-cache-fixture"
mkdir -p \
  "$fixture/scripts" \
  "$fixture/packages/component-runtime" \
  "$fixture/packages/harness-claude" \
  "$fixture/packages/harness-codex" \
  "$fixture/packages/harness-pi" \
  "$fixture/packages/scripts" \
  "$fixture/node-root/node_modules/.bin" \
  "$fixture/registry/package"
cp scripts/test-packed-plugin.sh "$fixture/scripts/test-packed-plugin.sh"
printf 'fixture component\n' > "$fixture/shepherd-component.wasm"

cat > "$fixture/node-root/node_modules/.bin/jco" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat > "$fixture/scripts/stage-component-runtime.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
runtime="$1/packages/component-runtime/runtime"
mkdir -p "$runtime"
printf 'export const fixture = true;\n' > "$runtime/shepherd-component.js"
printf 'fixture component\n' > "$runtime/shepherd-component.wasm"
EOF
cat > "$fixture/scripts/stage-pi-carrier.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
package_root="$1/packages/harness-pi"
mkdir -p "$package_root/prompts" "$package_root/agents"
for role in auditor coder conductor critic discovery engineer planter shepherd worker; do
  printf 'fixture prompt for %s\n' "$role" > "$package_root/prompts/$role.md"
done
for role in auditor coder conductor critic discovery engineer worker; do
  {
    printf '%s\n' '---'
    printf 'name: "shepherd:%s"\n' "$role"
    printf '%s\n' 'tools: read, subagent'
    printf '%s\n' 'model: model-required/model-required'
    printf '%s\n' 'subagentOnlyExtensions: ../src/extension.mjs'
    printf '%s\n' 'maxSubagentDepth: 2'
    printf '%s\n' '---' "fixture agent for $role"
  } > "$package_root/agents/$role.md"
done
cat > "$package_root/.shepherd-generated.json" <<'JSON'
{
  "schema": "shepherd.compiled-tree/3",
  "target": "pi",
  "roles": [
    {"role": "conductor", "model_hint": "reasoning-high", "model": null, "capabilities": ["dispatch"]},
    {"role": "critic", "model_hint": "standard", "model": null, "capabilities": ["read"]},
    {"role": "engineer", "model_hint": "reasoning-high", "model": null, "capabilities": ["dispatch"]},
    {"role": "worker", "model_hint": "standard", "model": null, "capabilities": ["read"]}
  ]
}
JSON
EOF
cat > "$fixture/scripts/stage-distribution-legal.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
for package in component-runtime harness-claude harness-codex harness-pi; do
  package_root="$1/packages/$package"
  mkdir -p "$package_root/THIRD_PARTY_LICENSES"
  printf 'fixture license\n' > "$package_root/LICENSE"
  printf 'fixture notices\n' > "$package_root/THIRD_PARTY_NOTICES.md"
  printf 'fixture dependency license\n' \
    > "$package_root/THIRD_PARTY_LICENSES/0000000000000000000000000000000000000000000000000000000000000000.txt"
done
EOF
chmod +x \
  "$fixture/node-root/node_modules/.bin/jco" \
  "$fixture/scripts/stage-component-runtime.sh" \
  "$fixture/scripts/stage-pi-carrier.sh" \
  "$fixture/scripts/stage-distribution-legal.sh" \
  "$fixture/scripts/test-packed-plugin.sh"

cat > "$fixture/registry/package/package.json" <<'EOF'
{
  "name": "@bytecodealliance/preview2-shim",
  "version": "0.20.1"
}
EOF
(
  cd "$fixture/registry/package"
  npm pack --ignore-scripts --loglevel=error \
    --pack-destination "$fixture/registry" >/dev/null
)
dependency_tarball="$fixture/registry/bytecodealliance-preview2-shim-0.20.1.tgz"
test -f "$dependency_tarball"

cat > "$fixture/serve-dependency.mjs" <<'EOF'
import { createReadStream, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';

const [portFile, tarball] = process.argv.slice(2);
const server = createServer((request, response) => {
  if (request.url !== '/preview2-shim.tgz') {
    response.writeHead(404).end();
    return;
  }
  response.writeHead(200, { 'content-type': 'application/octet-stream' });
  createReadStream(tarball).pipe(response);
});
server.listen(0, '127.0.0.1', () => {
  writeFileSync(portFile, String(server.address().port));
});
EOF
port_file="$fixture/registry.port"
node "$fixture/serve-dependency.mjs" "$port_file" "$dependency_tarball" &
server_pid=$!
for _ in $(seq 1 100); do
  if [[ -s "$port_file" ]]; then
    break
  fi
  if ! kill -0 "$server_pid" 2>/dev/null; then
    break
  fi
  sleep 0.01
done
test -s "$port_file"
registry_port=$(<"$port_file")

cat > "$fixture/packages/component-runtime/package.json" <<EOF
{
  "name": "@pzzld/component-runtime",
  "version": "$version",
  "type": "module",
  "dependencies": {
    "@bytecodealliance/preview2-shim": "http://127.0.0.1:${registry_port}/preview2-shim.tgz"
  }
}
EOF
for package in claude codex pi; do
  case "$package" in
    claude) published='claude-shepherd' ;;
    codex) published='codex-shepherd' ;;
    pi) published='pi-shepherd' ;;
  esac
  cat > "$fixture/packages/harness-$package/package.json" <<EOF
{
  "name": "@pzzld/$published",
  "version": "$version",
  "type": "module",
  "dependencies": {
    "@pzzld/component-runtime": "$version"
  }
}
EOF
done
cat > "$fixture/packages/scripts/test-active-adapters.mjs" <<'EOF'
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';

const packageScope = process.argv[3];
const dependency = join(
  dirname(packageScope),
  '@bytecodealliance',
  'preview2-shim',
  'package.json',
);
if (!existsSync(dependency)) {
  throw new Error(`packed install did not resolve ${dependency}`);
}
EOF

cold_cache="$fixture/empty-npm-cache"
mkdir -p "$cold_cache"
if (
  cd "$fixture"
  npm_config_cache="$cold_cache" \
    npm_config_registry="http://127.0.0.1:${registry_port}/" \
    SHEPHERD_COMPONENT_NODE_ROOT="$fixture/node-root" \
    SHEPHERD_COMPONENT_WASM="$fixture/shepherd-component.wasm" \
    bash scripts/test-packed-plugin.sh
); then
  printf 'ok: packed consumer install resolves an exact dependency from a cold npm cache\n'
else
  printf 'packed consumer install depends on ambient npm cache state\n' >&2
  exit 1
fi
