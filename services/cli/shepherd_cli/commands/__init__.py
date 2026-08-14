"""Command sub-apps for the shepherd CLI.

Empty on purpose (T3-startup-cost perf sweep, v6.4.5): every command module
is resolved lazily by :class:`shepherd_cli.app._LazyGroup`, which imports
``shepherd_cli.commands.<module>`` directly via ``importlib`` (see that
module's own "LAZY SUBCOMMAND DISPATCH" docstring). Because Python always
executes a package's ``__init__`` before any of its submodules, anything
imported HERE is paid by EVERY CLI invocation regardless of which
subcommand was requested, defeating the point of lazy dispatch. This used
to eagerly ``from shepherd_cli.commands import teammate`` -- issue #198's
only ported surface at the time, predating the v6.4.2 lazy-dispatch
rewrite -- which alone dragged the full Tortoise ORM + Pydantic stack
(~116ms, confirmed via ``python -X importtime``) into every call, whether
or not ``teammate`` was the command being run. Nothing else in the
codebase imports ``shepherd_cli.commands.teammate`` through this package's
namespace (``rg -n "from shepherd_cli.commands import teammate"`` has no
other hits); callers that need a specific submodule import it directly
(``from shepherd_cli.commands.config import ...``, matching every other
submodule-to-submodule reference in this package). Keep this file
import-free.
"""

from __future__ import annotations
