#!/usr/bin/env bash
# Fixture: hooks/tests/fixtures/assertion-hygiene/bare_reference.sh
#
# Deliberately BARE -- one committed example of each banned shape (#318 the
# silent `rg -q` kill, #340 the bash-3.2 `set -e` gap for `[[ ]]`/`(( ))`).
# Never fix these lines; never remove hooks/tests/lint_shell_assertions.sh's
# path-prefix exclusion of this directory.
#
# This file exists to prove two things about the lint, not to be corrected:
#   1. the classifier's core rule flags every one of these four shapes when
#      pointed at this file directly (bypassing the exclusion);
#   2. the fixtures-directory exclusion the lint applies to its OWN
#      production-tree scan is not vacuous -- scanning hooks/** with the
#      exclusion in place contributes ZERO hits from this file. A lint that
#      flags its own fixtures is unshippable, so proving the exclusion does
#      real work (rather than merely existing in source) is part of the
#      contract.
#
# Not meant to run. Purely a text fixture for the classifier.

set -uo pipefail

token="MARKER"
config_count=3

[[ "$config_count" -eq 3 ]]

(( config_count == 3 ))

rg -Fq "$token" "$0"

rg -q "$token" "$0"
