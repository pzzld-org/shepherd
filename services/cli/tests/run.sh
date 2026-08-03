#!/usr/bin/env bash
# shepherd CLI gate suite (v6.4.2).
#
# The suite is subprocess-per-test by contract (#198: every test drives the
# real CLI as a fresh interpreter, never by importing shepherd_cli into the
# pytest process). That makes each test cost one full interpreter start, and
# at 1348 tests a serial run takes ~22 minutes -- far outside CLAUDE.md's
# gate-test budget, and long enough that the pre-commit hook stops being run.
#
# The tests are perfectly parallel (every one of them is isolated by tmp_path
# plus a fully explicit environment: SHCTX_DB, CLAUDE_PLUGIN_ROOT,
# SHEPHERD_SESSION_ID, cwd), so xdist splits them across cores with no shared
# state to contend over. Default is `auto` (one worker per core); override
# with SHEPHERD_TEST_JOBS when the box is already loaded -- a shepherd wave
# fanning out agents on the same machine should cap this rather than let the
# gate compete with the lanes for memory (#256).
#
#   ./tests/run.sh                      # -n auto
#   SHEPHERD_TEST_JOBS=2 ./tests/run.sh # cap to 2 workers
#   SHEPHERD_TEST_JOBS=0 ./tests/run.sh # serial (no xdist), for debugging
#
# Extra pytest args pass straight through: ./tests/run.sh tests/test_run.py -x
set -euo pipefail
cd "$(dirname "$0")/.."

jobs="${SHEPHERD_TEST_JOBS:-auto}"
if [[ "$jobs" == "0" ]]; then
  exec .venv/bin/python -m pytest -q "$@"
fi
exec .venv/bin/python -m pytest -q -n "$jobs" "$@"
