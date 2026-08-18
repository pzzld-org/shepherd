#!/usr/bin/env bash
# Regression harness pinning scripts/lib/release-package-names.sh's npm-pack
# transform against ground truth, independent of every consumer that sources
# it (verify-release-distribution.sh, verify-release-assets.sh, and
# test-release-distribution-license.sh's own fixture generator). Two
# consumers deriving from the SAME transform will always agree with each
# other even if that transform is wrong — agreement between two things that
# read the same input is not verification. This gate is what actually
# verifies the transform.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

bash "$ROOT/scripts/lib/release-package-names.sh" --self-test
