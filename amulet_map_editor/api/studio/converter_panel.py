"""The universal local file converter surface.

A guided, entirely local panel: pick a source file, watch its real format
get detected from its bytes, choose from only the targets an adapter can
genuinely produce, preview the loss/metadata disclosure, and convert -- one
file or a whole batch, with progress, cancellation, and an honest per-file
result list. Nothing here ever touches the network, and a source file is
never overwritten.
"""

from __future__ import annotations

import os
import threading
from typing import Callable, List, Optional, Sequence

import wx

from amulet_map_editor.api import config
from amulet_map_editor.api.converter import core, registry
from amulet_map_editor.api.converter.signatures import (
    display_name as format_display_name,
)
from amulet_map_editor.api.studio import tokens
from amulet_map_editor.api.studio.copy import studio_label, studio_text
from amulet_map_editor.api.studio.search import SearchState
from amulet_map_editor.api.studio.widgets import (
    Card,
    ListRow,
    PathField,
    ProgressRow,
    SearchableChoice,
    SearchBar,
    SectionLabel,
    StudioButton,
    StudioText,
)

#: Persisted alongside every other profile record, so a picked destination
#: folder survives to the next session the way every other guided form does.
_LAST_DESTINATION_ID = "converter_last_destination_dir"

#: Localized display copy for each honest outcome bucket. Keyed by
#: ``ConvertOutcome.value`` so the row shown to a user matches the same
#: language mode as the rest of the panel, while ``result.outcome.value``
#: itself (used by filtering, history, and tests) stays the stable English
#: identifier documented in :mod:`amulet_map_editor.api.converter.core`.
_OUTCOME_LABELS = {
    "converted": ("converted", "轉換咗"),
    "skipped": ("skipped", "跳咗過"),
    "cancelled": ("cancelled", "取消咗"),
    "failed": ("failed", "失敗咗"),
}


def _outcome_label(outcome_value: str) -> str:
    english, cantonese = _OUTCOME_LABELS.get(outcome_value, (outcome_value, ""))
    return studio_label(english, cantonese)


class _QueueEntry:
    __slots__ = ("source_path", "adapter", "destination_path")

    def __init__(self, source_path: str, adapter, destination_path: str) -> None:
        self.source_path = source_path
        self.adapter = adapter
        self.destination_path = destination_path


class ConverterPanel(wx.Panel):
    """The full converter surface: pick, preview, queue, convert, review."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.SetName(studio_label("File converter", "檔案轉換器"))
        self._queue: List[_QueueEntry] = []
        self._results: List[core.ConvertResult] = []
        self._cancel_requested = False
        self._worker: Optional[threading.Thread] = None
        self._detected_format: Optional[str] = None

        outer = wx.BoxSizer(wx.VERTICAL)
        pad = tokens.scaled(tokens.SPACE_MD)

        title = SectionLabel(self, studio_label("Convert a local file", "轉換本機檔案"))
        outer.Add(title, 0, wx.ALL, pad)

        self.source_field = PathField(
            self,
            studio_label("Source file", "來源檔案"),
            mode="file",
            on_change=self._on_source_changed,
        )
        outer.Add(self.source_field, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, pad)

        self._no_file_text = studio_text(
            "No file chosen yet.", "重未揀檔案。"
        )
        self.detected_label = StudioText(
            self,
            self._no_file_text,
            size_px=12,
            name=studio_label("Detected source format", "偵測到嘅來源格式"),
        )
        outer.Add(self.detected_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, pad)

        self.target_choice = SearchableChoice(
            self,
            studio_label("Convert to", "轉換做"),
            [],
            on_change=self._on_target_changed,
            hint=studio_text(
                "Only targets this build has a real adapter for are offered",
                "呢個版本得返真係有轉換器嘅目標先會俾你揀。",
            ),
        )
        outer.Add(self.target_choice, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, pad)

        self.disclosure_card = Card(self)
        disclosure_sizer = wx.BoxSizer(wx.VERTICAL)
        self._choose_file_text = studio_text(
            "Choose a source file to see what a conversion would change.",
            "揀個來源檔案，睇下轉換會改動咩。",
        )
        self.disclosure_text = StudioText(
            self.disclosure_card,
            self._choose_file_text,
            size_px=12,
            name=studio_label("Loss and metadata disclosure", "資料流失同元資料披露"),
        )
        disclosure_sizer.Add(
            self.disclosure_text, 0, wx.ALL, tokens.scaled(tokens.SPACE_SM)
        )
        self.disclosure_card.SetSizer(disclosure_sizer)
        outer.Add(
            self.disclosure_card, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, pad
        )

        self.destination_field = PathField(
            self,
            studio_label("Save converted file as", "轉換後檔案儲存做"),
            mode="save_file",
        )
        outer.Add(
            self.destination_field, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, pad
        )

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        self.add_to_batch_button = StudioButton(
            self,
            studio_label("Add to batch", "加入批次"),
            variant="outlined",
            on_click=self._on_add_to_batch,
            name=studio_label("Add this conversion to the batch queue", "將呢個轉換加入批次隊列"),
        )
        button_row.Add(self.add_to_batch_button, 0)
        self.convert_button = StudioButton(
            self,
            studio_label("Convert", "轉換"),
            variant="filled",
            on_click=self._on_convert_now,
            name=studio_label("Convert this one file now", "即刻轉換呢個檔案"),
        )
        button_row.Add(self.convert_button, 0, wx.LEFT, tokens.scaled(tokens.SPACE_SM))
        outer.Add(button_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, pad)

        outer.Add(
            SectionLabel(self, studio_label("Batch queue", "批次隊列")),
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            pad,
        )
        self.queue_search_state = SearchState(
            label=studio_label("Batch queue", "批次隊列")
        )
        self.queue_search = SearchBar(
            self,
            studio_label("Filter the queue", "篩選隊列"),
            self.queue_search_state,
            on_change=self._on_queue_search_changed,
        )
        outer.Add(self.queue_search, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, pad)

        self.queue_panel = wx.Panel(self)
        self.queue_sizer = wx.BoxSizer(wx.VERTICAL)
        self.queue_panel.SetSizer(self.queue_sizer)
        outer.Add(self.queue_panel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, pad)

        batch_row = wx.BoxSizer(wx.HORIZONTAL)
        self.run_batch_button = StudioButton(
            self,
            studio_label("Convert batch", "轉換批次"),
            variant="filled",
            on_click=self._on_run_batch,
            name=studio_label(
                "Convert every file in the batch queue", "轉換批次隊列入面所有檔案"
            ),
        )
        batch_row.Add(self.run_batch_button, 0)
        self.cancel_button = StudioButton(
            self,
            studio_label("Cancel", "取消"),
            variant="outlined",
            on_click=self._on_cancel_batch,
            name=studio_label(
                "Cancel the running batch conversion", "取消而家進行緊嘅批次轉換"
            ),
        )
        self.cancel_button.Enable(False)
        batch_row.Add(self.cancel_button, 0, wx.LEFT, tokens.scaled(tokens.SPACE_SM))
        outer.Add(batch_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, pad)

        self.progress_row = ProgressRow(
            self, studio_label("Idle", "閒置中"), 0.0, ""
        )
        outer.Add(self.progress_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, pad)

        outer.Add(
            SectionLabel(self, studio_label("Results", "結果")),
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            pad,
        )
        self.results_search_state = SearchState(
            label=studio_label("Conversion results", "轉換結果")
        )
        self.results_search = SearchBar(
            self,
            studio_label("Filter results", "篩選結果"),
            self.results_search_state,
            on_change=self._on_results_search_changed,
        )
        outer.Add(
            self.results_search, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, pad
        )
        self.results_panel = wx.Panel(self)
        self.results_sizer = wx.BoxSizer(wx.VERTICAL)
        self.results_panel.SetSizer(self.results_sizer)
        outer.Add(
            self.results_panel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, pad
        )

        self.SetSizer(outer)
        self._refresh_queue_rows("")
        self._refresh_result_rows("")

    def _on_queue_search_changed(self, state: SearchState) -> None:
        self._refresh_queue_rows(state.query)

    def _on_results_search_changed(self, state: SearchState) -> None:
        self._refresh_result_rows(state.query)

    # -- source detection ---------------------------------------------

    def _on_source_changed(self, path: str) -> None:
        path = path.strip()
        self._detected_format = None
        if not path or not os.path.isfile(path):
            self.detected_label.set_text(self._no_file_text)
            self.target_choice.set_options([])
            self.disclosure_text.set_text(self._choose_file_text)
            return
        fmt = core.detect_source(path)
        self._detected_format = fmt
        self.detected_label.set_text(
            studio_text(
                f"Detected: {format_display_name(fmt)}",
                f"偵測到：{format_display_name(fmt)}",
            )
            if fmt
            else studio_text(
                "Detected: unrecognised bytes -- no target can be offered.",
                "偵測到：唔認得嘅位元組——冇目標可以俾你揀。",
            )
        )
        adapters = registry.adapters_for_source(fmt)
        options = [a.display_name for a in adapters]
        self.target_choice.set_options(options)
        self._adapters_by_display = {a.display_name: a for a in adapters}
        if options:
            self._on_target_changed(options[0])
        else:
            self.disclosure_text.set_text(
                studio_text(
                    "This build has no adapter for that source format yet.",
                    "呢個版本重未有呢種來源格式嘅轉換器。",
                )
            )

    def _on_target_changed(self, display: str) -> None:
        adapter = getattr(self, "_adapters_by_display", {}).get(display)
        if adapter is None:
            return
        lossy_note = (
            studio_label("Lossy", "會流失資料")
            if adapter.lossy
            else studio_label("Lossless", "唔會流失資料")
        )
        what_may_change = studio_label("What may change", "可能會改變咩")
        metadata_encoding = studio_label("Metadata/encoding", "元資料／編碼")
        self.disclosure_text.set_text(
            f"{lossy_note}.\n"
            f"{what_may_change}: {adapter.loss_disclosure}\n"
            f"{metadata_encoding}: {adapter.metadata_behaviour}"
        )

    def _current_adapter(self):
        display = getattr(self.target_choice, "value", "")
        return getattr(self, "_adapters_by_display", {}).get(display)

    # -- single conversion ----------------------------------------------

    def _on_convert_now(self) -> None:
        source_path = self.source_field.field.value().strip()
        destination_path = self.destination_field.field.value().strip()
        adapter = self._current_adapter()
        if not source_path or not adapter or not destination_path:
            return
        overwrite = os.path.exists(destination_path)
        result = core.convert_one(
            source_path, adapter.id, destination_path, overwrite_confirmed=overwrite
        )
        self._results.append(result)
        self._refresh_result_rows(self.results_search_state.query)

    # -- batch queue ------------------------------------------------------

    def _on_add_to_batch(self) -> None:
        source_path = self.source_field.field.value().strip()
        destination_path = self.destination_field.field.value().strip()
        adapter = self._current_adapter()
        if not source_path or not adapter or not destination_path:
            return
        self._queue.append(_QueueEntry(source_path, adapter, destination_path))
        self._refresh_queue_rows("")

    def _refresh_queue_rows(self, query: str) -> None:
        self.queue_sizer.Clear(delete_windows=True)
        query_lower = (query or "").lower()
        for entry in self._queue:
            haystack = f"{entry.source_path} {entry.adapter.display_name}".lower()
            if query_lower and query_lower not in haystack:
                continue
            row = ListRow(
                self.queue_panel,
                os.path.basename(entry.source_path),
                entry.adapter.display_name,
                studio_label("queued", "排緊隊"),
            )
            self.queue_sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(4))
        self.queue_panel.Layout()
        self.Layout()

    def _on_run_batch(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        jobs = [
            {
                "source_path": entry.source_path,
                "adapter_id": entry.adapter.id,
                "destination_path": entry.destination_path,
                "overwrite_confirmed": os.path.exists(entry.destination_path),
            }
            for entry in self._queue
        ]
        if not jobs:
            return
        self._cancel_requested = False
        self.cancel_button.Enable(True)
        self.run_batch_button.Enable(False)

        def _progress(done: int, total: int, result: core.ConvertResult) -> None:
            self._results.append(result)
            wx.CallAfter(
                self.progress_row.set_progress,
                done / total if total else 1.0,
                f"{done}/{total}",
            )
            wx.CallAfter(self._refresh_result_rows, "")

        def _run() -> None:
            core.convert_batch(
                jobs,
                should_cancel=lambda: self._cancel_requested,
                on_progress=_progress,
            )
            wx.CallAfter(self._on_batch_finished)

        self._worker = threading.Thread(target=_run, daemon=True)
        self._worker.start()

    def _on_batch_finished(self) -> None:
        self.cancel_button.Enable(False)
        self.run_batch_button.Enable(True)
        self._queue.clear()
        self._refresh_queue_rows("")

    def _on_cancel_batch(self) -> None:
        self._cancel_requested = True

    # -- results ------------------------------------------------------

    def _refresh_result_rows(self, query: str) -> None:
        self.results_sizer.Clear(delete_windows=True)
        query_lower = (query or "").lower()
        for result in reversed(self._results):
            haystack = (
                f"{result.source_path} {result.outcome.value} {result.reason}".lower()
            )
            if query_lower and query_lower not in haystack:
                continue
            row = ListRow(
                self.results_panel,
                os.path.basename(result.source_path),
                result.reason or (result.output_path or ""),
                _outcome_label(result.outcome.value),
            )
            self.results_sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(4))
        self.results_panel.Layout()
        self.Layout()
