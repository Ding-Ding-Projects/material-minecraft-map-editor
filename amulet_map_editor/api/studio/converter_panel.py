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
        self.SetName("File converter")
        self._queue: List[_QueueEntry] = []
        self._results: List[core.ConvertResult] = []
        self._cancel_requested = False
        self._worker: Optional[threading.Thread] = None
        self._detected_format: Optional[str] = None

        outer = wx.BoxSizer(wx.VERTICAL)
        pad = tokens.scaled(tokens.SPACE_MD)

        title = SectionLabel(self, "Convert a local file")
        outer.Add(title, 0, wx.ALL, pad)

        self.source_field = PathField(
            self,
            "Source file",
            mode="file",
            on_change=self._on_source_changed,
        )
        outer.Add(self.source_field, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, pad)

        self.detected_label = StudioText(
            self, "No file chosen yet.", size_px=12, name="Detected source format"
        )
        outer.Add(self.detected_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, pad)

        self.target_choice = SearchableChoice(
            self,
            "Convert to",
            [],
            on_change=self._on_target_changed,
            hint="Only targets this build has a real adapter for are offered",
        )
        outer.Add(self.target_choice, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, pad)

        self.disclosure_card = Card(self)
        disclosure_sizer = wx.BoxSizer(wx.VERTICAL)
        self.disclosure_text = StudioText(
            self.disclosure_card,
            "Choose a source file to see what a conversion would change.",
            size_px=12,
            name="Loss and metadata disclosure",
        )
        disclosure_sizer.Add(
            self.disclosure_text, 0, wx.ALL, tokens.scaled(tokens.SPACE_SM)
        )
        self.disclosure_card.SetSizer(disclosure_sizer)
        outer.Add(
            self.disclosure_card, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, pad
        )

        self.destination_field = PathField(
            self, "Save converted file as", mode="save_file"
        )
        outer.Add(
            self.destination_field, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, pad
        )

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        self.add_to_batch_button = StudioButton(
            self,
            "Add to batch",
            variant="outlined",
            on_click=self._on_add_to_batch,
            name="Add this conversion to the batch queue",
        )
        button_row.Add(self.add_to_batch_button, 0)
        self.convert_button = StudioButton(
            self,
            "Convert",
            variant="filled",
            on_click=self._on_convert_now,
            name="Convert this one file now",
        )
        button_row.Add(self.convert_button, 0, wx.LEFT, tokens.scaled(tokens.SPACE_SM))
        outer.Add(button_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, pad)

        outer.Add(
            SectionLabel(self, "Batch queue"), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, pad
        )
        self.queue_search_state = SearchState(label="Batch queue")
        self.queue_search = SearchBar(
            self,
            "Filter the queue",
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
            "Convert batch",
            variant="filled",
            on_click=self._on_run_batch,
            name="Convert every file in the batch queue",
        )
        batch_row.Add(self.run_batch_button, 0)
        self.cancel_button = StudioButton(
            self,
            "Cancel",
            variant="outlined",
            on_click=self._on_cancel_batch,
            name="Cancel the running batch conversion",
        )
        self.cancel_button.Enable(False)
        batch_row.Add(self.cancel_button, 0, wx.LEFT, tokens.scaled(tokens.SPACE_SM))
        outer.Add(batch_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, pad)

        self.progress_row = ProgressRow(self, "Idle", 0.0, "")
        outer.Add(self.progress_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, pad)

        outer.Add(SectionLabel(self, "Results"), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, pad)
        self.results_search_state = SearchState(label="Conversion results")
        self.results_search = SearchBar(
            self,
            "Filter results",
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
            self.detected_label.set_text("No file chosen yet.")
            self.target_choice.set_options([])
            self.disclosure_text.set_text(
                "Choose a source file to see what a conversion would change."
            )
            return
        fmt = core.detect_source(path)
        self._detected_format = fmt
        self.detected_label.set_text(
            f"Detected: {format_display_name(fmt)}"
            if fmt
            else "Detected: unrecognised bytes -- no target can be offered."
        )
        adapters = registry.adapters_for_source(fmt)
        options = [a.display_name for a in adapters]
        self.target_choice.set_options(options)
        self._adapters_by_display = {a.display_name: a for a in adapters}
        if options:
            self._on_target_changed(options[0])
        else:
            self.disclosure_text.set_text(
                "This build has no adapter for that source format yet."
            )

    def _on_target_changed(self, display: str) -> None:
        adapter = getattr(self, "_adapters_by_display", {}).get(display)
        if adapter is None:
            return
        lossy_note = "Lossy" if adapter.lossy else "Lossless"
        self.disclosure_text.set_text(
            f"{lossy_note} conversion.\n"
            f"What may change: {adapter.loss_disclosure}\n"
            f"Metadata/encoding: {adapter.metadata_behaviour}"
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
                "queued",
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
                result.outcome.value,
            )
            self.results_sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(4))
        self.results_panel.Layout()
        self.Layout()
