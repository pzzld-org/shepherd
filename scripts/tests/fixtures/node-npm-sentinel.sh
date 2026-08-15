#!/usr/bin/env bash
# The Claude marketplace carrier must not spawn a system Node/npm bootstrap.
set -euo pipefail

: "${SHEPHERD_NODE_NPM_SENTINEL_LOG:?missing sentinel log path}"
printf '%s\n' "$(basename "$0") $*" >> "$SHEPHERD_NODE_NPM_SENTINEL_LOG"
exit 127
