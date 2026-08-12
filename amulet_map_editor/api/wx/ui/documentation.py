"""Native offline documentation browser backed by :mod:`docs_browser`."""

from __future__ import annotations

import html
import re

import wx
import wx.html

from amulet_map_editor.api.docs_browser import (
    DocumentationBundleError,
    DocumentationIndex,
    load_bundled_articles,
)
from amulet_map_editor.api import preferences
from amulet_map_editor.api import lang
from amulet_map_editor.api.studio import widgets as studio
from amulet_map_editor.api.wx.material3 import apply_material3
from amulet_map_editor.api.wx.modeless import finish_dialog
from amulet_map_editor.api.wx.ui import material_forms as forms
from amulet_map_editor.api.wx.ui.regex_dialog import RegexBuilderDialog


def _copy(key: str, mode: str) -> str:
    """Return localized chrome copy in the persisted three-mode contract."""

    english = lang.get(f"documentation.en.{key}")
    cantonese = lang.get(f"documentation.zh.{key}")
    if mode == "cantonese":
        return cantonese
    if mode == "bilingual":
        return f"{english} · {cantonese}"
    return english


def _markdown_to_html(index: DocumentationIndex, slug: str, markdown: str) -> str:
    """Render the small, trusted feature-article subset without network access."""

    article = index.get(slug)
    lines: list[str] = ["<html><body style='font-family: sans-serif; padding: 12px;'>"]
    in_list = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            if in_list:
                lines.append("</ul>")
                in_list = False
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            if in_list:
                lines.append("</ul>")
                in_list = False
            level = len(heading.group(1))
            lines.append(f"<h{level}>{html.escape(heading.group(2))}</h{level}>")
            continue
        bullet = re.match(r"^[-*]\s+(.+)$", line)
        if bullet:
            if not in_list:
                lines.append("<ul>")
                in_list = True
            lines.append(f"<li>{_inline(index, article.slug, bullet.group(1))}</li>")
            continue
        if in_list:
            lines.append("</ul>")
            in_list = False
        lines.append(f"<p>{_inline(index, article.slug, line)}</p>")
    if in_list:
        lines.append("</ul>")
    lines.append("</body></html>")
    return "".join(lines)


def _inline(index: DocumentationIndex, slug: str, text: str) -> str:
    escaped = html.escape(text)

    def replace(match: re.Match[str]) -> str:
        label = html.escape(match.group(1))
        target = match.group(2)
        linked = index.resolve(slug, target)
        if linked is not None:
            return f"<a href='amulet://article/{html.escape(linked.slug)}'>{label}</a>"
        parsed = target if target.startswith(("https://", "http://")) else "#"
        return f"<a href='{html.escape(parsed)}'>{label}</a>"

    return re.sub(r"\[([^]]+)\]\(([^)\s]+)(?:\s+[^)]*)?\)", replace, escaped)


class DocumentationDialog(wx.Dialog):
    """Browse bundled feature articles while offline."""

    def __init__(self, parent: wx.Window):
        self._language_mode = preferences.load().language_mode
        super().__init__(
            parent,
            title=_copy("title", self._language_mode),
            size=wx.Size(900, 620),
            style=wx.NO_BORDER | wx.RESIZE_BORDER,
        )
        self._index = load_bundled_articles()
        self._visible = self._index.articles

        root = wx.BoxSizer(wx.VERTICAL)
        filters = wx.BoxSizer(wx.HORIZONTAL)
        self.query = forms.MaterialTextField(
            self,
            placeholder=_copy("search_hint", self._language_mode),
            name="Documentation search",
        )
        self.regex = studio.StudioCheckBox(
            self, _copy("regex", self._language_mode), name="Documentation regex mode"
        )
        self.regex_button = studio.StudioButton(
            self,
            label="Regex…",
            variant="outlined",
            hint="Build a bounded regular-expression search",
            name="Documentation search regex builder",
        )
        self.feedback = studio.StudioText(
            self, "", size_px=12, role="on_surface_variant"
        )
        filters.Add(self.query, 1, wx.EXPAND | wx.RIGHT, 8)
        filters.Add(self.regex, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        filters.Add(self.regex_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        filters.Add(self.feedback, 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(filters, 0, wx.EXPAND | wx.ALL, 12)

        body = wx.BoxSizer(wx.HORIZONTAL)
        self.results = forms.MaterialListBox(self, name="Documentation articles")
        self.results.SetMinSize(wx.Size(250, -1))
        body.Add(self.results, 0, wx.EXPAND | wx.RIGHT, 12)
        self.article_view = wx.html.HtmlWindow(self, style=wx.html.HW_SCROLLBAR_AUTO)
        body.Add(self.article_view, 1, wx.EXPAND)
        root.Add(body, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        close = studio.StudioButton(
            self,
            _copy("close", self._language_mode),
            variant="outlined",
            name="Close documentation",
        )
        close.SetId(wx.ID_CLOSE)
        close.Bind(wx.EVT_BUTTON, lambda _event: finish_dialog(self, wx.ID_CANCEL))
        root.Add(close, 0, wx.ALIGN_RIGHT | wx.ALL, 12)
        self.SetSizer(root)
        self._search_flags = 0
        for control in (self.query, self.regex):
            event = wx.EVT_TEXT if control is self.query else wx.EVT_CHECKBOX
            control.Bind(event, self._refresh)
        self.regex_button.Bind(wx.EVT_BUTTON, self._open_regex_builder)
        self.results.Bind(wx.EVT_LISTBOX, self._show_selected)
        self.article_view.Bind(wx.html.EVT_HTML_LINK_CLICKED, self._follow_link)
        apply_material3(self)
        self._refresh()

    def _open_regex_builder(self, _event) -> None:
        with RegexBuilderDialog(
            self,
            pattern=self.query.GetValue(),
            regex_enabled=self.regex.GetValue(),
            flags=self._search_flags,
            sample="Article title and body",
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self.query.ChangeValue(dialog.pattern)
            self.regex.SetValue(dialog.regex_enabled)
            self._search_flags = dialog.flags
        self._refresh()

    def _refresh(self, _event: wx.Event | None = None) -> None:
        try:
            self._visible = (
                self._index.search(
                    self.query.GetValue()[:4096],
                    regex=self.regex.GetValue(),
                    flags=self._search_flags,
                )
                if self.query.GetValue()
                else tuple(self._index.articles)
            )
        except DocumentationBundleError as exc:
            self._visible = ()
            self.feedback.SetLabel(
                f"{_copy('invalid_search', self._language_mode)}: {exc}"
            )
        else:
            self.feedback.SetLabel(
                _copy("article_count", self._language_mode).format(
                    count=len(self._visible)
                )
            )
        self.results.Set(
            [
                article.title
                for item in self._visible
                for article in [getattr(item, "article", item)]
            ]
        )
        if self._visible:
            self.results.SetSelection(0)
            self._show_selected()
        else:
            self.article_view.SetPage(
                "<html><body><p>"
                + html.escape(_copy("no_match", self._language_mode))
                + "</p></body></html>"
            )

    def _show_selected(self, _event: wx.Event | None = None) -> None:
        if not self._visible or self.results.GetSelection() == wx.NOT_FOUND:
            return
        item = self._visible[self.results.GetSelection()]
        article = getattr(item, "article", item)
        self.article_view.SetPage(
            _markdown_to_html(self._index, article.slug, article.markdown)
        )

    def _follow_link(self, event: wx.html.HtmlLinkEvent) -> None:
        href = event.GetLinkInfo().GetHref()
        prefix = "amulet://article/"
        if href.startswith(prefix):
            try:
                article = self._index.get(href.removeprefix(prefix))
            except DocumentationBundleError:
                return
            self.query.ChangeValue("")
            self._visible = self._index.articles
            self.results.Set([item.title for item in self._visible])
            self.results.SetSelection(self._visible.index(article))
            self._show_selected()
