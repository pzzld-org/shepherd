#!/usr/bin/env node
// packages/scripts/check-deps.mjs -- the npm-side analogue of
// scripts/check-features.sh: enforce the adapter dependency rule.
//
// WHY THIS EXISTS.
//
// Three harness adapters (@pzzld/claude-shepherd, @pzzld/codex-shepherd,
// @pzzld/pi-shepherd) sit over one shared Component Model runtime. That split only holds if no adapter ever
// depends on another adapter -- the moment `harness-codex` names
// `harness-claude` in its `dependencies`, installing the Codex adapter drags
// in Claude's runtime too, and the "thin adapter over one core" property is
// gone with nothing anywhere reporting it. `npm ls` will not catch this: a
// workspace with a stray cross-adapter dependency installs and resolves
// cleanly, because npm has no opinion about which packages may depend on
// which. So the rule is checked here, not just documented in READMEs.
//
// The three rules:
//   1. No `@pzzld/pi-*` package may depend on or import another
//      `@pzzld/pi-*` package, in any dependency field or executable
//      `.js`, `.mjs`, `.cjs`, `.jsx`, `.ts`, `.mts`, `.cts`, or `.tsx` file.
//      Adapter packages declare `type: module`; `.cjs` and `.cts` are rejected
//      explicitly because they would otherwise introduce CommonJS require()
//      semantics outside the ESM ownership scanner.
//   2. A `@pzzld/pi-*` package's `@pzzld/*`-scoped dependencies must be
//      `@pzzld/component-runtime`. A prefix allowlist would let an adapter introduce a
//      second, unreviewed platform dependency while still passing this gate.
//   3. The component runtime must not depend on any `@pzzld/pi-*` package.
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

import { existsSync, mkdtempSync, mkdirSync, readdirSync, readFileSync, realpathSync, rmSync, statSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, extname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "@babel/parser";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..");
const PACKAGES_DIR = join(REPO_ROOT, "packages");

// Adapters are identified by an explicit SET, not a name prefix.
//
// `@pzzld/pi-` only ever worked by accident: the Claude and Codex adapters were
// published as `pi-claude` and `pi-codex`, names that read as "Pi's Claude
// adapter" and describe nothing true. Correcting them to `claude-shepherd` and
// `codex-shepherd` immediately silenced two of these rules, because neither new
// name carries the prefix -- the reverse-edge check protecting the runtime
// stopped seeing two of the three adapters it guards, and said nothing.
//
// A prefix is a guess about identity. This membership is small, closed and
// known, so it is stated.
const ADAPTER_NAMES = new Set([
  "@pzzld/claude-shepherd",
  "@pzzld/codex-shepherd",
  "@pzzld/pi-shepherd",
]);

const isAdapter = (name) => typeof name === "string" && ADAPTER_NAMES.has(name);
const COMPONENT_RUNTIME_NAME = "@pzzld/component-runtime";
const SCOPE_PREFIX = "@pzzld/";

const DEP_FIELDS = ["dependencies", "devDependencies", "peerDependencies", "optionalDependencies"];
// These are every executable JavaScript/TypeScript source extension supported by the adapter
// policy. CommonJS `.cjs`/`.cts` files are collected too so they can be rejected explicitly,
// rather than becoming an unscanned escape hatch.
const EXECUTABLE_SOURCE_EXTENSIONS = new Set([".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx"]);
const COMMONJS_SOURCE_EXTENSIONS = new Set([".cjs", ".cts"]);

// --------------------------------------------------------------------------
// Package loading.
// --------------------------------------------------------------------------

function readPackageJson(pkgDir) {
  const path = join(pkgDir, "package.json");
  if (!existsSync(path)) return null;
  return JSON.parse(readFileSync(path, "utf8"));
}

// Resolve the deepest existing ancestor before appending missing tail segments. That preserves
// ownership checks for an import whose leaf has not been generated yet while still following a
// directory/workspace symlink that would otherwise make a cross-adapter path appear local.
function canonicalPath(path) {
  let candidate = resolve(path);
  const missingSegments = [];
  while (true) {
    try {
      const real = realpathSync.native?.(candidate) ?? realpathSync(candidate);
      return join(real, ...missingSegments.reverse());
    } catch {
      const parent = dirname(candidate);
      if (parent === candidate) return join(candidate, ...missingSegments.reverse());
      missingSegments.push(basename(candidate));
      candidate = parent;
    }
  }
}

function loadPackages(packagesRoot) {
  if (!existsSync(packagesRoot)) return [];
  return readdirSync(packagesRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() || entry.isSymbolicLink())
    .map((entry) => {
      const dir = join(packagesRoot, entry.name);
      return { dir, realDir: canonicalPath(dir), manifest: readPackageJson(dir) };
    })
    .filter((pkg) => pkg.manifest && typeof pkg.manifest.name === "string");
}

function allDependencyEntries(manifest) {
  const entries = [];
  for (const field of DEP_FIELDS) {
    for (const [dependencyName, version] of Object.entries(manifest[field] ?? {})) {
      entries.push({ field, dependencyName, version });
    }
  }
  return entries;
}

function packageNameFromReference(reference) {
  if (typeof reference !== "string" || reference === "") return null;
  if (reference.startsWith("@")) {
    const slash = reference.indexOf("/");
    if (slash === -1) return null;
    const versionAt = reference.indexOf("@", slash + 1);
    return versionAt === -1 ? reference : reference.slice(0, versionAt);
  }
  const versionAt = reference.indexOf("@");
  return versionAt === -1 ? reference : reference.slice(0, versionAt);
}

function localDependencyPath(version) {
  if (typeof version !== "string") return null;
  const prefixes = ["file:", "link:", "workspace:"];
  const prefix = prefixes.find((candidate) => version.startsWith(candidate));
  if (!prefix) return null;
  let target = version.slice(prefix.length);
  if (target.startsWith("file:") || target.startsWith("link:")) target = target.slice(target.indexOf(":") + 1);
  return target.startsWith(".") || target.startsWith("/") ? target : null;
}

function dependencyTargetNames(pkg, dependencyName, version, pkgs) {
  const targets = new Set();
  const add = (name) => {
    if (typeof name === "string" && name !== "") targets.add(name);
  };
  const localPath = localDependencyPath(version);
  if (localPath) {
    const targetPath = canonicalPath(resolve(pkg.dir, localPath));
    const owner = owningPackageForPath(targetPath, pkgs);
    if (owner) add(owner.manifest.name);
    // Keep a scoped declaration as a conservative secondary signal when its local target is
    // missing. Existing local targets are always normalized to their physical owner above.
    if (dependencyName.startsWith(SCOPE_PREFIX)) add(dependencyName);
    return targets;
  }
  if (typeof version === "string" && version.startsWith("npm:")) {
    add(packageNameFromReference(version.slice("npm:".length)));
    return targets;
  }
  if (typeof version === "string" && version.startsWith("workspace:")) {
    const workspaceTarget = version.slice("workspace:".length);
    if (workspaceTarget.startsWith("@") || /^[A-Za-z0-9_-]+@/.test(workspaceTarget)) {
      add(packageNameFromReference(workspaceTarget));
    } else {
      add(dependencyName);
    }
    return targets;
  }
  add(dependencyName);
  return targets;
}

function sourceFiles(dir, visited = new Set()) {
  const realDir = canonicalPath(dir);
  if (visited.has(realDir)) return [];
  visited.add(realDir);
  const files = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "node_modules") continue;
    const path = join(dir, entry.name);
    if (entry.isDirectory()) files.push(...sourceFiles(path, visited));
    else if (entry.isSymbolicLink()) {
      // `Dirent` reports the link itself, not its target. Follow a source file/directory link
      // deliberately, while `visited`'s canonical directory identity prevents cycles. Without
      // this an adapter could put executable imports below a symlinked source root and evade the
      // otherwise realpath-aware ownership scan.
      try {
        const target = statSync(path);
        if (target.isDirectory()) files.push(...sourceFiles(path, visited));
        else if (target.isFile() && EXECUTABLE_SOURCE_EXTENSIONS.has(extname(path))) files.push(path);
      } catch {
        // A dangling or racing link has no readable executable source. Any import that points to
        // it is still handled conservatively by canonicalPath's existing-ancestor ownership rule.
      }
    }
    else if (EXECUTABLE_SOURCE_EXTENSIONS.has(extname(entry.name))) files.push(path);
  }
  return files;
}

// --------------------------------------------------------------------------
// Syntax-tree module-specifier scanner.
//
// Babel's maintained parser owns JavaScript, TypeScript, JSX, and TSX grammar. Hand-written
// token heuristics cannot distinguish every regex/division boundary or TypeScript import form.
// Parse errors fail the boundary closed instead of silently producing an empty import set.
// --------------------------------------------------------------------------

function parserPluginsFor(extension) {
  const plugins = [];
  if (extension === ".ts" || extension === ".mts" || extension === ".tsx") plugins.push("typescript");
  if (extension === ".jsx" || extension === ".tsx") plugins.push("jsx");
  return plugins;
}

function literalModuleSpecifier(node) {
  if (node?.type === "StringLiteral") return node.value;
  if (node?.type === "TemplateLiteral" && node.expressions.length === 0 && node.quasis.length === 1) {
    return node.quasis[0].value.cooked ?? node.quasis[0].value.raw;
  }
  return null;
}

function parseModuleSpecifiers(source, path) {
  const extension = extname(path);
  const ast = parse(source, {
    sourceType: "module",
    sourceFilename: path,
    allowAwaitOutsideFunction: true,
    createImportExpressions: true,
    errorRecovery: false,
    plugins: parserPluginsFor(extension),
  });
  const specifiers = [];
  const visited = new Set();
  const stack = [ast.program];

  while (stack.length > 0) {
    const node = stack.pop();
    if (!node || typeof node !== "object" || visited.has(node)) continue;
    visited.add(node);

    let specifier = null;
    if (node.type === "ImportDeclaration" || node.type === "ExportNamedDeclaration" || node.type === "ExportAllDeclaration") {
      specifier = literalModuleSpecifier(node.source);
    } else if (node.type === "ImportExpression") {
      specifier = literalModuleSpecifier(node.source);
    } else if (node.type === "CallExpression" && node.callee?.type === "Import") {
      specifier = literalModuleSpecifier(node.arguments?.[0]);
    } else if (node.type === "TSImportEqualsDeclaration" && node.moduleReference?.type === "TSExternalModuleReference") {
      specifier = literalModuleSpecifier(node.moduleReference.expression);
    } else if (node.type === "TSImportType") {
      specifier = literalModuleSpecifier(node.argument);
    }
    if (specifier !== null) specifiers.push(specifier);

    for (const value of Object.values(node)) {
      if (Array.isArray(value)) {
        for (const child of value) stack.push(child);
      } else if (value && typeof value === "object") {
        stack.push(value);
      }
    }
  }

  return specifiers;
}
function packageNameFromBareSpecifier(specifier) {
  if (specifier.startsWith(".") || specifier.startsWith("/") || specifier.startsWith("#") || specifier.includes(":")) return null;
  const segments = specifier.split("/");
  if (specifier.startsWith("@")) return segments.length >= 2 ? `${segments[0]}/${segments[1]}` : null;
  return segments[0] || null;
}

function isInsidePackage(path, packageDir) {
  const fromPackage = relative(packageDir, path);
  return fromPackage === "" || (!fromPackage.startsWith("..") && !isAbsolute(fromPackage));
}

function owningPackageForPath(path, pkgs) {
  // A symlinked package root can physically live beneath another package directory. Pick the
  // deepest matching physical root instead of the first directory returned by readdir(), or the
  // outer adapter would incorrectly claim ownership of the nested target.
  return pkgs
    .filter((pkg) => isInsidePackage(path, pkg.realDir ?? pkg.dir))
    .sort((left, right) => (right.realDir ?? right.dir).length - (left.realDir ?? left.dir).length)[0];
}

function adapterImportViolation({ pkgs, manifest, path, specifier }) {
  const barePackage = packageNameFromBareSpecifier(specifier);
  if (isAdapter(barePackage) && barePackage !== manifest.name) {
    return `${manifest.name}: imports adapter package \`${barePackage}\` via \`${specifier}\` from \`${path}\` -- adapters must not import each other`;
  }
  if (!specifier.startsWith(".") && !specifier.startsWith("/")) return null;
  const resolved = canonicalPath(resolve(dirname(path), specifier.split(/[?#]/, 1)[0]));
  const owner = owningPackageForPath(resolved, pkgs);
  if (isAdapter(owner?.manifest.name) && owner.manifest.name !== manifest.name) {
    return `${manifest.name}: imports adapter path \`${specifier}\` from \`${path}\` (resolved to \`${owner.manifest.name}\`) -- adapters must not import each other`;
  }
  return null;
}

// --------------------------------------------------------------------------
// The rules. Each takes the loaded package list and returns a list of
// human-readable violations.
// --------------------------------------------------------------------------

function ruleNoAdapterToAdapter(pkgs) {
  const bad = [];
  for (const pkg of pkgs) {
    const { manifest } = pkg;
    const name = manifest.name;
    if (!isAdapter(name)) continue;
    for (const { field, dependencyName, version } of allDependencyEntries(manifest)) {
      for (const target of dependencyTargetNames(pkg, dependencyName, version, pkgs)) {
        if (target !== name && isAdapter(target)) {
          bad.push(`${name}: ${field} depends on adapter package \`${target}\` via \`${dependencyName}\` -- adapters must not depend on each other`);
        }
      }
    }
  }
  return bad;
}

function ruleNoAdapterToAdapterImports(pkgs) {
  const bad = [];
  for (const { dir, manifest } of pkgs) {
    if (!isAdapter(manifest.name)) continue;
    if (manifest.type !== "module") {
      bad.push(`${manifest.name}: package.json must declare \"type\": \"module\" so adapter .js source cannot silently become CommonJS`);
    }
    for (const path of sourceFiles(dir)) {
      const extension = extname(path);
      if (COMMONJS_SOURCE_EXTENSIONS.has(extension)) {
        bad.push(
          `${manifest.name}: contains CommonJS source \`${path}\` (${extension}) -- adapter .cjs/.cts source is prohibited so require() cannot bypass the ESM adapter boundary`
        );
        continue;
      }
      const source = readFileSync(path, "utf8");
      let specifiers;
      try {
        specifiers = parseModuleSpecifiers(source, path);
      } catch (error) {
        bad.push(`${manifest.name}: executable source \`${path}\` could not be parsed: ${error.message ?? error}`);
        continue;
      }
      for (const specifier of specifiers) {
        const violation = adapterImportViolation({ pkgs, manifest, path, specifier });
        if (violation) bad.push(violation);
      }
    }
  }
  return bad;
}

function ruleAdapterScopedDepsAllowlisted(pkgs) {
  const bad = [];
  for (const pkg of pkgs) {
    const { manifest } = pkg;
    const name = manifest.name;
    if (!isAdapter(name)) continue;
    for (const { field, dependencyName, version } of allDependencyEntries(manifest)) {
      for (const target of dependencyTargetNames(pkg, dependencyName, version, pkgs)) {
        if (!target.startsWith(SCOPE_PREFIX)) continue; // real npm deps are out of scope for this rule
        const allowed = target === COMPONENT_RUNTIME_NAME;
        if (!allowed) {
          bad.push(
            `${name}: ${field} depends on \`${target}\` via \`${dependencyName}\`, which is not the allowlisted Component Model runtime \`${COMPONENT_RUNTIME_NAME}\``
          );
        }
      }
    }
  }
  return bad;
}

function ruleComponentRuntimeDoesNotDependOnAdapters(pkgs) {
  const compiler = pkgs.find((pkg) => pkg.manifest.name === COMPONENT_RUNTIME_NAME);
  if (!compiler) return [`no package named \`${COMPONENT_RUNTIME_NAME}\` found`];
  const bad = [];
  for (const { field, dependencyName, version } of allDependencyEntries(compiler.manifest)) {
    for (const target of dependencyTargetNames(compiler, dependencyName, version, pkgs)) {
      if (isAdapter(target)) {
        bad.push(`${COMPONENT_RUNTIME_NAME}: ${field} depends on adapter package \`${target}\` via \`${dependencyName}\` -- the runtime is the shared core beneath the adapters, never the reverse`);
      }
    }
  }
  return bad;
}

const RULES = [
  ["no adapter depends on another adapter", ruleNoAdapterToAdapter],
  ["no adapter imports another adapter", ruleNoAdapterToAdapterImports],
  ["adapter scoped deps are allowlisted", ruleAdapterScopedDepsAllowlisted],
  ["component runtime does not depend on adapters", ruleComponentRuntimeDoesNotDependOnAdapters],
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
      name: "@pzzld/claude-shepherd",
      version: "0.0.0",
      dependencies: { "@pzzld/codex-shepherd": "0.0.0" },
    });
    writeFixturePackage(join(tmp, "harness-b"), { name: "@pzzld/codex-shepherd", version: "0.0.0" });
    writeFixturePackage(join(tmp, "component-runtime"), { name: COMPONENT_RUNTIME_NAME, version: "0.0.0" });
    const violations = ruleNoAdapterToAdapter(loadPackages(tmp));
    reportFixture("no adapter depends on another adapter", violations.length > 0);
    if (violations.length === 0) failures += 1;
  });

  // Fixture 2: source imports must be resolved from a real syntax tree and by package ownership.
  // forbidden cases cover bare/relative ESM, re-export, dynamic imports after division at top
  // level and inside template interpolation, .jsx/.mts/.tsx, symlinked relative and package-root
  // targets, and explicitly banned CommonJS extensions. The comment, ordinary string, raw template literal,
  // regex, JSX text, member method, shadowed ESM `require`, and same-adapter helper are control
  // cases: they are not imports and must not be reported.
  withTempPackagesDir((tmp) => {
    const harnessA = join(tmp, "harness-a");
    writeFixturePackage(harnessA, { name: "@pzzld/claude-shepherd", version: "0.0.0", type: "module" });
    writeFileSync(join(harnessA, "index.mjs"), 'import "@pzzld/codex-shepherd";\nimport "../harness-b/src/guard.mjs";\n');
    writeFileSync(join(harnessA, "cross.jsx"), 'import "@pzzld/codex-shepherd/guard-jsx";\n');
    writeFileSync(join(harnessA, "cross.mts"), 'import "../harness-b/src/guard.mts";\n');
    writeFileSync(join(harnessA, "cross.tsx"), 'import "@pzzld/codex-shepherd/guard";\n');
    writeFileSync(join(harnessA, "re-export.mjs"), 'export { guard } from "@pzzld/codex-shepherd";\n');
    writeFileSync(join(harnessA, "dynamic.ts"), 'await import("../harness-b/src/dynamic.mts");\n');
    writeFileSync(join(harnessA, "dynamic-template-specifier.mjs"), 'await import(`@pzzld/codex-shepherd`);\n');
    writeFileSync(join(harnessA, "division-dynamic.mjs"), 'const ratio = 1 / import("@pzzld/codex-shepherd");\n');
    writeFileSync(join(harnessA, "postfix-division-dynamic.mjs"), 'let value = 1; const ratio = value++ / import("@pzzld/codex-shepherd");\n');
    writeFileSync(join(harnessA, "template-dynamic.mjs"), 'const ratio = `${1 / import("@pzzld/codex-shepherd")}`;\n');
    writeFileSync(join(harnessA, "type-import-equals.ts"), 'import Guard = require("@pzzld/codex-shepherd");\nvoid Guard;\n');
    writeFileSync(join(harnessA, "parse-error.mjs"), 'import { from "@pzzld/codex-shepherd";\n');
    writeFileSync(join(harnessA, "common.cjs"), 'require("@pzzld/codex-shepherd");\n');
    writeFileSync(join(harnessA, "common.cts"), 'require("@pzzld/codex-shepherd");\n');
    writeFileSync(
      join(harnessA, "non-imports.mjs"),
      '// import "@pzzld/codex-shepherd";\nconst ordinary = "import \\"@pzzld/codex-shepherd\\"";\nconst template = `import "@pzzld/codex-shepherd"`;\nconst matcher = /import "@fl03\\/harness-b"/;\nif (ready) /import\\("@fl03\\/harness-b"\\)/.test(source);\nif (ready) {} /import\\("@fl03\\/harness-b"\\)/.test(source);\nconst member = { import() {} }; member.import("@pzzld/codex-shepherd");\nconst require = () => {}; require("@pzzld/codex-shepherd");\n'
    );
    writeFileSync(join(harnessA, "jsx-text.jsx"), 'const view = <div>import("@pzzld/codex-shepherd")</div>;\n');
    writeFileSync(join(harnessA, "same-adapter.mjs"), 'import "./harness-helper.mjs";\n');
    writeFileSync(join(harnessA, "harness-helper.mjs"), 'export const helper = true;\n');
    const harnessB = join(tmp, "harness-b");
    writeFixturePackage(harnessB, { name: "@pzzld/codex-shepherd", version: "0.0.0", type: "module" });
    mkdirSync(join(harnessB, "src"), { recursive: true });
    writeFileSync(join(harnessB, "src", "guard.mjs"), "export const guard = true;\n");
    symlinkSync("../harness-b", join(harnessA, "linked-harness-b"), "dir");
    writeFileSync(join(harnessA, "symlinked-relative.mjs"), 'import "./linked-harness-b/src/guard.mjs";\n');
    const externalSource = join(tmp, "external-source");
    mkdirSync(externalSource);
    writeFileSync(join(externalSource, "symlinked-source.mjs"), 'import "@pzzld/codex-shepherd";\n');
    symlinkSync("../external-source", join(harnessA, "linked-source"), "dir");
    const linkedWorkspaceTarget = join(harnessA, "linked-workspace-target");
    writeFixturePackage(linkedWorkspaceTarget, { name: "@pzzld/pi-shepherd", version: "0.0.0", type: "module" });
    mkdirSync(join(linkedWorkspaceTarget, "src"), { recursive: true });
    writeFileSync(join(linkedWorkspaceTarget, "src", "guard.mjs"), "export const guard = true;\n");
    symlinkSync("harness-a/linked-workspace-target", join(tmp, "harness-c-root"), "dir");
    writeFileSync(join(harnessA, "symlinked-package-root.mjs"), 'import "./linked-workspace-target/src/guard.mjs";\n');
    writeFixturePackage(join(tmp, "component-runtime"), { name: COMPONENT_RUNTIME_NAME, version: "0.0.0" });
    const violations = ruleNoAdapterToAdapterImports(loadPackages(tmp));
    const catchesEveryForbiddenEdge = [
      "imports adapter package `@pzzld/codex-shepherd` via `@pzzld/codex-shepherd`",
      "imports adapter path `../harness-b/src/guard.mjs`",
      "imports adapter package `@pzzld/codex-shepherd` via `@pzzld/codex-shepherd/guard-jsx`",
      "imports adapter path `../harness-b/src/guard.mts`",
      "imports adapter package `@pzzld/codex-shepherd` via `@pzzld/codex-shepherd/guard`",
      "re-export.mjs",
      "imports adapter path `../harness-b/src/dynamic.mts`",
      "dynamic-template-specifier.mjs",
      "division-dynamic.mjs",
      "postfix-division-dynamic.mjs",
      "template-dynamic.mjs",
      "type-import-equals.ts",
      "parse-error.mjs",
      "symlinked-relative.mjs",
      "symlinked-package-root.mjs",
      "linked-source/symlinked-source.mjs",
      "common.cjs",
      "common.cts",
    ].every((needle) => violations.some((violation) => violation.includes(needle)));
    const acceptsEveryControl = !violations.some((violation) =>
      violation.includes("non-imports.mjs") || violation.includes("jsx-text.jsx") || violation.includes("same-adapter.mjs")
    );
    const passes = violations.length === 18 && catchesEveryForbiddenEdge && acceptsEveryControl;
    reportFixture("AST adapter import boundary", passes);
    if (!passes) failures += 1;
  });

  // Fixture 3: adapters must declare ESM package semantics so their executable source policy is
  // not changed by Node's default CommonJS interpretation.
  withTempPackagesDir((tmp) => {
    const harnessA = join(tmp, "harness-a");
    writeFixturePackage(harnessA, { name: "@pzzld/claude-shepherd", version: "0.0.0" });
    writeFixturePackage(join(tmp, "component-runtime"), { name: COMPONENT_RUNTIME_NAME, version: "0.0.0" });
    const violations = ruleNoAdapterToAdapterImports(loadPackages(tmp));
    reportFixture("adapter packages declare type=module", violations.length === 1);
    if (violations.length !== 1) failures += 1;
  });

  // Fixture 4: an adapter depends on an un-allowlisted @fl03-scoped package.
  withTempPackagesDir((tmp) => {
    writeFixturePackage(join(tmp, "harness-a"), {
      name: "@pzzld/claude-shepherd",
      version: "0.0.0",
      dependencies: { "@pzzld/cli-unreviewed": "0.0.0" },
    });
    writeFixturePackage(join(tmp, "component-runtime"), { name: COMPONENT_RUNTIME_NAME, version: "0.0.0" });
    const violations = ruleAdapterScopedDepsAllowlisted(loadPackages(tmp));
    reportFixture("adapter scoped deps are allowlisted", violations.length > 0);
    if (violations.length === 0) failures += 1;
  });

  // Fixture 5: the component runtime depends back on an adapter (inverted dependency).
  withTempPackagesDir((tmp) => {
    writeFixturePackage(join(tmp, "component-runtime"), {
      name: COMPONENT_RUNTIME_NAME,
      version: "0.0.0",
      dependencies: { "@pzzld/claude-shepherd": "0.0.0" },
    });
    const violations = ruleComponentRuntimeDoesNotDependOnAdapters(loadPackages(tmp));
    reportFixture("component runtime does not depend on adapters", violations.length > 0);
    if (violations.length === 0) failures += 1;
  });

  // Fixture 6: npm aliases and local/workspace dependency values must resolve to the actual
  // workspace owner, not merely trust an arbitrary dependency key.
  withTempPackagesDir((tmp) => {
    writeFixturePackage(join(tmp, "harness-a"), {
      name: "@pzzld/claude-shepherd",
      version: "0.0.0",
      dependencies: {
        "adapter-npm-alias": "npm:@pzzld/codex-shepherd@0.0.0",
        "adapter-file-alias": "file:../harness-b",
        "adapter-workspace-alias": "workspace:../harness-b",
      },
    });
    writeFixturePackage(join(tmp, "harness-b"), { name: "@pzzld/codex-shepherd", version: "0.0.0" });
    writeFixturePackage(join(tmp, "component-runtime"), { name: COMPONENT_RUNTIME_NAME, version: "0.0.0" });
    const violations = ruleNoAdapterToAdapter(loadPackages(tmp));
    const passes = violations.length === 3 && violations.every((violation) => violation.includes("@pzzld/codex-shepherd"));
    reportFixture("adapter aliases resolve to adapter owners", passes);
    if (!passes) failures += 1;
  });

  // Fixture 7: aliases must not hide an unreviewed @fl03 package from the adapter allowlist.
  withTempPackagesDir((tmp) => {
    writeFixturePackage(join(tmp, "harness-a"), {
      name: "@pzzld/claude-shepherd",
      version: "0.0.0",
      dependencies: {
        "platform-npm-alias": "npm:@pzzld/cli-unreviewed@0.0.0",
        "platform-file-alias": "file:../cli-unreviewed",
      },
    });
    writeFixturePackage(join(tmp, "cli-unreviewed"), { name: "@pzzld/cli-unreviewed", version: "0.0.0" });
    writeFixturePackage(join(tmp, "component-runtime"), { name: COMPONENT_RUNTIME_NAME, version: "0.0.0" });
    const violations = ruleAdapterScopedDepsAllowlisted(loadPackages(tmp));
    const passes = violations.length === 2 && violations.every((violation) => violation.includes("@pzzld/cli-unreviewed"));
    reportFixture("adapter aliases preserve the @fl03 allowlist", passes);
    if (!passes) failures += 1;
  });

  // Fixture 8: the component runtime's reverse-edge prohibition also applies to aliases.
  withTempPackagesDir((tmp) => {
    writeFixturePackage(join(tmp, "component-runtime"), {
      name: COMPONENT_RUNTIME_NAME,
      version: "0.0.0",
      dependencies: { "adapter-alias": "npm:@pzzld/claude-shepherd@0.0.0" },
    });
    writeFixturePackage(join(tmp, "harness-claude"), { name: "@pzzld/claude-shepherd", version: "0.0.0" });
    const violations = ruleComponentRuntimeDoesNotDependOnAdapters(loadPackages(tmp));
    const passes = violations.length === 1 && violations[0].includes("@pzzld/claude-shepherd");
    reportFixture("component runtime aliases preserve reverse-edge rule", passes);
    if (!passes) failures += 1;
  });

  // Fixture 9: each dependency field is an independent contract. A repeated key in a later
  // field must not overwrite and hide a forbidden production edge from an earlier field.
  withTempPackagesDir((tmp) => {
    writeFixturePackage(join(tmp, "harness-a"), {
      name: "@pzzld/claude-shepherd",
      version: "0.0.0",
      dependencies: { alias: "npm:@pzzld/codex-shepherd@0.0.0" },
      devDependencies: { alias: "npm:@pzzld/component-runtime@0.0.0" },
    });
    writeFixturePackage(join(tmp, "harness-b"), { name: "@pzzld/codex-shepherd", version: "0.0.0" });
    writeFixturePackage(join(tmp, "component-runtime"), { name: COMPONENT_RUNTIME_NAME, version: "0.0.0" });
    const pkgs = loadPackages(tmp);
    const adapterViolations = ruleNoAdapterToAdapter(pkgs);
    const passes = adapterViolations.length === 1 && adapterViolations[0].includes("dependencies") && adapterViolations[0].includes("@pzzld/codex-shepherd");
    reportFixture("dependency fields cannot mask each other", passes);
    if (!passes) failures += 1;
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
