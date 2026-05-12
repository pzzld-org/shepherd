# Geo-block law — production yyz forever

The `node` Fly process group is pinned to `yyz` (Toronto) PERMANENTLY. Region change is FORBIDDEN.

## Why

Polymarket geo-fences US users. Any trade-touching code running from a US Fly region (`dfw`/`iad`/`ord`/`sea`/`lax`) trips detection and bricks the relayer flow. The block is regulatory, not technical — Polymarket cannot serve US users for legal reasons; running from a US region implicates Polymarket in our compliance stance.

## How to apply

- `fly.toml [[vm]] processes=["node"]` carries `region = "yyz"`. NEVER change this.
- The `gateway` process group (formerly `indexer`) lives in `dfw` and is **forbidden from reaching any Polymarket endpoint** — `Cargo.toml`-feature-enforced (no `rspm` / `polymarket-client-sdk` deps in `bin/gateway/`).
- CI grep at `.github/workflows/discipline.yml` rejects PRs that change the yyz pin or that introduce Polymarket deps in gateway.

## Tier classification

- **Tier A (yyz-only, geo-required):** Polymarket Gamma + CLOB + relayer; allocator dispatch; positions/attribution writes; kill-switch.
- **Tier B (yyz-only, realtime-required):** Coinbase WS match feed → HAWKES tick stream. NO relay hop — direct to bot.
- **Tier C (gateway/dfw):** alt-asset candle polling; Chainlink oracle RPC; wallet_watcher Polygon RPC; book snapshots; historical backfills.

Inter-machine transport: Fly 6PN private mesh (`<process>.process.axiom-node.internal`) authenticated by `AXIOM__SECRETS__GATEWAY_TOKEN` shared-secret.

## Audit enforcement

The auditor `dependency-topology` concern at sprint close runs:

```bash
# Reject any rspm or polymarket-client-sdk dep in gateway
rg -n 'rspm|polymarket-client-sdk' bin/gateway/Cargo.toml && exit 1

# Verify yyz pin
rg -n '^region\s*=\s*"yyz"' fly.toml || exit 1
```

If either grep returns the wrong result, the close grade caps at C+ regardless of other work.

## See also

- `three-role-topology.md` — node + worker + gateway, no fold
- `feedback_three_role_topology.md` — operator framing (in user memory)
