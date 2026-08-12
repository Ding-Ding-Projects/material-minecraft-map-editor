"""The sidecar's real methods, over the core's real modules.

Every entry in :data:`METHODS` calls straight into the same portable core
module a wx surface would call -- :mod:`amulet_map_editor.api.preferences`,
:mod:`amulet_map_editor.api.lang`, :mod:`amulet_map_editor.api.converter`,
:mod:`amulet_map_editor.api.changelog`, :mod:`amulet_map_editor.api.docs_browser`,
:mod:`amulet_map_editor.api.dim_sum_surprise`. Nothing here is a stub: a
method only exists in this table because its implementation exists and is
already exercised by the wx application today.

None of these modules touch a secret. The authenticator and the forge/OAuth
account store both live behind the OS credential vault and are deliberately
left off this table until a lane gives them their own bounded, tested
methods -- the sidecar must never become the first place a secret is
serialized to a pipe.
"""

from __future__ import annotations

import random
import secrets
from dataclasses import asdict
from typing import Any, Callable, Dict

from amulet_map_editor.api import changelog as CHANGELOG
from amulet_map_editor.api import dim_sum_surprise as DIM_SUM
from amulet_map_editor.api import docs_browser as DOCS_BROWSER
from amulet_map_editor.api import lang as LANG
from amulet_map_editor.api import preferences as PREFERENCES
from amulet_map_editor.api.converter import registry as CONVERTER_REGISTRY
from amulet_map_editor.api.sidecar.mesh_methods import MESH_METHODS
from amulet_map_editor.api.sidecar.protocol import ERR_INVALID_PARAMS, ProtocolError
from amulet_map_editor.api.sidecar.world_methods import WORLD_METHODS

MethodHandler = Callable[[Dict[str, Any]], Any]


def _preferences_read(_params: Dict[str, Any]) -> Dict[str, Any]:
    return asdict(PREFERENCES.load())


#: Only fields a caller may ever set through the sidecar. Deliberately a
#: fixed allowlist rather than "every field on the dataclass", so a new
#: preference field is opt-in to remote mutation rather than automatically
#: exposed the day it is added.
_WRITABLE_PREFERENCE_FIELDS = frozenset(
    {
        "display_name",
        "language_mode",
        "funny_level_english",
        "funny_level_cantonese",
        "show_dialog_emojis",
        "theme",
        "density",
        "accent",
        "ui_font",
        "ui_scale",
        "external_editor_path",
        "auto_stage_updates",
    }
)


def _preferences_write(params: Dict[str, Any]) -> Dict[str, Any]:
    unknown = set(params) - _WRITABLE_PREFERENCE_FIELDS
    if unknown:
        raise ProtocolError(
            ERR_INVALID_PARAMS,
            f"Unknown or non-writable preference field(s): {sorted(unknown)}",
        )
    try:
        updated = PREFERENCES.update(**params)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
    return asdict(updated)


def _language_get(_params: Dict[str, Any]) -> Dict[str, Any]:
    return {"language_id": LANG.get_language()}


def _language_set(params: Dict[str, Any]) -> Dict[str, Any]:
    language_id = params.get("language_id")
    if not isinstance(language_id, str) or not language_id:
        raise ProtocolError(
            ERR_INVALID_PARAMS, "'language_id' must be a non-empty string"
        )
    LANG.set_language(language_id)
    return {"language_id": LANG.get_language()}


def _language_list(_params: Dict[str, Any]) -> Dict[str, Any]:
    return {"language_ids": list(LANG.get_languages())}


def _converter_formats(_params: Dict[str, Any]) -> Dict[str, Any]:
    adapters = [
        {
            "id": adapter.id,
            "source_format": adapter.source_format,
            "target_format": adapter.target_format,
            "display_name": adapter.display_name,
            "lossy": adapter.lossy,
            "loss_disclosure": adapter.loss_disclosure,
            "metadata_behaviour": adapter.metadata_behaviour,
        }
        for adapter in CONVERTER_REGISTRY.ADAPTERS
    ]
    return {"adapters": adapters}


def _protocol_ping(_params: Dict[str, Any]) -> Dict[str, Any]:
    """A cheap round-trip check the host can use to prove the sidecar is alive."""
    return {"ok": True}


def _changelog_change_dict(change: "CHANGELOG.ChangelogChange") -> Dict[str, Any]:
    return {
        "action": change.action,
        "summary": change.summary,
        "commit_sha": change.commit_sha,
    }


def _changelog_entry_dict(entry: "CHANGELOG.ChangelogEntry") -> Dict[str, Any]:
    return {
        "version": entry.version,
        "released_on": entry.released_on.isoformat(),
        "commit_sha": entry.commit_sha,
        "changes": [_changelog_change_dict(change) for change in entry.changes],
    }


def _changelog_entries(params: Dict[str, Any]) -> Dict[str, Any]:
    """The real bundled changelog catalog, optionally filtered.

    ``start_date``/``end_date`` are inclusive ISO dates; ``actions`` is a
    list of stable action identifiers; ``text`` is a plain-text substring
    query. The renderer's regex builder, when the caller wants one, runs
    client-side over this same data -- the sidecar only ever returns real
    catalog rows, never a client-supplied compiled pattern.
    """

    catalog = CHANGELOG.load_bundled_catalog()

    start_date = params.get("start_date")
    end_date = params.get("end_date")
    actions = params.get("actions", [])
    text = params.get("text", "")

    from datetime import date as _date

    def _parse(value: Any, field: str) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ProtocolError(ERR_INVALID_PARAMS, f"'{field}' must be an ISO date string")
        try:
            return _date.fromisoformat(value)
        except ValueError:
            raise ProtocolError(ERR_INVALID_PARAMS, f"'{field}' must use the YYYY-MM-DD form")

    if not isinstance(actions, list) or not all(isinstance(item, str) for item in actions):
        raise ProtocolError(ERR_INVALID_PARAMS, "'actions' must be a list of strings")
    if not isinstance(text, str):
        raise ProtocolError(ERR_INVALID_PARAMS, "'text' must be a string")

    try:
        query = CHANGELOG.ChangelogQuery(
            start_date=_parse(start_date, "start_date"),
            end_date=_parse(end_date, "end_date"),
            actions=tuple(actions),
            text=text,
        )
        filtered = CHANGELOG.filter_changelog(catalog, query)
    except CHANGELOG.ChangelogValidationError as exc:
        raise ProtocolError(ERR_INVALID_PARAMS, str(exc))

    return {
        "schema_version": filtered.schema_version,
        "repository_url": filtered.repository_url,
        "source_revision": filtered.source_revision,
        "entries": [_changelog_entry_dict(entry) for entry in filtered.entries],
    }


def _docs_article_dict(article: "DOCS_BROWSER.DocumentationArticle") -> Dict[str, Any]:
    return {
        "slug": article.slug,
        "title": article.title,
        "markdown": article.markdown,
        "source_path": article.source_path,
        "sha256": article.sha256,
        "links": list(article.links),
    }


def _docs_articles(params: Dict[str, Any]) -> Dict[str, Any]:
    """The real bundled documentation articles, or one article by slug."""

    index = DOCS_BROWSER.load_bundled_articles()

    slug = params.get("slug")
    if slug is not None:
        if not isinstance(slug, str):
            raise ProtocolError(ERR_INVALID_PARAMS, "'slug' must be a string")
        try:
            article = index.get(slug)
        except DOCS_BROWSER.DocumentationBundleError as exc:
            raise ProtocolError(ERR_INVALID_PARAMS, str(exc))
        return {"articles": [_docs_article_dict(article)]}

    return {"articles": [_docs_article_dict(article) for article in index.articles]}


def _dimsum_draw(params: Dict[str, Any]) -> Dict[str, Any]:
    """Perform one real draw against the dim-sum surprise's actual 10% rule.

    This calls straight into :mod:`amulet_map_editor.api.dim_sum_surprise` --
    the same ``should_show`` gate and the same public-catalog fetch a wx
    surface uses -- rather than reimplementing the odds or the catalog
    parsing in JavaScript. A caller that wins the draw but finds the public
    catalog unreachable gets an honest ``"unavailable"`` status, never a
    fabricated dish.
    """

    language_mode = params.get("language_mode", "english")
    if language_mode not in DIM_SUM.LANGUAGE_MODES:
        raise ProtocolError(
            ERR_INVALID_PARAMS,
            f"'language_mode' must be one of {sorted(DIM_SUM.LANGUAGE_MODES)}",
        )

    if not DIM_SUM.should_show(random.random()):
        return {"status": "not_drawn"}

    dishes = DIM_SUM.fetch_public_catalog()
    if not dishes:
        return {"status": "unavailable"}

    dish = secrets.choice(dishes)
    payload = DIM_SUM.build_payload(dish, language_mode)
    return {
        "status": payload.status,
        "dish_id": payload.dish_id,
        "title": payload.title,
        "alt_text": payload.alt_text,
        "image_asset_path": payload.image_asset_path,
        "language_mode": payload.language_mode,
        "catalog_url": payload.catalog_url,
        "non_blocking": payload.non_blocking,
        "steal_focus": payload.steal_focus,
        "auto_dismiss_seconds": payload.auto_dismiss_seconds,
    }


#: method name -> handler. The dispatcher (see :mod:`server`) looks a method
#: up here and nowhere else, so an unregistered method name is always a
#: structured "unknown_method" error rather than an ``AttributeError``.
METHODS: Dict[str, MethodHandler] = {
    "protocol.ping": _protocol_ping,
    "preferences.read": _preferences_read,
    "preferences.write": _preferences_write,
    "language.get": _language_get,
    "language.set": _language_set,
    "language.list": _language_list,
    "converter.formats": _converter_formats,
    "changelog.entries": _changelog_entries,
    "docs.articles": _docs_articles,
    "dimsum.draw": _dimsum_draw,
    **WORLD_METHODS,
    **MESH_METHODS,
}
