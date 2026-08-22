#!/usr/bin/env node
/**
 * Deterministic release-trust policy over committed manifests and measurements.
 *
 * Registry-backed tools discover findings. This gate does not contact a registry:
 * it verifies the committed measurement has one truthful classification per
 * finding, derives npm production closure from package-lock.json, and rejects
 * every reachable shipped high/critical without a complete future-dated waiver.
 */

import { mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { extname, join, relative, resolve } from "node:path";

const SHIPPED_NPM_ROOTS = new Map([
  ["packages/component-runtime", "@pzzld/component-runtime"],
  ["packages/harness-claude", "@pzzld/claude-shepherd"],
  ["packages/harness-codex", "@pzzld/codex-shepherd"],
  ["packages/harness-pi", "@pzzld/pi-shepherd"],
]);
const REQUIRED_ECOSYSTEMS = new Set(["github-actions", "npm", "cargo"]);
const GATED_SEVERITIES = new Set(["high", "critical"]);
const TEXT_EXTENSIONS = new Set([".json", ".md", ".mjs", ".py", ".sh", ".toml", ".yaml", ".yml"]);
const SCAN_EXCLUDED_DIRECTORIES = new Set([".git", ".pi", ".shepherd", "node_modules", "target"]);
const URL_HISTORY_PATHS = new Set(["CHANGELOG.md", "scripts/tests/test-dependency-policy.py"]);
const URL_HISTORY_PREFIXES = [".shepherd/", "conformance/"]; 
const CURRENT_FL03_PATTERNS = [
  /https?:\/\/github\.com\/fl03\/shepherd\b/gi,
  /https?:\/\/raw\.githubusercontent\.com\/fl03\/shepherd\b/gi,
];
const ALLOWED_SHARED_SETTINGS = new Set(["enabledPlugins", "extraKnownMarketplaces"]);
const REQUIRED_SECURITY_HEADINGS = [
  "## Supported versions",
  "## Private reporting",
  "## Response process",
  "## Coordinated disclosure",
  "## Scope",
  "## Safe harbor",
];

function parseArguments(arguments_) {
  let root = process.cwd();
  let asOf = new Date().toISOString().slice(0, 10);
  let fixtureDir = null;
  let evidenceDir = null;
  for (let index = 0; index < arguments_.length; index += 1) {
    const argument = arguments_[index];
    const take = (name) => {
      index += 1;
      if (index >= arguments_.length) throw new Error(`${name} requires a path`);
      return arguments_[index];
    };
    if (argument === "--root") root = take("--root");
    else if (argument.startsWith("--root=")) root = argument.slice(7);
    else if (argument === "--as-of") asOf = take("--as-of");
    else if (argument.startsWith("--as-of=")) asOf = argument.slice(8);
    else if (argument === "--fixture-dir") fixtureDir = take("--fixture-dir");
    else if (argument.startsWith("--fixture-dir=")) fixtureDir = argument.slice(14);
    else if (argument === "--evidence-dir") evidenceDir = take("--evidence-dir");
    else if (argument.startsWith("--evidence-dir=")) evidenceDir = argument.slice(15);
    else throw new Error(`unknown argument: ${argument}`);
  }
  requireDate(asOf, "--as-of");
  return {
    root: resolve(root),
    asOf,
    fixtureDir: fixtureDir === null ? null : resolve(fixtureDir),
    evidenceDir: evidenceDir === null ? null : resolve(evidenceDir),
  };
}

function requireDate(value, label) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new Error(`${label} must be an exact YYYY-MM-DD date`);
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value) {
    throw new Error(`${label} must be a real calendar date`);
  }
}

function readText(root, path) {
  return readFileSync(join(root, path), "utf8");
}

function readJson(root, path, errors) {
  try {
    return JSON.parse(readText(root, path));
  } catch (error) {
    errors.push(`${path}: cannot read valid JSON: ${error.message}`);
    return null;
  }
}

function dependencyNames(manifest) {
  return [
    ...Object.keys(manifest?.dependencies ?? {}),
    ...Object.keys(manifest?.optionalDependencies ?? {}),
    ...Object.keys(manifest?.peerDependencies ?? {}),
  ];
}

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stable(value[key])]));
  }
  return value;
}

function same(left, right) {
  return JSON.stringify(stable(left)) === JSON.stringify(stable(right));
}

function parseReport(text, label) {
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`${label} did not emit valid JSON: ${error.message}`);
  }
}

function runTool(root, command, arguments_, accepted, label) {
  const result = spawnSync(command, arguments_, { cwd: root, encoding: "utf8" });
  if (result.error) throw new Error(`${label} tool failure: ${result.error.message}`);
  if (!accepted.has(result.status)) {
    throw new Error(`${label} tool failure (exit ${result.status}): ${(result.stderr || result.stdout).trim()}`);
  }
  return result;
}

function collectMeasurements(options) {
  let npmText;
  let cargoText;
  let metadataText;
  let denyText = "fixture: full cargo deny not executed\n";
  if (options.fixtureDir !== null) {
    npmText = readFileSync(join(options.fixtureDir, "npm-audit.json"), "utf8");
    cargoText = readFileSync(join(options.fixtureDir, "cargo-advisories.json"), "utf8");
    metadataText = readFileSync(join(options.fixtureDir, "cargo-metadata.json"), "utf8");
  } else {
    const npm = runTool(options.root, "npm", ["audit", "--json"], new Set([0, 1]), "npm audit");
    npmText = npm.stdout;
    const npmReport = parseReport(npmText, "npm audit");
    if (npmReport?.error !== undefined || npmReport?.vulnerabilities === undefined) {
      throw new Error(`npm audit tool failure: ${JSON.stringify(npmReport?.error ?? "missing vulnerabilities")}`);
    }
    const deny = runTool(
      options.root,
      "cargo",
      ["deny", "--workspace", "--all-features", "check"],
      new Set([0]),
      "cargo deny",
    );
    denyText = `${deny.stdout}${deny.stderr}`;
    const cargo = runTool(
      options.root,
      "cargo",
      ["deny", "--format", "json", "--workspace", "--all-features", "check", "advisories", "--audit-compatible-output"],
      new Set([0, 1]),
      "cargo deny advisories",
    );
    cargoText = cargo.stdout;
    const metadata = runTool(
      options.root,
      "cargo",
      ["metadata", "--format-version", "1", "--locked", "--all-features"],
      new Set([0]),
      "cargo metadata",
    );
    metadataText = metadata.stdout;
  }
  const npm = parseReport(npmText, "npm audit");
  if (npm?.error !== undefined || npm?.vulnerabilities === undefined) {
    throw new Error(`npm audit tool failure: ${JSON.stringify(npm?.error ?? "missing vulnerabilities")}`);
  }
  const cargo = parseReport(cargoText, "cargo deny advisories");
  const metadata = parseReport(metadataText, "cargo metadata");
  if (options.evidenceDir !== null) {
    mkdirSync(options.evidenceDir, { recursive: true });
    writeFileSync(join(options.evidenceDir, "npm-audit.json"), `${JSON.stringify(npm, null, 2)}\n`);
    writeFileSync(join(options.evidenceDir, "cargo-advisories.json"), `${JSON.stringify(cargo, null, 2)}\n`);
    writeFileSync(join(options.evidenceDir, "cargo-deny-check.txt"), denyText.endsWith("\n") ? denyText : `${denyText}\n`);
    const summary = {
      schema: 1,
      sha256: createHash("sha256").update(metadataText).digest("hex"),
      packageCount: Array.isArray(metadata.packages) ? metadata.packages.length : 0,
      workspaceMemberCount: Array.isArray(metadata.workspace_members) ? metadata.workspace_members.length : 0,
    };
    writeFileSync(join(options.evidenceDir, "cargo-metadata-summary.json"), `${JSON.stringify(summary, null, 2)}\n`);
  }
  return { npm, cargo, metadata };
}

function resolveLockPath(packages, parentPath, dependency) {
  const candidates = [];
  let current = parentPath;
  while (true) {
    candidates.push(current ? `${current}/node_modules/${dependency}` : `node_modules/${dependency}`);
    const marker = current.lastIndexOf("/node_modules/");
    if (marker === -1) break;
    current = current.slice(0, marker);
  }
  candidates.push(`node_modules/${dependency}`);
  return candidates.find((candidate) => Object.hasOwn(packages, candidate)) ?? null;
}

function npmClosure(lock, errors) {
  const packages = lock?.packages;
  if (packages === null || typeof packages !== "object" || Array.isArray(packages)) {
    errors.push("package-lock.json: packages object is required");
    return new Map();
  }
  const roots = [];
  for (const [path, expectedName] of SHIPPED_NPM_ROOTS) {
    const entry = packages[path];
    if (entry?.name !== expectedName) {
      errors.push(`package-lock.json: shipped root ${path} must be ${expectedName}`);
      continue;
    }
    roots.push([path, expectedName]);
  }
  const reached = new Map();
  const queue = roots.map(([path, artifact]) => ({ path, artifact, chain: [path] }));
  const seen = new Set();
  while (queue.length > 0) {
    const item = queue.shift();
    const seenKey = `${item.artifact}\0${item.path}`;
    if (seen.has(seenKey)) continue;
    seen.add(seenKey);
    const prior = reached.get(item.path) ?? { artifacts: new Set(), paths: [] };
    prior.artifacts.add(item.artifact);
    prior.paths.push(item.chain);
    reached.set(item.path, prior);
    const entry = packages[item.path];
    if (entry?.link === true && typeof entry.resolved === "string" && Object.hasOwn(packages, entry.resolved)) {
      queue.push({ path: entry.resolved, artifact: item.artifact, chain: item.chain });
      continue;
    }
    for (const dependency of dependencyNames(entry)) {
      const child = resolveLockPath(packages, item.path, dependency);
      if (child !== null) queue.push({ path: child, artifact: item.artifact, chain: [...item.chain, child] });
    }
  }
  return reached;
}

function cargoClosure(metadata, errors) {
  const packages = new Map((metadata?.packages ?? []).map((item) => [item.id, item]));
  const nodes = new Map((metadata?.resolve?.nodes ?? []).map((item) => [item.id, item]));
  const reached = new Map();
  const queue = (metadata?.workspace_members ?? []).map((id) => ({ id, root: id, chain: [id] }));
  const seen = new Set();
  while (queue.length > 0) {
    const item = queue.shift();
    const key = `${item.root}\0${item.id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const root = packages.get(item.root);
    if (root === undefined) {
      errors.push(`${item.root}: workspace member missing from cargo metadata packages`);
      continue;
    }
    const artifacts = root.name === "shepherd-cli"
      ? ["crates.io:shepherd-cli", "github-release:shepherd"]
      : root.publish === false || Array.isArray(root.publish) && root.publish.length === 0
        ? []
        : [`crates.io:${root.name}`];
    const prior = reached.get(item.id) ?? { artifacts: new Set(), paths: [] };
    for (const artifact of artifacts) prior.artifacts.add(artifact);
    prior.paths.push(item.chain);
    reached.set(item.id, prior);
    for (const dependency of nodes.get(item.id)?.deps ?? []) {
      const kinds = dependency.dep_kinds ?? [];
      if (kinds.length === 0 || kinds.some((kind) => kind.kind !== "dev")) {
        queue.push({ id: dependency.pkg, root: item.root, chain: [...item.chain, dependency.pkg] });
      }
    }
  }
  return { reached, packages };
}

function npmFindings(report, lock, errors) {
  const findings = [];
  for (const [name, vulnerability] of Object.entries(report?.vulnerabilities ?? {})) {
    for (const node of vulnerability.nodes ?? []) {
      const version = lock?.packages?.[node]?.version;
      if (typeof version !== "string") errors.push(`${node}: npm audit node missing exact package-lock version`);
      const advisories = (vulnerability.via ?? []).map((value) => {
        if (typeof value === "string") return `package:${value}`;
        const match = typeof value?.url === "string" ? value.url.match(/\/advisories\/([^/]+)$/) : null;
        return match === null ? `source:${value?.source}` : match[1];
      }).sort();
      let fix = { status: "none" };
      if (vulnerability.fixAvailable && typeof vulnerability.fixAvailable === "object") {
        fix = {
          status: vulnerability.fixAvailable.isSemVerMajor ? "semver-major" : "available",
          package: vulnerability.fixAvailable.name,
          version: vulnerability.fixAvailable.version,
        };
      }
      findings.push({
        id: `npm:${name}:${node}`,
        ecosystem: "npm",
        package: name,
        version,
        node,
        severity: vulnerability.severity,
        affected: vulnerability.range,
        advisories,
        fix,
      });
    }
  }
  return findings;
}

function cargoFindings(report) {
  return (report?.vulnerabilities ?? []).map((value) => {
    const source = value.package.source;
    const packageId = `${source}#${value.package.name}@${value.package.version}`;
    const patched = [...(value.versions?.patched ?? [])].sort();
    const unaffected = [...(value.versions?.unaffected ?? [])].sort();
    return {
      id: `cargo:${value.advisory.id}:${packageId}`,
      ecosystem: "cargo",
      package: value.package.name,
      version: value.package.version,
      packageId,
      advisory: value.advisory.id,
      advisoryKind: "vulnerability",
      cvss: value.advisory.cvss,
      affected: { patched, unaffected },
      fix: patched.length === 0 ? { status: "none" } : { status: "available", versions: patched },
    };
  });
}

function bestPath(paths) {
  return [...paths].sort((left, right) => left.length - right.length || JSON.stringify(left).localeCompare(JSON.stringify(right)))[0] ?? [];
}

function validatePolicy(manifest, lock, measurements, asOf, errors) {
  const policy = manifest?.shepherdReleaseTrust;
  if (policy === null || typeof policy !== "object" || Array.isArray(policy)) {
    errors.push("package.json: shepherdReleaseTrust policy object is required");
    return { findings: 0, reachable: 0, waivers: 0, npmProduction: 0, cargoProduction: 0 };
  }
  if (policy.schema !== 2) errors.push("package.json: shepherdReleaseTrust.schema must be 2");
  try { requireDate(policy.measuredOn, "package.json: shepherdReleaseTrust.measuredOn"); } catch (error) { errors.push(error.message); }
  const requiredSources = {
    npm: "npm audit --json",
    cargoDeny: "cargo deny --workspace --all-features check",
    cargoAdvisories: "cargo deny --format json --workspace --all-features check advisories --audit-compatible-output",
    cargoMetadata: "cargo metadata --format-version 1 --locked --all-features",
  };
  for (const [key, command] of Object.entries(requiredSources)) {
    if (policy.sources?.[key] !== command) errors.push(`package.json: shepherdReleaseTrust.sources.${key} must equal ${command}`);
  }
  const measured = [
    ...cargoFindings(measurements.cargo),
    ...npmFindings(measurements.npm, lock, errors),
  ].sort((left, right) => left.id.localeCompare(right.id));
  const observed = Array.isArray(policy.observedFindings) ? [...policy.observedFindings].sort((a, b) => String(a.id).localeCompare(String(b.id))) : [];
  if (!same(observed, measured)) {
    const observedIds = new Set(observed.map((item) => item.id));
    const measuredIds = new Set(measured.map((item) => item.id));
    const detail = [
      ...measured.filter((item) => !observedIds.has(item.id)).map((item) => `missing ${item.id}`),
      ...observed.filter((item) => !measuredIds.has(item.id)).map((item) => `fabricated ${item.id}`),
      ...measured.filter((item) => observedIds.has(item.id) && !same(item, observed.find((candidate) => candidate.id === item.id))).map((item) => `mismatch ${item.id}`),
    ];
    errors.push(`package.json: observedFindings must equal exact measured findings (${detail.join("; ")})`);
  }
  const npm = npmClosure(lock, errors);
  const cargo = cargoClosure(measurements.metadata, errors);
  const classifications = Array.isArray(policy.classifications) ? policy.classifications : [];
  const byId = new Map();
  for (const classification of classifications) {
    if (byId.has(classification.id)) errors.push(`${classification.id}: duplicate classification id`);
    else byId.set(classification.id, classification);
  }
  for (const finding of measured.filter((item) => item.ecosystem === "cargo")) {
    if (!cargo.packages.has(finding.packageId)) {
      errors.push(`${finding.package}@${finding.version}: exact package ID ${finding.packageId} missing from cargo metadata`);
    }
  }
  for (const classification of classifications) {
    if (!measured.some((item) => item.id === classification.id)) errors.push(`${classification.id}: classification has no exact measured finding`);
  }
  let reachable = 0;
  let waivers = 0;
  let npmProduction = 0;
  let cargoProduction = 0;
  for (const finding of measured) {
    const classification = byId.get(finding.id);
    if (classification === undefined) {
      errors.push(`${finding.id}: exact measured finding has no classification`);
      continue;
    }
    let derived;
    if (finding.ecosystem === "npm") {
      const reach = npm.get(finding.node);
      derived = {
        productionClosure: reach !== undefined,
        dependencyPath: reach === undefined ? [] : bestPath(reach.paths),
        shippedArtifacts: reach === undefined ? [] : [...reach.artifacts].sort(),
      };
    } else {
      if (!cargo.packages.has(finding.packageId)) {
        errors.push(`${finding.package}@${finding.version}: exact package ID ${finding.packageId} missing from cargo metadata`);
      }
      const reach = cargo.reached.get(finding.packageId);
      derived = {
        productionClosure: reach !== undefined && reach.artifacts.size > 0,
        dependencyPath: reach === undefined || reach.artifacts.size === 0 ? [] : bestPath(reach.paths.filter((path) => {
          const root = cargo.packages.get(path[0]);
          return root?.name === "shepherd-cli" || !(root?.publish === false || Array.isArray(root?.publish) && root.publish.length === 0);
        })),
        shippedArtifacts: reach === undefined ? [] : [...reach.artifacts].sort(),
      };
    }
    for (const key of ["productionClosure", "dependencyPath", "shippedArtifacts"]) {
      if (!same(classification[key], derived[key])) {
        errors.push(`${finding.id}: ${key} disagrees with derived ${key} ${JSON.stringify(derived[key])}`);
      }
    }
    if (derived.productionClosure) {
      if (finding.ecosystem === "npm") npmProduction += 1; else cargoProduction += 1;
    }
    if (typeof classification.reachable !== "boolean") errors.push(`${finding.id}: reachable must be boolean`);
    if (typeof classification.rationale !== "string" || classification.rationale.length < 20) errors.push(`${finding.id}: rationale is incomplete`);
    if (!derived.productionClosure && classification.reachable) errors.push(`${finding.id}: finding outside production closure cannot be reachable`);
    const gated = derived.productionClosure && classification.reachable
      && (finding.ecosystem === "cargo" || GATED_SEVERITIES.has(finding.severity));
    if (!gated) {
      if (!["not-shipped", "not-reachable"].includes(classification.disposition)) {
        errors.push(`${finding.id}: non-gated finding disposition must be not-shipped or not-reachable`);
      }
      if (classification.waiver !== undefined) errors.push(`${finding.id}: non-gated finding must not carry a waiver`);
      continue;
    }
    reachable += 1;
    const waiver = classification.waiver;
    let complete = classification.disposition === "waived" && waiver !== null && typeof waiver === "object"
      && typeof waiver.owner === "string" && waiver.owner.startsWith("@")
      && typeof waiver.reason === "string" && waiver.reason.length >= 30
      && typeof waiver.tracking === "string" && /^https:\/\/github\.com\/pzzld-org\/shepherd\/issues\/\d+$/.test(waiver.tracking);
    try { requireDate(waiver?.expires, `${finding.id}: waiver.expires`); } catch { complete = false; }
    if (!complete) errors.push(`${finding.id}: reachable shipped high/critical requires a complete unexpired waiver`);
    else if (waiver.expires <= asOf) errors.push(`${finding.id}: waiver expired on ${waiver.expires} (gate date ${asOf})`);
    else waivers += 1;
  }
  return { findings: measured.length, reachable, waivers, npmProduction, cargoProduction };
}

function validateDependabot(root, errors) {
  let text;
  try {
    text = readText(root, ".github/dependabot.yml");
  } catch (error) {
    errors.push(`.github/dependabot.yml: ${error.message}`);
    return;
  }
  const entries = new Map();
  let current = null;
  for (const line of text.split("\n")) {
    const ecosystem = line.match(/^\s*-\s+package-ecosystem:\s*([A-Za-z0-9_-]+)\s*$/);
    if (ecosystem !== null) {
      current = ecosystem[1];
      entries.set(current, { directory: false, monthly: false });
      continue;
    }
    if (current === null) continue;
    if (/^\s+directory:\s*\/\s*$/.test(line)) entries.get(current).directory = true;
    if (/^\s+interval:\s*monthly\s*$/.test(line)) entries.get(current).monthly = true;
  }
  for (const ecosystem of REQUIRED_ECOSYSTEMS) {
    const entry = entries.get(ecosystem);
    if (entry === undefined) {
      errors.push(`.github/dependabot.yml: dependabot is missing ${ecosystem} coverage`);
    } else if (!entry.directory || !entry.monthly) {
      errors.push(`.github/dependabot.yml: ${ecosystem} must update directory / monthly`);
    }
  }
}

function validateSettings(root, errors) {
  const settings = readJson(root, ".claude/settings.json", errors);
  if (settings === null || typeof settings !== "object" || Array.isArray(settings)) return;
  for (const key of Object.keys(settings)) {
    if (!ALLOWED_SHARED_SETTINGS.has(key)) {
      errors.push(`.claude/settings.json: shared project settings must not contain personal/unsafe key ${key}`);
    }
  }
  const permissions = settings.permissions;
  if (permissions?.defaultMode === "bypassPermissions") {
    errors.push(".claude/settings.json: bypassPermissions is prohibited in shared settings");
  }
  for (const permission of permissions?.allow ?? []) {
    if (permission === "Bash(*)") errors.push(".claude/settings.json: unrestricted Bash(*) is prohibited");
  }
  for (const key of ["skipDangerousModePermissionPrompt", "skipAutoPermissionPrompt"]) {
    if (settings[key] === true) errors.push(`.claude/settings.json: ${key} prompt suppression is prohibited`);
  }
  if (settings.enabledPlugins?.["shepherd@shepherd"] !== true) {
    errors.push(".claude/settings.json: project dogfood posture must enable only shepherd@shepherd explicitly");
  }
  if (settings.extraKnownMarketplaces?.shepherd?.source?.repo !== "pzzld-org/shepherd") {
    errors.push(".claude/settings.json: shepherd marketplace must resolve pzzld-org/shepherd");
  }
}

function validateSecurity(root, errors) {
  let security;
  try {
    security = readText(root, "SECURITY.md");
  } catch (error) {
    errors.push(`SECURITY.md: ${error.message}`);
    return;
  }
  for (const heading of REQUIRED_SECURITY_HEADINGS) {
    if (!security.includes(heading)) errors.push(`SECURITY.md: missing ${heading}`);
  }
  if (!/ordinary correctness and compatibility/i.test(security)) {
    errors.push("SECURITY.md: must distinguish vulnerabilities from ordinary correctness and compatibility defects");
  }
}

function fallbackFiles(root, directory = root, found = []) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    if (entry.isDirectory() && !SCAN_EXCLUDED_DIRECTORIES.has(entry.name)) {
      fallbackFiles(root, join(directory, entry.name), found);
    } else if (entry.isFile()) {
      found.push(relative(root, join(directory, entry.name)));
    }
  }
  return found;
}

function sourceFiles(root) {
  const result = spawnSync("git", ["-C", root, "ls-files", "-z"], { encoding: "buffer", stdio: ["ignore", "pipe", "ignore"] });
  if (result.status === 0) return result.stdout.toString("utf8").split("\0").filter(Boolean).sort();
  return fallbackFiles(root).sort();
}

function validateCurrentUrls(root, errors) {
  for (const path of sourceFiles(root)) {
    if (
      URL_HISTORY_PATHS.has(path)
      || URL_HISTORY_PREFIXES.some((prefix) => path.startsWith(prefix))
      || !TEXT_EXTENSIONS.has(extname(path))
    ) continue;
    const absolute = join(root, path);
    try {
      if (!statSync(absolute).isFile()) continue;
      const text = readFileSync(absolute, "utf8");
      for (const pattern of CURRENT_FL03_PATTERNS) {
        pattern.lastIndex = 0;
        const match = pattern.exec(text);
        if (match !== null) {
          const line = text.slice(0, match.index).split("\n").length;
          errors.push(`${path}:${line}: current FL03 URL/install surface must use pzzld-org`);
          break;
        }
      }
    } catch (error) {
      errors.push(`${path}: cannot inspect current URL inventory: ${error.message}`);
    }
  }
}

function validateInventory(root, errors) {
  const inventory = readJson(root, "scripts/release-trust-surfaces.json", errors);
  if (inventory === null) return;
  if (inventory.schema !== 1 || !Array.isArray(inventory.activeSurfaces)) {
    errors.push("scripts/release-trust-surfaces.json: schema 1 activeSurfaces are required");
    return;
  }
  for (const entry of inventory.preservedContributorIdentity ?? []) {
    try {
      if (!readText(root, entry.path).includes(entry.requiredText)) {
        errors.push(`${entry.path}: preserved contributor identity ${entry.requiredText} is missing`);
      }
    } catch (error) {
      errors.push(`${entry.path}: cannot verify preserved contributor identity: ${error.message}`);
    }
  }
}

function workflowStep(job, name) {
  const start = job.findIndex((line) => line === `      - name: ${name}`);
  if (start === -1) return [];
  const relativeEnd = job.slice(start + 1).findIndex((line) => /^      - name: /.test(line));
  return job.slice(start, relativeEnd === -1 ? job.length : start + 1 + relativeEnd);
}

function stepField(step, key) {
  const prefix = `        ${key}:`;
  const line = step.find((candidate) => candidate.startsWith(prefix));
  return line === undefined ? null : line.slice(prefix.length).trim();
}

function validateReleaseWorkflow(root, errors) {
  let workflow;
  try {
    workflow = readText(root, ".github/workflows/release.yml");
  } catch (error) {
    errors.push(`.github/workflows/release.yml: ${error.message}`);
    return;
  }
  const lines = workflow.split("\n");
  const jobStart = lines.findIndex((line) => /^  release-metadata:\s*$/.test(line));
  const relativeEnd = jobStart === -1 ? -1 : lines.slice(jobStart + 1).findIndex((line) => /^  [A-Za-z0-9_-]+:\s*$/.test(line));
  const jobEnd = relativeEnd === -1 ? lines.length : jobStart + 1 + relativeEnd;
  const job = jobStart === -1 ? [] : lines.slice(jobStart, jobEnd);
  const condition = "steps.detect.outputs.proceed == 'true'";
  const requirements = [
    ["Verify version authority", 'python3 scripts/version-bump.py check --root . --version "${{ steps.detect.outputs.current }}"'],
    ["Verify dependency policy mutations", "python3 scripts/tests/test-dependency-policy.py"],
    ["Verify live dependency trust", "node scripts/check-deps.mjs"],
  ];
  for (const [name, command] of requirements) {
    const step = workflowStep(job, name);
    if (stepField(step, "run") !== command || stepField(step, "if") !== condition) {
      errors.push(`.github/workflows/release.yml: release-metadata ${name} must be an enabled single-line run step executing ${command}`);
    }
  }
  const install = workflowStep(job, "Setup cargo-deny");
  const installIndex = job.indexOf("      - name: Setup cargo-deny");
  const liveIndex = job.indexOf("      - name: Verify live dependency trust");
  if (stepField(install, "uses") !== "taiki-e/install-action@v2"
      || stepField(install, "if") !== condition
      || !install.includes("          tool: cargo-deny")
      || installIndex === -1 || liveIndex === -1 || installIndex >= liveIndex) {
    errors.push(".github/workflows/release.yml: release-metadata must conditionally install cargo-deny with taiki-e/install-action@v2 before live dependency trust");
  }
}

function main() {
  let options;
  try {
    options = parseArguments(process.argv.slice(2));
  } catch (error) {
    console.error(`release-trust: ERROR: ${error.message}`);
    return 2;
  }
  let measurements;
  try {
    measurements = collectMeasurements(options);
  } catch (error) {
    console.error(`release-trust: ERROR: ${error.message}`);
    return 2;
  }
  const errors = [];
  const manifest = readJson(options.root, "package.json", errors);
  const lock = readJson(options.root, "package-lock.json", errors);
  const metrics = manifest === null || lock === null
    ? { findings: 0, reachable: 0, waivers: 0, npmProduction: 0, cargoProduction: 0 }
    : validatePolicy(manifest, lock, measurements, options.asOf, errors);
  validateDependabot(options.root, errors);
  validateSettings(options.root, errors);
  validateSecurity(options.root, errors);
  validateInventory(options.root, errors);
  validateCurrentUrls(options.root, errors);
  validateReleaseWorkflow(options.root, errors);
  if (errors.length > 0) {
    for (const error of errors) console.error(`release-trust: ERROR: ${error}`);
    console.error(`release-trust: FAILED violations=${errors.length}`);
    return 1;
  }
  console.log(
    `release-trust: OK ecosystems=${REQUIRED_ECOSYSTEMS.size} findings=${metrics.findings} `
      + `npm-production-findings=${metrics.npmProduction} cargo-production-findings=${metrics.cargoProduction} `
      + `reachable-high-critical=${metrics.reachable} waivers=${metrics.waivers} `
      + "current-fl03-urls=0 unsafe-settings=0",
  );
  return 0;
}

process.exitCode = main();
