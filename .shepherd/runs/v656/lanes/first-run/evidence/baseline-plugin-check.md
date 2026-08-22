HEAD: 6837e109ab618e3d22cb34c637de8ed7b7da7c69
COMMAND: python3 scripts/check-plugin.py
EXIT_CODE: 0
--- STDOUT BEGIN ---
checking the plugin layout contract

  component dirs are at the root               ok
  retired command surface is absent            ok
  hooks json is discoverable                   ok
  hook commands resolve                        ok
  plugin root refs resolve                     ok
  skills are shaped correctly                  ok
  generated skills are thin                    ok
  thin carrier projects canonical content      ok
  codex carrier is regular and canonical       ok
  configured gates resolve                     ok

ok: all 10 plugin contract rules hold.
--- STDOUT END ---
--- STDERR BEGIN ---
--- STDERR END ---
