"""Deterministic Jinja2 render engine for every shepherd template surface.

This module is the ONE template renderer (#244/#243/#181). Before it, the
repo carried five placeholder dialects for the same job: awk ``gsub`` in
``cmd_handoff.sh``, naive ``str.replace`` in ``handoff.py``, bash
interpolation in ``services/eval/eval.sh``, latent ``{curly}`` fill-in in
``commands/spawn.md``, and config-key ``{paths.*}`` braces in doctrine.
Rendering now goes through exactly one ``jinja2.Environment`` with:

- ``StrictUndefined`` — a missing variable is a hard error (exit 4 at the
  CLI seam), the deterministic analogue of ``shctx seed verify``;
- ``trim_blocks`` + ``lstrip_blocks`` + ``keep_trailing_newline`` — the
  whitespace-determinism knobs #244 names, so renders are byte-identical
  for byte-identical inputs;
- a ``tojson`` override serializing with sorted keys and fixed separators,
  so dict ordering can never leak into rendered bytes.

Deterministic lineage: :func:`render_template` returns a
:class:`RenderResult` carrying sha256 digests of the template source, the
canonicalized variable set, and the output. The CLI writes these as a
sidecar manifest next to ``--out`` targets — mirroring the
``cmd_graph.sh`` compile-manifest precedent (``compiled_at`` lives ONLY in
the manifest, never the artifact body; template bodies MUST NOT embed
timestamps).

Template resolution precedence (first hit wins), mirroring the profile
style chain (project overrides user overrides bundled):

1. project ``<workdir>/templates/``
2. user ``~/.shepherd/templates/`` (``SHEPHERD_HOME`` honored)
3. bundled package data ``shepherd_cli/templates/``

This module does no argument parsing — ``commands/render.py`` owns the
CLI seam; other commands (``handoff``, future ``spawn`` boot prompts)
import :func:`render_template` directly.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound
from jinja2.exceptions import UndefinedError

from shepherd_cli.resolution import resolve_user_home, resolve_workdir

#: Bundled template directory (package data), the last-resort search root.
BUNDLED_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")


class TemplateMissingError(Exception):
    """Raised when a template name resolves in no search root."""


class TemplateVarError(Exception):
    """Raised when a template references a variable the context lacks."""


#: Tier labels for :func:`template_search_paths`'s three roots, in order —
#: the same vocabulary :mod:`shepherd_cli.profiles`'s ``SOURCE_PROJECT``/
#: ``SOURCE_USER``/``SOURCE_BUNDLED`` use (string-literal, not imported —
#: self-contained-module convention), so ``shepherd home which``'s two
#: chain renderers (style profile / template) read consistently.
TIER_PROJECT = "project"
TIER_USER = "user"
TIER_BUNDLED = "bundled"


def user_templates_dir() -> str:
    """The user-level templates root: ``~/.shepherd/templates`` (``SHEPHERD_HOME`` honored)."""
    return os.path.join(resolve_user_home(), "templates")


def template_search_paths() -> list[str]:
    """The ordered template search roots (project, user, bundled).

    Returns:
        Existing-or-not directory paths in precedence order. Non-existent
        roots are kept in the list (jinja2's loader skips them safely) so
        callers can display the full precedence chain.
    """
    return [
        os.path.join(resolve_workdir(), "templates"),
        user_templates_dir(),
        BUNDLED_TEMPLATES_DIR,
    ]


def template_search_chain(name: str, *, search_paths: list[str] | None = None) -> list[tuple[str, str, bool]]:
    """Every search root's resolved candidate for one template name, as data.

    Mirrors :func:`render_template`'s own two-step name resolution (the
    bare template name, then that name with ``.j2`` appended) independently
    per root, so ``exists`` here means EXACTLY what :func:`render_template`
    would find at that root — the single source of truth ``shepherd home
    which --template`` renders from (issue #254).

    Args:
        name: The template name to resolve, e.g. ``handoff.md`` or
            ``handoff.md.j2``.
        search_paths: Override the search roots (tests); None uses
            :func:`template_search_paths`.

    Returns:
        ``(tier_label, path, exists)`` for project/user/bundled, in that
        fixed precedence order. ``path`` is the first candidate name that
        exists at that root (bare name, else ``<name>.j2``), or the bare
        name's candidate path when neither exists at that root.
    """
    roots = search_paths if search_paths is not None else template_search_paths()
    labels = (TIER_PROJECT, TIER_USER, TIER_BUNDLED)
    chain: list[tuple[str, str, bool]] = []
    for label, root in zip(labels, roots):
        resolved_path = os.path.join(root, name)
        exists = False
        for candidate_name in (name, f"{name}.j2"):
            candidate_path = os.path.join(root, candidate_name)
            if os.path.isfile(candidate_path):
                resolved_path = candidate_path
                exists = True
                break
        chain.append((label, resolved_path, exists))
    return chain


def _sorted_tojson(value: object) -> str:
    """``tojson`` filter override: sorted keys, fixed separators.

    Args:
        value: Any JSON-serializable value.

    Returns:
        Canonical JSON — dict insertion order can never change the bytes.
    """
    return json.dumps(value, sort_keys=True, separators=(", ", ": "), ensure_ascii=False)


def build_env(search_paths: list[str] | None = None) -> Environment:
    """Construct the canonical deterministic Environment.

    Args:
        search_paths: Override the search roots (tests); None uses
            :func:`template_search_paths`.

    Returns:
        A configured ``jinja2.Environment`` — StrictUndefined,
        whitespace-deterministic, canonical ``tojson``.
    """
    env = Environment(
        loader=FileSystemLoader(search_paths if search_paths is not None else template_search_paths()),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,
    )
    env.filters["tojson"] = _sorted_tojson
    return env


@dataclass(frozen=True, slots=True)
class RenderResult:
    """One deterministic render plus its lineage digests."""

    text: str
    template_name: str
    template_path: str
    template_sha256: str
    vars_sha256: str
    output_sha256: str

    def manifest(self) -> dict[str, str]:
        """The lineage manifest written beside ``--out`` targets.

        Returns:
            A JSON-ready dict of the template identity and digests. No
            timestamp field — callers that want wall-clock provenance add
            it at write time, keeping this dict (and diffs of it) stable
            for identical inputs.
        """
        return {
            "template": self.template_name,
            "template_path": self.template_path,
            "template_sha256": self.template_sha256,
            "vars_sha256": self.vars_sha256,
            "output_sha256": self.output_sha256,
        }


def _canonical_vars_digest(variables: dict[str, object]) -> str:
    """sha256 of the canonicalized (sorted-key JSON) variable set."""
    canonical = json.dumps(variables, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def render_template(
    name: str,
    variables: dict[str, object],
    *,
    search_paths: list[str] | None = None,
) -> RenderResult:
    """Render one template deterministically, with lineage.

    Args:
        name: Template filename relative to a search root, e.g.
            ``handoff.md.j2``. A bare stem is tried with a ``.j2``
            suffix appended (``handoff.md`` -> ``handoff.md.j2``).
        variables: The COMPLETE context. StrictUndefined makes any
            reference outside this dict a :class:`TemplateVarError`.
        search_paths: Override search roots (tests).

    Returns:
        The rendered text plus template/vars/output sha256 digests.

    Raises:
        TemplateMissingError: No search root contains the template.
        TemplateVarError: The template references an undefined variable.
    """
    env = build_env(search_paths)
    template = None
    resolved_name = name
    for candidate in (name, f"{name}.j2"):
        try:
            template = env.get_template(candidate)
            resolved_name = candidate
            break
        except TemplateNotFound:
            continue
    if template is None or template.filename is None:
        roots = ", ".join(search_paths if search_paths is not None else template_search_paths())
        raise TemplateMissingError(f"template not found: {name} (searched: {roots})")

    try:
        text = template.render(**variables)
    except UndefinedError as exc:
        raise TemplateVarError(f"{resolved_name}: {exc.message or exc}") from exc

    with open(template.filename, "rb") as handle:
        template_bytes = handle.read()

    return RenderResult(
        text=text,
        template_name=resolved_name,
        template_path=template.filename,
        template_sha256=hashlib.sha256(template_bytes).hexdigest(),
        vars_sha256=_canonical_vars_digest(variables),
        output_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def list_templates(search_paths: list[str] | None = None) -> list[tuple[str, str]]:
    """Enumerate available templates across the search roots.

    Args:
        search_paths: Override search roots (tests).

    Returns:
        ``(template_name, source_root)`` pairs, first-hit-wins per name
        (a project override shadows the bundled copy), sorted by name.
    """
    roots = search_paths if search_paths is not None else template_search_paths()
    seen: dict[str, str] = {}
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in sorted(filenames):
                if not filename.endswith(".j2"):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, filename), root)
                seen.setdefault(rel, root)
    return sorted(seen.items())


__all__ = [
    "BUNDLED_TEMPLATES_DIR",
    "TIER_BUNDLED",
    "TIER_PROJECT",
    "TIER_USER",
    "RenderResult",
    "TemplateMissingError",
    "TemplateVarError",
    "build_env",
    "list_templates",
    "render_template",
    "template_search_chain",
    "template_search_paths",
    "user_templates_dir",
]
