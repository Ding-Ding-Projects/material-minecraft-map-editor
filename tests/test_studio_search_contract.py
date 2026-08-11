"""What every Amulet Studio search field promises, checked once for all of them.

Every search surface in the shell -- the ribbon's per-tab filter, the backstage
tables, the window search in each spec dialog, the command palette, every
context menu, and every searchable dropdown -- shares one
:class:`SearchState`.  That is deliberate: a regex toggle that behaves one way
in the palette and another in a menu is worse than no toggle, because the user
cannot learn it.

The feedback strings are asserted verbatim.  They are the only thing telling
somebody why a pattern found nothing, so a reworded line that no longer names
the failure is a real regression rather than a cosmetic one.
"""

from __future__ import annotations

from amulet_map_editor.api.studio.search import (
    DEFAULT_SAMPLE,
    MAX_PATTERN_LENGTH,
    SearchState,
)

EMPTY_FEEDBACK = "Plain-text search. Enable regex deliberately."
PLAIN_FEEDBACK = "Filtering by plain text."
VALID_REGEX_FEEDBACK = "Regex is valid."


def test_a_fresh_field_says_plain_text_is_the_default():
    state = SearchState()
    assert state.query == ""
    assert state.regex is False
    assert state.flags == "iu"
    assert state.sample == DEFAULT_SAMPLE
    assert state.is_active() is False
    assert state.is_valid() is True
    assert state.feedback() == EMPTY_FEEDBACK


def test_an_empty_query_matches_everything_rather_than_nothing():
    state = SearchState()
    assert state.matches("anything at all") is True
    assert state.matches("") is True
    assert state.filter(["a", "b", "c"]) == ["a", "b", "c"]


def test_plain_text_matching_is_a_case_insensitive_substring():
    state = SearchState(query="Rail")
    assert state.feedback() == PLAIN_FEEDBACK
    assert state.matches("Rail tunnel builder") is True
    assert state.matches("rail network") is True
    assert state.matches("Terrain brush") is False


def test_plain_text_never_reads_the_query_as_a_pattern():
    state = SearchState(query="1.17.")
    assert state.matches("1.17.1") is True
    assert state.matches("1a17b") is False
    assert SearchState(query="a|b").matches("a") is False
    assert SearchState(query="a|b").matches("a|b") is True


def test_a_valid_regex_reports_itself_valid_and_matches():
    state = SearchState(query=r"^rail.*tunnel$", regex=True)
    assert state.is_valid() is True
    assert state.error() == ""
    assert state.feedback() == VALID_REGEX_FEEDBACK
    assert state.matches("Rail tunnel") is True
    assert state.matches("tunnel rail") is False


def test_regex_matching_is_case_insensitive_and_unicode_aware():
    state = SearchState(query=r"\w+", regex=True)
    assert state.matches("蝦餃") is True
    assert SearchState(query="RAIL", regex=True).matches("rail") is True


def test_an_invalid_pattern_is_reported_and_matches_nothing():
    state = SearchState(query="rail(", regex=True)
    assert state.is_valid() is False
    assert state.feedback().startswith("Invalid pattern: ")
    assert state.error() == state.feedback()
    # The failure is surfaced, never absorbed: a broken pattern that silently
    # matched everything would look like a search that had been ignored.
    assert state.matches("rail tunnel") is False
    assert state.filter(["rail tunnel", "rail network"]) == []


def test_an_invalid_pattern_stops_being_invalid_once_it_is_fixed():
    state = SearchState(query="rail(", regex=True)
    assert state.is_valid() is False
    state.query = "rail"
    assert state.is_valid() is True
    assert state.feedback() == VALID_REGEX_FEEDBACK


def test_turning_regex_off_makes_an_unparseable_query_ordinary_text_again():
    state = SearchState(query="rail(", regex=True)
    assert state.is_valid() is False
    state.regex = False
    assert state.is_valid() is True
    assert state.error() == ""
    assert state.feedback() == PLAIN_FEEDBACK
    assert state.matches("rail(tunnel)") is True


def test_a_pathological_pattern_is_refused_by_length_before_it_is_compiled():
    state = SearchState(query="a" * (MAX_PATTERN_LENGTH + 1), regex=True)
    assert state.is_valid() is False
    assert state.feedback() == (
        f"Pattern is longer than {MAX_PATTERN_LENGTH} characters."
    )
    assert state.matches("a" * (MAX_PATTERN_LENGTH + 1)) is False
    assert SearchState(query="a" * MAX_PATTERN_LENGTH, regex=True).is_valid() is True


def test_flags_are_honoured_and_can_be_narrowed():
    state = SearchState(query="RAIL", regex=True, flags="u")
    assert state.matches("rail") is False
    assert state.matches("RAIL") is True
    multiline = SearchState(query="^second", regex=True, flags="im")
    assert multiline.matches("first\nsecond") is True
    single_line = SearchState(query="^second", regex=True, flags="iu")
    assert single_line.matches("first\nsecond") is False


def test_filter_uses_the_key_it_is_given():
    rows = [("Rail tunnel", "build"), ("Terrain brush", "terrain")]
    state = SearchState(query="terrain")
    assert state.filter(rows, key=lambda row: row[0]) == [("Terrain brush", "terrain")]
    assert state.filter(rows, key=lambda row: row[1]) == [("Terrain brush", "terrain")]
    assert SearchState(query="build").filter(rows, key=lambda row: row[0]) == []


def test_highlights_report_every_span_a_reader_should_see():
    plain = SearchState(query="ra")
    assert plain.highlights("rail rack") == ((0, 2), (5, 7))
    pattern = SearchState(query=r"\d+", regex=True)
    assert pattern.highlights("chunk 4 of 12") == ((6, 7), (11, 13))
    assert SearchState(query="x(", regex=True).highlights("x(") == ()
    assert SearchState().highlights("anything") == ()


def test_the_result_count_line_is_honest_about_the_empty_case():
    assert SearchState().describe_matches(0) == "0 results"
    assert SearchState().describe_matches(1) == "1 result"
    state = SearchState(query="rail")
    assert state.describe_matches(2) == "2 results match “rail”."
    assert state.describe_matches(0) == "No results match “rail”."
    broken = SearchState(query="rail(", regex=True)
    assert broken.describe_matches(0).startswith("No results — invalid pattern: ")


def test_resetting_clears_the_query_and_keeps_the_mode_the_user_chose():
    state = SearchState(query="rail(", regex=True)
    assert state.is_valid() is False
    state.reset()
    assert state.query == ""
    assert state.regex is True
    assert state.is_active() is False
    assert state.is_valid() is True
    assert state.feedback() == EMPTY_FEEDBACK


def test_whitespace_alone_is_not_a_query():
    state = SearchState(query="   ")
    assert state.is_active() is False
    assert state.feedback() == EMPTY_FEEDBACK
    assert state.matches("anything") is True


def test_a_label_travels_with_the_field_for_screen_readers_and_the_builder():
    state = SearchState(label="Search this tab's commands")
    assert state.label == "Search this tab's commands"
