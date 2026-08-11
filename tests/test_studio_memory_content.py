"""The Memory Console's thirteen views and its feature-article reader.

The console is one of the two surfaces the spec renderer cannot express, so its
content is a data module of its own rather than a spec.  That makes it easy to
add a view and easy to add one that goes nowhere, which is what most of this
file is about: a rail entry with no page, a card row that looks pressable and
targets nothing, an article whose path names a file that does not exist.

The last group of checks is about what must *not* reach a visible string.  It is
written as a set of patterns rather than a list of forbidden words on purpose:
this repository is public, so a denylist would publish the exact private terms
it exists to keep out.  What it looks for instead is the damage those leaks
actually do -- a machine name, a private address, somebody's home directory, an
unfinished placeholder, or a Python repr that escaped into the interface.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from amulet_map_editor.api.studio import memory_content as memory
from amulet_map_editor.api.studio import surfaces
from amulet_map_editor.api.studio.search import SearchState

ROOT = Path(__file__).resolve().parents[1]

#: The rail, in the order the design draws it.
EXPECTED_VIEWS = (
    "overview",
    "sync",
    "skills",
    "memory",
    "docs",
    "history",
    "changelog",
    "operations",
    "security",
    "twoFactor",
    "locks",
    "statusHub",
    "settings",
)

#: Patterns no visible string may contain.  Each one names a real leak rather
#: than a style preference.
FORBIDDEN_PATTERNS = {
    "a private network address": r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b",
    "somebody's home directory": r"(?:[A-Za-z]:[\\/]Users[\\/]|/home/[a-z])",
    "a remote shell target": r"\b\w+@\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
    "an unfinished placeholder": r"\b(?:TODO|TBD|FIXME|lorem ipsum|coming soon)\b",
    "a Python repr": r"object at 0x|<built-in|NotImplemented|<class '",
    "an unresolved format field": r"\{[a-z_]+\}(?![\w`])",
}


def _visible_strings():
    """Yield ``(where, text)`` for every string the console can show."""
    for view in memory.MEMORY_VIEWS:
        for name, text in (
            ("label", view.label),
            ("glyph", view.glyph),
            ("title", view.title),
            ("subtitle", view.subtitle),
        ):
            yield f"view {view.key}.{name}", text
        for index, card in enumerate(view.cards):
            where = f"view {view.key} card {index}"
            for name, text in (
                ("title", card.title),
                ("stat", card.stat),
                ("body", card.body),
                ("code", card.code),
            ):
                yield f"{where}.{name}", text
            for row in card.rows:
                for name, text in (
                    ("name", row.name),
                    ("detail", row.detail),
                    ("tag", row.tag),
                    ("note", row.note),
                ):
                    yield f"{where} row {row.name}.{name}", text
    for article in memory.ARTICLES:
        for name, text in (
            ("title", article.title),
            ("summary", article.summary),
            ("body", article.body),
        ):
            yield f"article {article.path}.{name}", text


# ---------------------------------------------------------------------------
# the rail
# ---------------------------------------------------------------------------
def test_the_rail_carries_the_thirteen_documented_views():
    assert memory.VIEW_KEYS == EXPECTED_VIEWS
    assert len(memory.MEMORY_VIEWS) == 13
    assert set(memory.VIEWS_BY_KEY) == set(EXPECTED_VIEWS)


def test_every_view_names_itself_and_shows_something():
    problems = []
    for view in memory.MEMORY_VIEWS:
        if not view.label.strip():
            problems.append(f"{view.key}: no rail label")
        if not view.glyph.strip():
            problems.append(f"{view.key}: no rail glyph")
        if not view.title.strip():
            problems.append(f"{view.key}: no page title")
        if not view.subtitle.strip():
            problems.append(f"{view.key}: no page subtitle")
        if not view.cards:
            problems.append(f"{view.key}: no cards")
    assert not problems, problems


def test_no_card_is_empty_below_its_own_heading():
    problems = [
        f"{view.key}/{card.title}"
        for view in memory.MEMORY_VIEWS
        for card in view.cards
        if not (card.stat or card.body or card.rows or card.code)
    ]
    assert not problems, f"these cards show only a heading: {problems}"


def test_every_card_fits_the_grid_it_is_laid_out_on():
    problems = [
        f"{view.key}/{card.title}: span {card.span}"
        for view in memory.MEMORY_VIEWS
        for card in view.cards
        if not 1 <= card.span <= memory.GRID_COLUMNS
    ]
    assert not problems, problems


def test_every_row_that_looks_pressable_goes_somewhere_real():
    """A row styled as a control and wired to nothing is worse than plain text."""
    problems = []
    for view in memory.MEMORY_VIEWS:
        for card in view.cards:
            for row in card.rows:
                target = row.target
                if not target:
                    if not (row.detail or row.tag or row.note):
                        problems.append(
                            f"{view.key}/{card.title}/{row.name}: no target and "
                            "nothing to read"
                        )
                    continue
                kind, _, value = target.partition(":")
                if kind == "view":
                    if value not in memory.VIEWS_BY_KEY:
                        problems.append(f"{row.name}: view {value!r} does not exist")
                elif kind == "article":
                    if value not in memory.ARTICLES_BY_PATH:
                        problems.append(f"{row.name}: article {value!r} does not exist")
                elif kind == "surface":
                    if surfaces.surface(value) is None:
                        problems.append(f"{row.name}: surface {value!r} is not indexed")
                else:
                    problems.append(f"{row.name}: unknown target kind {target!r}")
    assert not problems, problems


def test_an_unknown_view_key_is_answered_with_nothing():
    assert memory.view("no-such-view") is None
    assert memory.view("") is None


# ---------------------------------------------------------------------------
# the article reader
# ---------------------------------------------------------------------------
def test_every_article_has_a_path_a_domain_a_summary_and_a_body():
    problems = []
    for article in memory.ARTICLES:
        if not article.title.strip():
            problems.append(f"{article.path}: no title")
        if not article.path.strip():
            problems.append(f"{article.title}: no path")
        if article.domain not in memory.DOMAINS:
            problems.append(f"{article.path}: domain {article.domain!r} is not a filter")
        if not article.summary.strip():
            problems.append(f"{article.path}: no summary")
        if len(article.body.strip()) < 200:
            problems.append(f"{article.path}: the body is a stub")
        if not article.paragraphs():
            problems.append(f"{article.path}: the body has no paragraphs")
    assert not problems, problems


def test_the_reader_holds_more_than_a_token_article():
    assert len(memory.ARTICLES) >= 18
    assert len(memory.ARTICLES_BY_PATH) == len(memory.ARTICLES)


def test_every_article_path_names_a_file_that_actually_exists():
    """The path is shown to the reader and copied into an external editor."""
    missing = [
        article.path
        for article in memory.ARTICLES
        if not (ROOT / article.path).is_file()
    ]
    assert not missing, f"these articles point at files that are not there: {missing}"


def test_every_domain_filter_has_at_least_one_article_behind_it():
    counts = memory.domain_counts()
    assert set(counts) == set(memory.DOMAINS)
    empty = [domain for domain, count in counts.items() if count == 0]
    assert not empty, f"these filters would show nothing: {empty}"


def test_searching_the_articles_is_plain_text_first_and_regex_on_request():
    literal = memory.search_articles(SearchState(query="nbt.*editor"))
    assert literal == ()
    pattern = memory.search_articles(SearchState(query="nbt.*editor", regex=True))
    assert pattern
    assert all(isinstance(item, memory.Article) for item in pattern)


def test_searching_the_views_and_cards_narrows_rather_than_empties():
    everything = memory.search_views(SearchState())
    assert len(everything) == 13
    narrowed = memory.search_views(SearchState(query="changelog"))
    assert 0 < len(narrowed) < 13


def test_an_article_can_be_written_out_in_every_offered_format():
    article = memory.ARTICLES[0]
    for suffix in memory.ARTICLE_FORMATS:
        rendered = memory.render_article(article, suffix)
        assert rendered.strip()
        assert article.title in rendered
    assert memory.render_article(article, ".md").startswith("# ")
    assert memory.render_article(article, ".html").lstrip().startswith("<")
    assert '"title"' in memory.render_article(article, ".json")


# ---------------------------------------------------------------------------
# what must never reach a visible string
# ---------------------------------------------------------------------------
def test_the_console_shows_a_meaningful_amount_of_text_to_check():
    # Guarding the guard: the patterns below prove nothing about an empty set.
    visible = [text for _where, text in _visible_strings() if text.strip()]
    assert len(visible) >= 400


def test_no_visible_string_leaks_a_machine_a_path_or_an_unfinished_note():
    offenders = []
    for description, pattern in FORBIDDEN_PATTERNS.items():
        compiled = re.compile(pattern, re.IGNORECASE)
        for where, text in _visible_strings():
            if text and compiled.search(text):
                offenders.append(f"{where} contains {description}: {text[:80]!r}")
    assert not offenders, offenders


def test_visible_strings_are_prose_rather_than_identifiers_shown_by_accident():
    """A label that is really a variable name has escaped from the code."""
    identifier = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")
    offenders = [
        f"{where}: {text!r}"
        for where, text in _visible_strings()
        if text and identifier.match(text.strip())
    ]
    assert not offenders, offenders


def test_the_console_never_reaches_the_network_for_its_content():
    """Every card and article is written into the module, not fetched."""
    tree = ast.parse(
        (ROOT / "amulet_map_editor/api/studio/memory_content.py").read_text(
            encoding="utf-8"
        )
    )
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(
        {"urllib", "requests", "http", "socket", "ftplib", "webbrowser"}
    ), sorted(imported)
