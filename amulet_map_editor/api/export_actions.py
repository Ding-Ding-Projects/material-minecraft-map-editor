"""Shared actions for producing exports and handing them to the editor.

Two jobs live here, and both exist so that a surface which owns data does not
have to reinvent them.

*Opening what was produced.*  :func:`open_exported_path` keeps editor
discovery, path validation, and failure handling in one place, so a missing or
broken external editor can never fail an export.

*Producing it in the first place.*  Every record, view, list, log, document,
setting, and generated artifact the application owns is exportable, and the
format list is offered per datum rather than one favourite for the whole
application: :func:`offer_formats` asks
:mod:`amulet_map_editor.api.studio.exporters` what a specific dataset can be
written as, and returns each format with what it would cost.  A format that
cannot carry the data faithfully still appears -- hiding it would be its own
kind of dishonesty -- but it arrives with the fields it would flatten, the
reason, and the number of records affected, and :func:`export_dataset` refuses
to write it until a caller has said ``accept_loss=True``.

The module imports no wx.  ``exporters`` is resolved on first use so that the
many user-interface modules importing this one for
:func:`open_exported_path` alone do not pay for the format catalogue.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence, TYPE_CHECKING

from amulet_map_editor.api import external_editor

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from amulet_map_editor.api.studio import exporters as _exporters_module

_EXPORTERS: Any = None


def _exporters() -> Any:
    """Return the exporters module, imported the first time it is needed."""

    global _EXPORTERS
    if _EXPORTERS is None:
        from amulet_map_editor.api.studio import exporters as module

        _EXPORTERS = module
    return _EXPORTERS


def __getattr__(name: str) -> Any:
    """Expose ``export_actions.exporters`` without importing it eagerly."""

    if name == "exporters":
        return _exporters()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------------------
# opening a produced export
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ExportEditorAction:
    """The export target and the structured editor outcome."""

    target: Path
    result: external_editor.EditorResult

    @property
    def ok(self) -> bool:
        return self.result.ok

    @property
    def message(self) -> str:
        return self.result.message


def open_exported_path(
    target: str | Path,
    *,
    opener: Callable[[str | Path], external_editor.EditorResult] | None = None,
) -> ExportEditorAction:
    """Open an exported file/folder, returning a safe non-throwing result.

    ``opener`` is injectable for wx-independent tests.  Unexpected launcher
    failures are converted into the same structured result contract as the
    external-editor bridge, so a missing or broken editor cannot fail export.
    """

    path = Path(target).expanduser()
    launch = opener or external_editor.open_path
    try:
        result = launch(path)
    except Exception as exc:  # pragma: no cover - defensive boundary
        result = external_editor.EditorResult(
            False, "launch_failed", f"Could not open the exported path: {exc}"
        )
    return ExportEditorAction(path, result)


# ---------------------------------------------------------------------------
# offering formats for one datum
# ---------------------------------------------------------------------------
def offer_formats(dataset: "_exporters_module.Dataset") -> tuple[Any, ...]:
    """Return every format this dataset can be written as, best fit first.

    Each offer carries the catalogue entry and a fidelity report measured
    against the dataset's real values, which is what a picker shows beside the
    format name so nobody chooses one blind.
    """

    return _exporters().format_offers(dataset)


def lossless_formats(dataset: "_exporters_module.Dataset") -> tuple[str, ...]:
    """Return the ids of the formats that carry this dataset whole."""

    return tuple(
        offer.format_id
        for offer in offer_formats(dataset)
        if offer.available and offer.lossless
    )


def preview_export(
    dataset: "_exporters_module.Dataset", format_id: str
) -> "_exporters_module.FidelityReport":
    """Return what a format would and would not carry, before anything runs."""

    return _exporters().describe_fidelity(dataset, format_id)


def recommended_format(dataset: "_exporters_module.Dataset") -> str:
    """Return the id of the format that carries this datum whole and reads back."""

    return _exporters().recommended_format(dataset).id


def resolve_target(
    target: str | os.PathLike[str],
    dataset: "_exporters_module.Dataset",
    format_id: str,
) -> Path:
    """Return the file an export should be written to.

    A directory, or a name with no extension, gets the dataset's name and the
    format's own extension; a name the caller spelled out is left exactly as
    they spelled it.
    """

    exporters = _exporters()
    fmt = exporters.resolve_format(format_id)
    path = Path(target).expanduser()
    text = os.fspath(target)
    looks_like_directory = text.endswith(("/", "\\")) or path.is_dir()
    if looks_like_directory:
        return path / f"{dataset.name}{fmt.extension}"
    if not path.suffix:
        return path.with_name(f"{path.name}{fmt.extension}")
    return path


# ---------------------------------------------------------------------------
# producing one export
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ExportResult:
    """One written export, with what the format could not carry stated."""

    target: Path
    format_id: str
    format_label: str
    report: "_exporters_module.FidelityReport"
    bytes_written: int
    editor: ExportEditorAction | None = None

    @property
    def lossless(self) -> bool:
        return self.report.lossless

    @property
    def message(self) -> str:
        return f"{self.format_label} written to {self.target.name}. " + (
            self.report.summary()
        )


def export_dataset(
    dataset: "_exporters_module.Dataset",
    target: str | os.PathLike[str],
    format_id: str | None = None,
    *,
    accept_loss: bool = False,
    open_after: bool = False,
    opener: Callable[[str | Path], external_editor.EditorResult] | None = None,
    timestamp: Any = None,
    preamble: bool = True,
) -> ExportResult:
    """Write one dataset in one format, refusing a loss nobody agreed to.

    ``format_id`` defaults to the format that carries this particular datum
    whole, which is the point of offering the list per datum: the default is a
    property of the data, not a favourite baked into the application.
    """

    exporters = _exporters()
    chosen = format_id or recommended_format(dataset)
    fmt = exporters.resolve_format(chosen)
    report = exporters.describe_fidelity(dataset, fmt.id)
    path = resolve_target(target, dataset, fmt.id)
    exporters.write_export(
        dataset,
        path,
        fmt.id,
        accept_loss=accept_loss,
        timestamp=timestamp,
        preamble=preamble,
    )
    editor = open_exported_path(path, opener=opener) if open_after else None
    return ExportResult(
        target=path,
        format_id=fmt.id,
        format_label=fmt.label,
        report=report,
        bytes_written=path.stat().st_size,
        editor=editor,
    )


def export_dataset_text(
    dataset: "_exporters_module.Dataset",
    format_id: str,
    *,
    accept_loss: bool = False,
    timestamp: Any = None,
    preamble: bool = True,
) -> str:
    """Return one export as text, for a clipboard or a preview pane."""

    return _exporters().export_text(
        dataset,
        format_id,
        accept_loss=accept_loss,
        timestamp=timestamp,
        preamble=preamble,
    )


# ---------------------------------------------------------------------------
# producing an archive of several
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BundleResult:
    """One written archive, its plan, and every export inside it."""

    archive: "_exporters_module.ArchiveResult"
    reports: tuple[Any, ...]
    editor: ExportEditorAction | None = None

    @property
    def target(self) -> Path:
        return self.archive.path

    @property
    def members(self) -> tuple[str, ...]:
        return self.archive.members

    @property
    def message(self) -> str:
        return (
            f"{self.archive.kind.upper()} written to {self.archive.path.name}: "
            f"{len(self.archive.members)} files, {self.archive.size} bytes.  "
            f"{self.archive.plan.protection}"
        )


def export_bundle(
    datasets: Sequence["_exporters_module.Dataset"],
    target: str | os.PathLike[str],
    *,
    formats: Iterable[str] = ("json", "csv", "markdown"),
    kind: str = "zip",
    zip_options: Any = None,
    seven_zip_options: Any = None,
    sensitive: bool = False,
    accept_loss: bool = False,
    accept_unencrypted: bool = False,
    accept_visible_names: bool = False,
    accept_unhonoured: bool = False,
    open_after: bool = False,
    opener: Callable[[str | Path], external_editor.EditorResult] | None = None,
    timestamp: Any = None,
) -> BundleResult:
    """Write several datasets, in several formats, into one archive.

    Member names stay relative so extraction cannot escape its own directory,
    a manifest and a README travel with them so the archive explains itself
    without this application, and a record set marked as carrying secrets
    refuses to enter an archive the caller has not marked sensitive.
    """

    exporters = _exporters()
    format_ids = tuple(formats)
    members = exporters.bundle_members(
        datasets,
        format_ids,
        accept_loss=accept_loss,
        timestamp=timestamp,
    )
    archive = exporters.write_archive(
        members,
        target,
        kind=kind,
        zip_options=zip_options,
        seven_zip_options=seven_zip_options,
        sensitive=sensitive,
        accept_unencrypted=accept_unencrypted,
        accept_visible_names=accept_visible_names,
        accept_unhonoured=accept_unhonoured,
    )
    reports = tuple(
        exporters.describe_fidelity(dataset, format_id)
        for dataset in datasets
        for format_id in format_ids
    )
    editor = open_exported_path(archive.path, opener=opener) if open_after else None
    return BundleResult(archive=archive, reports=reports, editor=editor)


def describe_archive(
    kind: str = "zip",
    *,
    zip_options: Any = None,
    seven_zip_options: Any = None,
) -> "_exporters_module.ArchivePlan":
    """Return what an archive would cost and what it would protect, up front.

    A caller shows this beside the archive controls: what each compression
    choice charges in time and memory, whether the file names would be hidden
    as well as the contents, and the exact named reason when 7z cannot be
    written here at all.
    """

    exporters = _exporters()
    key = str(kind).strip().lower().lstrip(".")
    if key == "zip":
        return exporters.describe_zip(zip_options)
    if key in {"7z", "sevenzip", "seven_zip"}:
        return exporters.describe_seven_zip(seven_zip_options)
    raise exporters.ArchiveOptionError(
        f"Unknown archive kind {kind!r}; this application writes zip and 7z."
    )
