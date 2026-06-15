# Geo-block law — production node pinned to one region

> Example project doctrine. It shows the *shape* of a project-specific law: a hard
> architectural rule with a stated reason and **mechanical** enforcement (CI grep +
> auditor concern). Swap the region, dependency names, and endpoints for your own.

The `node` Fly process group is pinned to `yyz` (Toronto) PERMANENTLY. Region change
is FORBIDDEN.

## Why

A regulated upstream API geo-restricts certain regions. Any code that touches that
API while running from a restricted region trips detection and bricks the request
flow. The block is regulatory, not technical — running from a restricted region
implicates the service in a compliance violation, so the constraint is encoded as a
hard doctrine rather than left to convention.

## How to apply

- `fly.toml [[vm]] processes=["node"]` carries `region = "yyz"`. NEVER change this.
- The `gateway` process group lives in `dfw` and is **forbidden from reaching the
  regulated endpoint** — `Cargo.toml`-feature-enforced (no `regulated-api-sdk` dep in
  `bin/gateway/`).
- CI grep at `.github/workflows/discipline.yml` rejects PRs that change the `yyz` pin
  or introduce the regulated dependency in `gateway`.

## Tier classification

- **Tier A (yyz-only, geo-required):** all calls to the regulated upstream API; the
  dispatch path that consumes them; kill-switch.
- **Tier B (yyz-only, realtime-required):** the low-latency market feed → tick stream.
  No relay hop — direct to the consumer.
- **Tier C (gateway/dfw):** unrestricted polling; external oracle RPC; book snapshots;
  historical backfills.

Inter-machine transport: Fly 6PN private mesh (`<process>.process.service-node.internal`)
authenticated by the `SERVICE__SECRETS__GATEWAY_TOKEN` shared-secret.

## Audit enforcement

The auditor `dependency-topology` concern at sprint close runs:

```bash
# Reject the regulated SDK in the gateway binary
rg -n 'regulated-api-sdk' bin/gateway/Cargo.toml && exit 1

# Verify the yyz pin
rg -n '^region\s*=\s*"yyz"' fly.toml || exit 1
```

If either grep returns the wrong result, the close grade caps at C+ regardless of
other work.

## See also

- `three-role-topology.md` — node + worker + gateway, no fold
