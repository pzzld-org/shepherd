"""Tortoise ORM model mirroring the existing ``styles`` table.

ARCHITECTURE — COEXISTENCE: same contract as :mod:`shepherd_cli.models`.
The SQL migrations under ``skills/context/schema/`` remain the single
schema source of truth for this table — ``styles`` is created wholesale
by ``migrations/0002_styles.sql`` and has never been touched by a later
migration (confirmed by grep: no other ``migrations/*.sql`` file
references ``styles``). This module NEVER calls
``Tortoise.generate_schemas`` and declares only the columns
``shepherd style`` reads or writes — every column in the table happens to
be one of those, so the field list below is the full column set, but
that is a property of this particular table, not a license for other
model modules to assume the same.

Collision check (before adding this file): ``grep -rn 'table = "styles"'
services/cli/shepherd_cli/models*.py`` returned no hits prior to this
module — no existing model mirrors ``styles``, so this is a NEW model,
not a reuse of one that already exists.
"""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class Style(Model):
    """Mirrors the ``styles`` table (``migrations/0002_styles.sql``).

    One row per ``(project_id, language)`` pair — the style guide a
    project has adopted for a given language, copied from the skill's
    bundled ``styles/<language>.md`` source into the project's
    ``<workdir>/styles/<language>.md`` and tracked here so ``shepherd
    style list``/``show`` can report on it without re-scanning the
    filesystem. The ``UNIQUE(project_id, language)`` constraint
    (declared in SQL, not mirrored here as a Tortoise-level constraint —
    see ``commands/style.py``'s raw-SQL ``ON CONFLICT`` upsert, which is
    the actual enforcement point this CLI writes through) is why
    ``style init`` is idempotent: re-running it for a language that
    already has a row updates ``source_path``/``updated_at`` in place
    rather than creating a duplicate.

    Attributes:
        id: A UUIDv7-shaped primary key (this CLI generates one on
            insert; bash generates one via ``_lib.sh``'s
            ``shctx_uuid7``). An ``ON CONFLICT`` upsert on an existing
            row does NOT overwrite ``id`` — the SQL ``DO UPDATE SET``
            clause deliberately omits it, matching
            ``cmd_style.sh``'s ``upsert_row``.
        project_id: FK into ``projects.id``. A plain ``CharField``, not
            a Tortoise ``ForeignKeyField`` — mirrors
            :class:`shepherd_cli.models.Teammate`'s ``project_id``
            convention of leaving cross-table relations to the SQL
            layer rather than modeling them in the ORM.
        language: The style's language key, e.g. ``"python"``,
            ``"rust"`` — matches the bundled
            ``skills/context/styles/<language>.md`` file's basename
            (minus the ``.md`` extension).
        source_path: The absolute path this style guide was copied to
            in the project's work directory (``<workdir>/styles/
            <language>.md``), NOT the bundled skill source path.
        active: ``1``/``0`` flag (INTEGER, not a Tortoise
            ``BooleanField``, so the raw stored value round-trips
            unchanged through ``--json`` output exactly like sqlite3
            would print it — see :mod:`shepherd_cli.commands.mem`'s
            ``pinned`` column for the same convention). ``style init``
            always writes ``1`` on first insert and never changes it on
            a re-init upsert (the ``ON CONFLICT DO UPDATE`` clause omits
            ``active``); this CLI has no subcommand that ever writes
            ``0`` — a currently-inactive row is possible only via
            direct SQL or the bash tool's own (nonexistent, as of this
            port) deactivation path, i.e. ``active`` is effectively
            always ``1`` in practice, but the column is still mirrored
            faithfully rather than assumed constant.
        created_at: Epoch SECONDS when this row was first inserted
            (matches ``_lib.sh``'s ``shctx_now`` == ``date +%s`` — NOT
            the epoch-millisecond unit ``teammates``/``deliverables``
            use). Never updated after insert.
        updated_at: Epoch SECONDS this row was last touched by an
            ``init``/``edit`` upsert.
    """

    id = fields.CharField(max_length=64, pk=True)
    project_id = fields.CharField(max_length=64)
    language = fields.CharField(max_length=64)
    source_path = fields.TextField()
    active = fields.IntField(default=1)
    created_at = fields.BigIntField()
    updated_at = fields.BigIntField()

    class Meta:
        table = "styles"

    def __str__(self) -> str:
        return f"Style(language={self.language!r}, project_id={self.project_id!r})"


__all__ = ["Style"]
