#!/usr/bin/env node
// Check that the platform packages can cross the workspace boundary without
// carrying workspace-only dependency metadata. The probe deliberately uses
// `npm pack --dry-run`; it computes the publish file list but never writes a
// tarball or installs anything.

import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "../..");
const PACKAGE_ROOT = join(REPO_ROOT, "packages");
const PLATFORM_PACKAGES = ["component-runtime", "harness-claude", "harness-codex", "harness-pi"];
const DEPENDENCY_FIELDS = ["dependencies", "optionalDependencies", "peerDependencies"];

function readManifest(packageDir) {
  const path = join(packageDir, "package.json");
  if (!existsSync(path)) throw new Error(`missing package manifest: ${path}`);
  return JSON.parse(readFileSync(path, "utf8"));
}

function pathExists(packageDir, relativePath) {
  return typeof relativePath === "string" && relativePath !== "" && existsSync(join(packageDir, relativePath));
}

function manifestViolations(manifest, packageDir) {
  const violations = [];
  if (typeof manifest.name !== "string" || !manifest.name.startsWith("@pzzld/")) {
    violations.push("package name must use the @pzzld/ namespace");
  }
  if (!/^\d+\.\d+\.\d+$/.test(manifest.version ?? "")) {
    violations.push("package version must be an exact semver");
  }
  if (manifest.private === true) {
    violations.push("private=true prevents a registry clean install");
  }
  if (!pathExists(packageDir, "README.md")) violations.push("README.md is absent from the package boundary");

  for (const field of DEPENDENCY_FIELDS) {
    for (const [name, version] of Object.entries(manifest[field] ?? {})) {
      if (typeof version !== "string" || /^(workspace:|file:|link:)/.test(version) || version.startsWith("/")) {
        violations.push(`${field}.${name} uses workspace-local reference ${JSON.stringify(version)}`);
      } else if (/^[~^*<>=]|\s/.test(version)) {
        violations.push(`${field}.${name} must pin an exact version, got ${JSON.stringify(version)}`);
      }
    }
  }

  for (const target of Object.values(manifest.exports ?? {})) {
    if (typeof target === "string" && !pathExists(packageDir, target)) {
      violations.push(`exports target is absent: ${target}`);
    }
  }
  if (Object.keys(manifest.bin ?? {}).length > 0) {
    violations.push("adapter packages must not expose a second CLI; use the canonical shepherd binary");
  }
  return violations;
}

function dryPack(packageDir) {
  const result = spawnSync("npm", ["pack", "--dry-run", "--json", "--ignore-scripts"], {
    cwd: packageDir,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  if (result.error) throw new Error(`npm pack --dry-run failed to start: ${result.error.message}`);
  if (result.status !== 0) {
    const details = (result.stderr || result.stdout || "").trim().replace(/\s+/g, " ");
    throw new Error(`npm pack --dry-run failed (${result.status}): ${details}`);
  }
  let payload;
  try {
    payload = JSON.parse(result.stdout);
  } catch (error) {
    throw new Error(`npm pack --dry-run returned invalid JSON: ${error.message}`);
  }
  const packed = payload?.[0];
  if (!packed || !Array.isArray(packed.files)) throw new Error("npm pack --dry-run returned no file list");
  const paths = packed.files.map((file) => file.path);
  const invalid = paths.filter((path) => path.startsWith("/") || path.includes("node_modules") || path === "package-lock.json");
  if (invalid.length > 0) throw new Error(`packlist contains forbidden paths: ${invalid.join(", ")}`);
  for (const required of ["package.json", "README.md"]) {
    if (!paths.includes(required)) throw new Error(`packlist omits ${required}`);
  }
  return { id: packed.id, fileCount: paths.length };
}

function authorityViolations(packageDir) {
  const violations = [];
  const forbidden = /(?:packages\/)?(?:compiler|cli-guard)|@fl03\/(?:compiler|cli-guard)|guard-(?:serve|broker)|materializeCanonical|verifyMaterialized/;
  function walk(dir) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === "node_modules" || entry.name === "runtime") continue;
      const path = join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === "bin" && readdirSync(path).length > 0) violations.push(path);
        else walk(path);
      }
      else if (/\.(?:mjs|js|ts|json|toml)$/.test(entry.name)) {
        const text = readFileSync(path, "utf8");
        if (forbidden.test(text)) violations.push(path);
      }
    }
  }
  walk(packageDir);
  return violations;
}

function assertSelfTest(condition, message) {
  if (!condition) throw new Error(`self-test failed: ${message}`);
}

function selfTest() {
  const realPackage = join(PACKAGE_ROOT, "component-runtime");
  const realManifest = readManifest(realPackage);
  assertSelfTest(
    manifestViolations(realManifest, realPackage).length === 0,
    "a real package passes the publishability metadata boundary",
  );
  const fixtureDir = "/tmp/package-boundary-fixture";
  const clean = {
    name: "@pzzld/fixture",
    version: "6.5.0",
    description: "fixture",
    type: "module",
    dependencies: { "@pzzld/core": "6.5.0" },
  };
  assertSelfTest(manifestViolations(clean, fixtureDir).length === 1, "README absence is detected");
  const privateManifest = { ...clean, private: true };
  assertSelfTest(manifestViolations(privateManifest, fixtureDir).includes("private=true prevents a registry clean install"), "private packages are blocked");
  const workspaceManifest = { ...clean, dependencies: { "@pzzld/core": "workspace:*" } };
  assertSelfTest(manifestViolations(workspaceManifest, fixtureDir).some((item) => item.includes("workspace-local reference")), "workspace references are blocked");
  const secondCli = { ...clean, bin: { other: "bin/other.mjs" } };
  assertSelfTest(manifestViolations(secondCli, fixtureDir).some((item) => item.includes("second CLI")), "secondary package CLIs are blocked");
  const invalidVersion = { ...clean, version: "^6.5.0" };
  assertSelfTest(manifestViolations(invalidVersion, fixtureDir).some((item) => item.includes("exact semver")), "non-exact versions are blocked");
  console.log("ok: package boundary self-test");
}

function main() {
  if (process.argv.includes("--self-test")) return selfTest();
  const failures = [];
  for (const packageName of PLATFORM_PACKAGES) {
    const packageDir = join(PACKAGE_ROOT, packageName);
    let manifest;
    try {
      manifest = readManifest(packageDir);
      const violations = manifestViolations(manifest, packageDir);
      const authority = authorityViolations(packageDir);
      if (authority.length > 0) {
        failures.push(`${manifest.name}: legacy JS authority reference in ${authority.join(", ")}`);
        continue;
      }
      if (violations.length > 0) {
        failures.push(`${manifest.name}: ${violations.join("; ")}`);
        continue;
      }
      const packed = dryPack(packageDir);
      console.log(`PASS ${manifest.name}: ${packed.fileCount} files in ${packed.id} (dry-run)`);
    } catch (error) {
      failures.push(`${packageName}: ${error.message}`);
    }
  }
  if (failures.length > 0) {
    console.error("Package boundary probe FAILED:");
    for (const failure of failures) console.error(`  - ${failure}`);
    process.exitCode = 1;
  } else {
    console.log("Package boundary probe passed: no workspace-only distribution edges found.");
  }
}

main();
