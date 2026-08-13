#!/usr/bin/env node
// packages/scripts/check-deps.mjs -- the npm-side analogue of
// scripts/check-features.sh: enforce the adapter dependency rule.
//
// WHY THIS EXISTS.
//
// Three harness adapters (@fl03/harness-claude, @fl03/harness-codex,
// @fl03/harness-pi) sit over one shared core (@fl03/compiler, plus the Rust
// engine behind the CLI binary). That split only holds if no adapter ever
// depends on another adapter -- the moment `harness-codex` names
// `harness-claude` in its `dependencies`, installing the Codex adapter drags
// in Claude's runtime too, and the "thin adapter over one core" property is
// gone with nothing anywhere reporting it. `npm ls` will not catch this: a
// workspace with a stray cross-adapter dependency installs and resolves
// cleanly, because npm has no opinion about which packages may depend on
// which. So the rule is checked here, not just documented in READMEs.
//
// The three rules:
//   1. No `@fl03/harness-*` package may depend on another `@fl03/harness-*`
//      package, in any dependency field.
//   2. A `@fl03/harness-*` package's `@fl03/*`-scoped dependencies must be
//      either `@fl03/compiler` or a platform binary package (reserved prefix
//      `@fl03/cli-*`, following the `@biomejs/cli-<platform>` precedent named
//      in plan.md W4-S1 -- not populated until that step lands, but the
//      allowlist exists now so this gate does not need rewriting the day
//      they do).
//   3. `@fl03/compiler` itself must not depend on any `@fl03/harness-*`
//      package -- it is the shared core beneath the adapters, never the
//      reverse.
//
// Usage:
//   node packages/scripts/check-deps.mjs              # check packages/
//   node packages/scripts/check-deps.mjs --self-test   # prove the rules can fail
//
// `--self-test` matters as much as the checks: a rule that cannot fail on a
// deliberately broken fixture is not checking anything, and would pass
// silently forever (the same discipline scripts/check-workspace.sh and
// scripts/check-plugin.sh already apply to the Rust workspace and the plugin
// layout).

import { existsSync, mkdtempSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..");
const PACKAGES_DIR = join(REPO_ROOT, "packages");

const ADAPTER_PREFIX = "@fl03/harness-";
const COMPILER_NAME = "@fl03/compiler";
const PLATFORM_BINARY_PREFIX = "@fl03/cli-";
const SCOPE_PREFIX = "@fl03/";

const DEP_FIELDS = ["dependencies", "devDependencies", "peerDependencies", "optionalDependencies"];

// --------------------------------------------------------------------------
// Package loading.
// --------------------------------------------------------------------------

function readPackageJson(pkgDir) {
  const path = join(pkgDir, "package.json");
  if (!existsSync(path)) return null;
  return JSON.parse(readFileSync(path, "utf8"));
}

function loadPackages(packagesRoot) {
  if (!existsSync(packagesRoot)) return [];
  return readdirSync(packagesRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => ({ dir: join(packagesRoot, entry.name), manifest: readPackageJson(join(packagesRoot, entry.name)) }))
    .filter((pkg) => pkg.manifest && typeof pkg.manifest.name === "string");
}

function allDeps(manifest) {
  const merged = {};
  for (const field of DEP_FIELDS) {
    Object.assign(merged, manifest[field] ?? {});
  }
  return merged;
}

// --------------------------------------------------------------------------
// The rules. Each takes the loaded package list and returns a list of
// human-readable violations.
// --------------------------------------------------------------------------

function ruleNoAdapterToAdapter(pkgs) {
  const bad = [];
  for (const { manifest } of pkgs) {
    const name = manifest.name;
    if (!name.startsWith(ADAPTER_PREFIX)) continue;
    for (const dep of Object.keys(allDeps(manifest))) {
      if (dep !== name && dep.startsWith(ADAPTER_PREFIX)) {
        bad.push(`${name}: depends on adapter package \`${dep}\` -- adapters must not depend on each other`);
      }
    }
  }
  return bad;
}

function ruleAdapterScopedDepsAllowlisted(pkgs) {
  const bad = [];
  for (const { manifest } of pkgs) {
    const name = manifest.name;
    if (!name.startsWith(ADAPTER_PREFIX)) continue;
    for (const dep of Object.keys(allDeps(manifest))) {
      if (!dep.startsWith(SCOPE_PREFIX)) continue; // real npm deps are out of scope for this rule
      const allowed = dep === COMPILER_NAME || dep.startsWith(PLATFORM_BINARY_PREFIX);
      if (!allowed) {
        bad.push(
          `${name}: depends on \`${dep}\`, which is neither \`${COMPILER_NAME}\` nor a \`${PLATFORM_BINARY_PREFIX}*\` platform package`
        );
      }
    }
  }
  return bad;
}

function ruleCompilerDoesNotDependOnAdapters(pkgs) {
  const compiler = pkgs.find((pkg) => pkg.manifest.name === COMPILER_NAME);
  if (!compiler) return [`no package named \`${COMPILER_NAME}\` found`];
  const bad = [];
  for (const dep of Object.keys(allDeps(compiler.manifest))) {
    if (dep.startsWith(ADAPTER_PREFIX)) {
      bad.push(`${COMPILER_NAME}: depends on adapter package \`${dep}\` -- the compiler is the shared core beneath the adapters, never the reverse`);
    }
  }
  return bad;
}

const RULES = [
  ["no adapter depends on another adapter", ruleNoAdapterToAdapter],
  ["adapter scoped deps are allowlisted", ruleAdapterScopedDepsAllowlisted],
  ["compiler does not depend on adapters", ruleCompilerDoesNotDependOnAdapters],
];

// --------------------------------------------------------------------------
// Runner.
// --------------------------------------------------------------------------

function run(packagesRoot) {
  const pkgs = loadPackages(packagesRoot);
  if (pkgs.length === 0) {
    console.log(`::error::no packages found under ${packagesRoot}`);
    return 1;
  }

  const names = pkgs.map((pkg) => pkg.manifest.name).sort();
  console.log(`checking ${pkgs.length} package(s): ${names.join(", ")}\n`);

  let failures = 0;
  for (const [label, rule] of RULES) {
    const violations = rule(pkgs);
    if (violations.length > 0) {
      failures += violations.length;
      console.log(`  ${label.padEnd(44)} FAILED`);
      for (const violation of violations) console.log(`      ${violation}`);
    } else {
      console.log(`  ${label.padEnd(44)} ok`);
    }
  }

  console.log();
  if (failures > 0) {
    console.log(`::error::${failures} dependency-rule violation(s).`);
    return 1;
  }
  console.log(`ok: all ${RULES.length} dependency rules hold.`);
  return 0;
}

// --------------------------------------------------------------------------
// Self-test.
//
// Each rule is run against a fixture that violates it, in a throwaway temp
// dir -- never against the real packages/ tree, which is checked separately
// afterwards to prove it is accepted.
// --------------------------------------------------------------------------

function writeFixturePackage(dir, manifest) {
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "package.json"), JSON.stringify(manifest, null, 2));
}

function withTempPackagesDir(fn) {
  const tmp = mkdtempSync(join(tmpdir(), "check-deps-fixture-"));
  try {
    return fn(tmp);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
}

function reportFixture(label, violationsFound) {
  console.log(`  ${label.padEnd(44)} ${violationsFound ? "fails as designed" : "DID NOT FAIL on a broken fixture"}`);
}

function selfTest() {
  console.log("self-test: every rule must be able to fail\n");
  let failures = 0;

  // Fixture 1: an adapter depends directly on another adapter.
  withTempPackagesDir((tmp) => {
    writeFixturePackage(join(tmp, "harness-a"), {
      name: "@fl03/harness-a",
      version: "0.0.0",
      dependencies: { "@fl03/harness-b": "0.0.0" },
    });
    writeFixturePackage(join(tmp, "harness-b"), { name: "@fl03/harness-b", version: "0.0.0" });
    writeFixturePackage(join(tmp, "compiler"), { name: COMPILER_NAME, version: "0.0.0" });
    const violations = ruleNoAdapterToAdapter(loadPackages(tmp));
    reportFixture("no adapter depends on another adapter", violations.length > 0);
    if (violations.length === 0) failures += 1;
  });

  // Fixture 2: an adapter depends on an un-allowlisted @fl03-scoped package.
  withTempPackagesDir((tmp) => {
    writeFixturePackage(join(tmp, "harness-a"), {
      name: "@fl03/harness-a",
      version: "0.0.0",
      dependencies: { "@fl03/some-other-thing": "0.0.0" },
    });
    writeFixturePackage(join(tmp, "compiler"), { name: COMPILER_NAME, version: "0.0.0" });
    const violations = ruleAdapterScopedDepsAllowlisted(loadPackages(tmp));
    reportFixture("adapter scoped deps are allowlisted", violations.length > 0);
    if (violations.length === 0) failures += 1;
  });

  // Fixture 3: the compiler depends back on an adapter (inverted dependency).
  withTempPackagesDir((tmp) => {
    writeFixturePackage(join(tmp, "compiler"), {
      name: COMPILER_NAME,
      version: "0.0.0",
      dependencies: { "@fl03/harness-claude": "0.0.0" },
    });
    const violations = ruleCompilerDoesNotDependOnAdapters(loadPackages(tmp));
    reportFixture("compiler does not depend on adapters", violations.length > 0);
    if (violations.length === 0) failures += 1;
  });

  console.log();
  if (failures > 0) {
    console.log(`::error::${failures} rule(s) cannot detect their own violation.`);
    return 1;
  }
  console.log("ok: every rule is falsifiable.\n");

  console.log("confirming the real packages/ tree is accepted:");
  return run(PACKAGES_DIR);
}

const args = process.argv.slice(2);
if (args.includes("--self-test")) {
  process.exit(selfTest());
} else {
  process.exit(run(PACKAGES_DIR));
}
