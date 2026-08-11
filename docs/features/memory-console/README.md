# Memory Console

The Memory Console is the second surface the spec renderer cannot express. It is
a rail of thirteen views over the guidance records this machine keeps and the
feature articles this documentation set contains, laid out as a card grid with a
two-pane documentation reader inside it.

## Behaviour

Thirteen rail views: **Overview**, **Sync**, **Skills**, **Memory**, **Docs**,
**History**, **Changelog**, **Operations**, **Security**, **Two-factor**,
**Locks**, **Status Hub**, and **Settings**.

Each view is a page of cards laid out on a twelve-column grid; a card declares
how many columns it spans and the console wraps when the next card will not fit
in what is left. A card can carry a large statistic, prose, a list of records, a
transcript, or any combination — a card holding only a number is as ordinary as
one holding a list and a code block.

Every row inside a card does something. A row can move the console to another
view, open one article in the reader, or open a Studio surface; a row with no
target is a record whose note is shown instead. A row that looked pressable and
did nothing would be worse than plain text, so the suite checks every target
resolves.

**Docs** is a working two-pane reader over the feature articles: domain filter
pills across the top, a searchable list on the left, and the article on the
right with its repository path and summary. The search field carries the regex
opt-in and the `.*` builder, and the domain counts are computed rather than
written down, so a filter that would show nothing is visible as a zero.

An article can be written out in Markdown, plain text, HTML, or JSON. Markdown
is offered first because it is the source form.

## Configuration

The content is a data module — `amulet_map_editor/api/studio/memory_content.py`
— rather than a scrape of anything. Domains are a grouping of feature areas
rather than a folder, so moving an article between folders does not silently
drop it out of its filter.

Each article carries the repository path it came from, shown monospaced and used
verbatim when the path is copied or the article is opened in an external editor.

## Failure modes

An article path that names a file which is not in the repository is a failing
check, because that path is shown to the reader and handed to an editor. A
search matching nothing says what it searched for. An invalid pattern is
reported and matches nothing rather than being ignored.

A view with no cards, or a card with nothing below its own heading, is a failing
check rather than a blank region a reader has to interpret.

## Security and accessibility

The console reads nothing over the network and imports no network module at all;
every card and article is written into the module. It shows no credentials,
tokens, or secrets, and the suite refuses any visible string containing a
private network address, a home directory, a remote shell target, an unfinished
placeholder, or a Python repr that escaped into the interface.

The rail is keyboard-navigable with visible focus, every card and row is named,
the card grid reflows at narrow widths, and the reader's two panes stack rather
than clipping when there is not room for both.

## Verification

```powershell
py -3 -m pytest tests/test_studio_memory_content.py -q
```

That file checks the thirteen views exist in order and each shows something,
that every card fits the grid and is not an empty heading, that every pressable
row resolves to a real view, article, or surface, that every article has a path
that exists on disk along with a domain, a summary, and a real body, that every
domain filter has something behind it, that all four export formats produce
something, and that no visible string leaks a machine, a path, or a placeholder.

Suggested articles: [offline documentation](../offline-documentation/README.md),
[search, regular expressions, and the command palette](../search-and-regex/README.md),
[settings and appearance](../settings/README.md), and
[exports](../exports/README.md).
