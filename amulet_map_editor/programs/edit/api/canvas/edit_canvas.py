import logging
import warnings
import wx
from dataclasses import dataclass
from typing import Callable, Any, Generator, Optional, Iterable
from types import GeneratorType
from threading import RLock, Thread
import sys
import os

from .base_edit_canvas import BaseEditCanvas
from ...edit import EDIT_CONFIG_ID
from ..key_config import (
    DefaultKeys,
    DefaultKeybindGroupId,
    PresetKeybinds,
    KeybindGroup,
)

import time
import traceback

from OpenGL.GL import (
    glClear,
    glEnable,
    GL_SCISSOR_TEST,
    glScissor,
    glClearColor,
    GL_COLOR_BUFFER_BIT,
    glDisable,
)

from amulet.api.data_types import OperationReturnType, OperationYieldType, Dimension
from amulet.api.structure import structure_cache
from amulet.api.level import BaseLevel

from amulet_map_editor import CONFIG
from amulet_map_editor.api import preferences
from amulet_map_editor.api.outcome import Outcome
from amulet_map_editor import close_level
from amulet_map_editor.api.wx.nonblocking import notify, notify_exception
from amulet_map_editor.programs.edit.api.ui.goto import show_goto
from amulet_map_editor.programs.edit.api.ui.tool_manager import ToolManagerSizer
from amulet_map_editor.programs.edit.api.operations.errors import (
    OperationError,
    OperationSilentAbort,
    OperationSuccessful,
    BaseLoudException,
    BaseSilentException,
)
from amulet_map_editor.programs.edit.plugins.operations.stock_plugins.internal_operations import (
    cut,
    copy,
    delete,
)

from amulet_map_editor.programs.edit.api.events import (
    UndoEvent,
    RedoEvent,
    CreateUndoEvent,
    SaveEvent,
    ToolChangeEvent,
    EVT_EDIT_CLOSE,
)
from amulet_map_editor.programs.edit.api.ui.file import FilePanel

log = logging.getLogger(__name__)
OperationType = Callable[[], OperationReturnType]


def _copy_never_rolls_back() -> bool:
    """Answer :meth:`EditCanvas.run_operation`'s rollback question for a copy.

    A named function rather than an inline ``lambda: False`` so that the answer
    can be read, and so the reason for it lives somewhere: a copy reads chunks
    and puts a structure in the clipboard.  It writes nothing to the world, at
    any point, on any path -- so there is never anything for a rollback to
    undo, and the rollback that used to run had reach only into the editor's
    own selection history.  See :meth:`EditCanvas.copy`.
    """
    return False


@dataclass(frozen=True)
class OperationOutcome(Outcome):
    """What one call to :meth:`EditCanvas.run_operation` actually did.

    ``run_operation`` used to answer ``None`` whether the operation wrote four
    hundred blocks, ran and wrote nothing, or raised and was contained -- so a
    caller carefully wrapping it in ``try``/``except`` was writing code that
    could never run, and one that carried on afterwards was building on a write
    that may never have happened.  This says which of the three it was.

    ``bool(outcome)`` is still the simple question, and it is true only when the
    operation completed and an undo point was recorded.  ``reason`` is the
    stable token for everything else:

    * ``""`` -- it ran and the undo point was created.  ``ok`` is true.
    * ``"aborted"`` -- a :class:`BaseSilentException`: the user cancelled the
      progress dialog, or the operation stopped itself deliberately and quietly.
      Nothing went wrong, so a caller must **not** announce a failure.  It also
      must not read this as "the operation did nothing": the stock ``copy``
      raises exactly this on the path where it *succeeded*, to decline an undo
      point for a read-only operation, and the cancel path raises the same class
      from the same place.  The token cannot tell those apart and does not
      pretend to -- see :meth:`EditCanvas._lift` for what to ask instead.
    * ``"nothing-copied"`` -- :meth:`EditCanvas.copy` and :meth:`EditCanvas.cut`
      only: the operation stopped quietly and the clipboard did not grow, so
      whatever the paste tool would pick up is the previous copy rather than
      this one.
    * ``"stopped"`` -- an :class:`OperationSuccessful`: the operation ended
      itself with a message the user has already been shown, and no undo point
      was created.  Again not an error.
    * ``"raised"`` -- the operation raised and the exception was contained here.
      ``_run_operation`` has already reported it through the non-blocking
      notifier, so a caller adds context rather than repeating the traceback.
    * ``"no-undo-point"`` -- the operation itself succeeded and creating the
      undo point afterwards did not.  ``ok`` is **true**: the world was written
      and saying otherwise would send somebody looking for blocks that are
      there.  What is missing is the ability to undo it.

    :attr:`failed` is the question nearly every caller actually has -- "did this
    stop because something went wrong, rather than because somebody chose to
    stop it" -- so that a cancelled paste is not reported as a broken one.

    ``value`` is whatever the operation returned, which is what ``run_operation``
    used to return directly.  ``error`` is the contained exception, kept so a
    caller can name it without re-reading the log.
    """

    #: The operation's own return value, or ``None`` when it did not get there.
    value: Any = None
    #: The exception that was contained, if one was.
    error: Optional[BaseException] = None

    @property
    def failed(self) -> bool:
        """Whether this stopped because something went wrong.

        A deliberate abort is not a failure and must not be shown as one; an
        operation that ran and then lost its undo point is a failure of the undo
        point rather than of the write, and is reported as one while ``ok``
        stays true.
        """
        return self.reason in ("raised", "no-undo-point")


def contained_outcome(error: Exception, out: Any = None) -> OperationOutcome:
    """Describe an exception ``run_operation`` caught instead of raising.

    The distinction drawn here is the one the user can see: a cancelled
    operation and a broken one both end with nothing written, and only one of
    them is worth a red notification.  ``_run_operation`` has already shown the
    loud ones and deliberately said nothing about the silent ones, so the token
    is what tells a caller which of those happened without it having to
    re-derive the exception's class for itself.

    A module function rather than a method because it reads no canvas state, and
    because that lets ``run_operation`` be exercised against a stand-in ``self``
    without the test having to supply a helper it does not care about.
    """
    if isinstance(error, BaseSilentException):
        return OperationOutcome(
            ok=False, reason="aborted", message=str(error), value=out, error=error
        )
    if isinstance(error, OperationSuccessful):
        return OperationOutcome(
            ok=False, reason="stopped", message=str(error), value=out, error=error
        )
    return OperationOutcome(
        ok=False,
        reason="raised",
        message=str(error) or type(error).__name__,
        value=out,
        error=error,
    )


def show_loading_dialog(
    run: OperationType, title: str, message: str, parent: wx.Window
) -> Any:
    warnings.warn("show_loading_dialog is depreciated.", DeprecationWarning)
    dialog = wx.ProgressDialog(
        title,
        message,
        maximum=10_000,
        parent=parent,
        style=wx.PD_APP_MODAL
        | wx.PD_ELAPSED_TIME
        | wx.PD_REMAINING_TIME
        | wx.PD_AUTO_HIDE,
    )
    dialog.Fit()
    t = time.time()
    try:
        obj = run()
        if isinstance(obj, GeneratorType):
            try:
                while True:
                    progress = next(obj)
                    if isinstance(progress, (list, tuple)):
                        if len(progress) >= 2:
                            message = progress[1]
                        if len(progress) >= 1:
                            progress = progress[0]
                    if isinstance(progress, (int, float)) and isinstance(message, str):
                        dialog.Update(
                            min(9999, max(0, int(progress * 10_000))), message
                        )
                    wx.Yield()
            except StopIteration as e:
                obj = e.value
    except Exception as e:
        dialog.Update(10_000)
        raise e
    time.sleep(max(0.2 - time.time() + t, 0))
    dialog.Update(10_000)
    return obj


class OperationThread(Thread):
    # The operation to run
    _operation: OperationType

    # Should the operation be stopped. Set externally
    stop: bool
    # The starting message for the progress dialog
    message: str
    # The operation progress (from 0-1)
    progress: float
    # The return value from the operation
    out: Any
    # The error raised if any
    error: Optional[BaseException]

    def __init__(self, operation: OperationType, message: str):
        super().__init__()
        self._operation = operation
        self.stop = False
        self.message = message
        self.progress = 0.0
        self.out = None
        self.error = None

    def run(self) -> None:
        t = time.time()
        obj: Any = None
        try:
            obj = self._operation()
            if isinstance(obj, GeneratorType):
                try:
                    while True:
                        if self.stop:
                            raise OperationSilentAbort
                        progress = next(obj)
                        if isinstance(progress, (list, tuple)):
                            if len(progress) >= 2:
                                self.message = progress[1]
                            if len(progress) >= 1:
                                self.progress = progress[0]
                        elif isinstance(progress, (int, float)):
                            self.progress = progress
                except StopIteration as e:
                    self.out = e.value
        except BaseException as e:
            self.error = e
        finally:
            if isinstance(obj, GeneratorType):
                try:
                    obj.close()
                except BaseException as e:
                    if self.error is None:
                        self.error = e
                    else:
                        log.exception("Exception while closing operation generator")
        time.sleep(max(0.2 - time.time() + t, 0))


class EditCanvas(BaseEditCanvas):
    def __init__(self, parent: wx.Window, world: "BaseLevel"):
        super().__init__(parent, world)
        self._file_panel: Optional[FilePanel] = None
        self._tool_sizer: Optional[ToolManagerSizer] = None
        self.buttons.register_actions(self.key_binds)

        self._canvas_sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self._canvas_sizer)

        # Tracks if an operation has been started and not finished.
        self._operation_running = False
        # This lock stops two threads from editing the world simultaneously
        # call run_operation to acquire it.
        self._edit_lock = RLock()

    def _init_opengl(self):
        super()._init_opengl()
        self._file_panel = FilePanel(self)
        self._canvas_sizer.AddSpacer(30)
        self._tool_sizer = ToolManagerSizer(self)
        self._canvas_sizer.Add(self._tool_sizer, 1, wx.EXPAND, 0)

    def bind_events(self):
        """Set up all events required to run.
        Note this will also bind subclass events."""
        self._tool_sizer.bind_events()
        # binding the tool events first will run them last so they can't accidentally block UI events.
        super().bind_events()
        self._file_panel.bind_events()
        self.Bind(EVT_EDIT_CLOSE, self._on_close)

    def enable(self):
        super().enable()
        self._tool_sizer.enable()
        self.PostSizeEvent()

    def disable(self):
        super().disable()
        self._tool_sizer.disable()

    def _on_close(self, _):
        close_level(self.world.level_path)

    def can_close(self) -> bool:
        return not self._operation_running

    @property
    def tools(self):
        return self._tool_sizer.tools

    @property
    def key_binds(self) -> KeybindGroup:
        config_ = CONFIG.get(EDIT_CONFIG_ID, {})
        user_keybinds = config_.get("user_keybinds", {})
        group = config_.get("keybind_group", DefaultKeybindGroupId)
        if group in user_keybinds:
            return user_keybinds[group]
        elif group in PresetKeybinds:
            return PresetKeybinds[group]
        else:
            return DefaultKeys

    def _deselect(self):
        # TODO: Re-implement this
        self._tool_sizer.enable_default_tool()

    def run_operation(
        self,
        operation: OperationType,
        title: str | None = None,
        msg="Running Operation",
        throw_exceptions=False,
        rollback_on_error: Optional[Callable[[], bool]] = None,
    ) -> OperationOutcome:
        """Run an operation against the open world and say what it did.

        The returned :class:`OperationOutcome` is the point of this function's
        signature.  It used to return the operation's own value on the path
        where nothing raised and ``None`` on the path where something did --
        and since most operations return ``None`` anyway, the two paths were
        indistinguishable.  Every caller that wrapped this in ``try``/``except``
        was therefore protecting itself from an exception that could not arrive,
        and every caller that carried on afterwards was assuming a write it had
        no evidence for.
        """
        title = preferences.load().display_name if title is None else title
        try:
            out = self._run_operation(operation, title, msg, True, rollback_on_error)
        except Exception as e:
            # ``Exception``, deliberately, and not ``BaseException``.
            #
            # ``KeyboardInterrupt``, ``SystemExit`` and ``GeneratorExit`` are not
            # the operation failing -- they are the interpreter being told to
            # stop.  Catching them here meant Ctrl+C during a long operation was
            # swallowed and the application carried on as though nothing had been
            # asked of it.  They travel on regardless of ``throw_exceptions``,
            # which is a question about the operation's own errors and cannot be
            # an answer about the interpreter's.
            #
            # ``MemoryError`` is **not** in that set, however much it reads like
            # it belongs there: Python derives it from ``Exception``, so it is
            # still contained here and still reported as an operation failure.
            # That is a fair outcome for a world edit that asked for more memory
            # than the machine had, and it is written down because the opposite
            # is easy to assume and impossible to notice.
            #
            # Nothing operational is lost by narrowing: every exception the
            # operation API defines -- ``OperationError``, ``OperationSuccessful``
            # and ``OperationSilentAbort`` -- descends from ``Exception`` through
            # ``BaseOperationException``, so cancelling and aborting are still
            # contained here exactly as before.
            if throw_exceptions:
                raise e
            return contained_outcome(e)

        # If there were no errors create an undo point
        def create_undo():
            yield 0, "Creating Undo Point"
            yield from self.create_undo_point_iter()

        try:
            self._run_operation(create_undo, title, msg, False)
        except Exception as e:
            # The operation itself already wrote the world, so this is not a
            # failed edit: it is an edit that cannot be undone.  Reporting it as
            # a failure would send the user looking for blocks that are there,
            # and reporting nothing at all is how the undo stack silently stops
            # matching the world.
            if throw_exceptions:
                raise e
            log.exception("The operation ran but its undo point could not be created")
            return OperationOutcome(
                ok=True,
                reason="no-undo-point",
                message=(
                    "The operation finished and the world was changed, but no undo "
                    f"point could be recorded for it: {e}"
                ),
                value=out,
                error=e,
            )

        return OperationOutcome(ok=True, value=out)

    def _run_operation(
        self,
        operation: OperationType,
        title: str,
        msg: str,
        cancelable: bool,
        rollback_on_error: Optional[Callable[[], bool]] = None,
    ) -> Any:
        with self._edit_lock:
            if self._operation_running:
                raise Exception(
                    "run_operation cannot be called from within itself. "
                    "This function has already been called by parent code so you cannot run it again"
                )
            self._operation_running = True

            try:
                self.renderer.disable_threads()

                style = (
                    wx.PD_APP_MODAL
                    | wx.PD_ELAPSED_TIME
                    | wx.PD_REMAINING_TIME
                    | wx.PD_AUTO_HIDE
                    | (wx.PD_CAN_ABORT * cancelable)
                )
                dialog = wx.ProgressDialog(
                    title,
                    msg,
                    maximum=10_000,
                    parent=self,
                    style=style,
                )
                dialog.Fit()

                # Set up a thread to run the actual operation
                op = OperationThread(operation, msg)
                # run the operation
                op.start()
                while op.is_alive():
                    op.join(0.1)
                    dialog.Update(
                        max(0, min(int(op.progress * 10_000), 9999)), op.message
                    )
                    wx.Yield()
                    if dialog.WasCancelled():
                        op.stop = True

                dialog.Destroy()
                wx.Yield()

                if op.error is not None:
                    if rollback_on_error is None:
                        should_rollback = True
                    else:
                        try:
                            should_rollback = bool(rollback_on_error())
                        except BaseException as rollback_error:
                            tb = "".join(
                                traceback.format_exception(
                                    type(rollback_error),
                                    rollback_error,
                                    rollback_error.__traceback__,
                                )
                            )
                            log.error(tb)
                            notify_exception(
                                self,
                                "Exception while deciding whether to rollback operation",
                                str(rollback_error),
                                tb,
                            )
                            should_rollback = False
                    if should_rollback:
                        self.world.restore_last_undo_point()

                    if isinstance(op.error, BaseLoudException):
                        msg = str(op.error)
                        if isinstance(op.error, OperationError):
                            msg = f"Error running operation: {msg}"
                        log.info(msg)
                        notify(self, "Operation failed", msg, severity="error")
                    elif isinstance(op.error, BaseSilentException):
                        pass
                    elif isinstance(op.error, BaseException):
                        tb = "".join(
                            traceback.format_exception(
                                type(op.error), op.error, op.error.__traceback__
                            )
                        )
                        log.error(tb)
                        notify_exception(
                            self,
                            "Exception while running operation",
                            str(op.error),
                            tb,
                        )

                if op.error is not None:
                    raise op.error
                return op.out
            finally:
                try:
                    self.renderer.enable_threads()
                    self.renderer.render_world.rebuild_changed()
                finally:
                    self._operation_running = False

    def create_undo_point(self, world=True, non_world=True):
        self.world.create_undo_point(world, non_world)
        wx.PostEvent(self, CreateUndoEvent())

    def create_undo_point_iter(
        self, world=True, non_world=True
    ) -> Generator[float, None, bool]:
        result = yield from self.world.create_undo_point_iter(world, non_world)
        wx.PostEvent(self, CreateUndoEvent())
        return result

    def undo(self):
        self.world.undo()
        self.renderer.render_world.rebuild_changed()
        wx.PostEvent(self, UndoEvent())

    def redo(self):
        self.world.redo()
        self.renderer.render_world.rebuild_changed()
        wx.PostEvent(self, RedoEvent())

    def _lift(
        self,
        operation: OperationType,
        rollback_on_error: Optional[Callable[[], bool]] = None,
    ) -> OperationOutcome:
        """Run a copy or a cut and say whether the clipboard really took it.

        **Why the cache is counted rather than the outcome believed.**  The
        stock ``copy`` operation finishes by raising ``OperationSilentAbort`` --
        on the path where it *succeeded*.  It is not failing; it is using the
        silent abort to tell ``run_operation`` not to record an undo point,
        because copying reads the world and never writes it.  So ``run_operation``
        answers ``ok=False, reason="aborted"`` for a copy that worked perfectly,
        and a caller that read that as "the copy did not happen" would refuse
        every clone in the application.  (It did, for one test run, and the real
        editor caught it.)

        The user cancelling the progress dialog raises the same class from the
        same place, so the token genuinely cannot tell the two apart.  What can
        is the clipboard: a copy that ran added a structure to it and a cancelled
        one did not.  That is the same shape as the paste bridge reading the
        world's undo depth -- ask the thing the operation was supposed to change,
        rather than the call that was supposed to change it.

        ``rollback_on_error`` is threaded through rather than fixed here
        because the two callers differ on exactly this point: a cut writes to
        the world and must be rolled back when it raises, and a copy never
        writes and must not be.
        """
        before = len(structure_cache)
        outcome = self.run_operation(operation, rollback_on_error=rollback_on_error)
        if outcome.failed:
            return outcome
        if len(structure_cache) > before:
            return OperationOutcome(ok=True, value=outcome.value)
        return OperationOutcome(
            ok=False,
            reason="nothing-copied",
            message=(
                outcome.message
                or "The selection was not added to the clipboard. It may have been "
                "cancelled before it finished."
            ),
            error=outcome.error,
        )

    def cut(self) -> OperationOutcome:
        """Lift the selection into the structure cache, and say whether it went.

        The outcome is returned rather than dropped because both callers here
        act on it: the Studio shell floats a copy for a rotation, and the Studio
        tool bridge hands one to the paste tool.  Neither can tell a cut that
        filled the clipboard from one that raised without being told, and a cut
        that did not fill it leaves the *previous* copy there for the paste tool
        to pick up -- so the user is handed blocks they never cut.
        """
        return self._lift(
            lambda: cut(self.world, self.dimension, self.selection.selection_group)
        )

    def copy(self) -> OperationOutcome:
        """Copy the selection into the structure cache; see :meth:`_lift`.

        **Why this one refuses the rollback.**  ``copy`` finishes by raising
        ``OperationSilentAbort``, and :meth:`_run_operation` answers every
        exception out of an operation with ``world.restore_last_undo_point()``
        -- which is right for an operation that was part-way through writing
        and wrong for one that never writes at all.

        What that rollback actually reached was not the world.  The level's one
        non-world history manager is this program's own
        :class:`~amulet_map_editor.programs.edit.api.selection.
        SelectionHistoryManager`, and restoring it unpacks its stored corners
        back through ``SelectionManager.set_selection_corners``, whose first
        act is ``self.changed = True``.  So pressing Ctrl+C on a settled
        selection left that flag set -- measured in a real editor: ``False``
        before, ``True`` after -- and that flag is precisely what decides
        whether the *next* undo point records a revision.  A read-only action
        was arming an undo point that undoes nothing.

        Inside the 400 ms before the selection's own deferred undo point fires
        it is worse than pointless: the value unpacked is then the *previous*
        committed selection, so the rollback would take away the box the user
        had just drawn and was copying.
        """
        return self._lift(
            lambda: copy(self.world, self.dimension, self.selection.selection_group),
            rollback_on_error=_copy_never_rolls_back,
        )

    def paste(self, structure: BaseLevel, dimension: Dimension):
        assert isinstance(
            structure, BaseLevel
        ), "Structure given is not a subclass of BaseLevel."
        assert (
            dimension in structure.dimensions
        ), "The requested dimension does not exist for this object."
        wx.PostEvent(
            self,
            ToolChangeEvent(
                tool="Paste", state={"structure": structure, "dimension": dimension}
            ),
        )

    def paste_from_cache(self):
        if structure_cache:
            self.paste(*structure_cache.get_structure())
        else:
            notify(
                self,
                "Paste unavailable",
                "A structure needs to be copied before one can be pasted.",
                severity="warning",
            )

    def delete(self) -> OperationOutcome:
        """Delete the selection; see :meth:`cut` for why the outcome comes back."""
        return self.run_operation(
            lambda: delete(self.world, self.dimension, self.selection.selection_group)
        )

    def goto(self):
        location = show_goto(self, *self.camera.location)
        if location:
            self.camera.location = location

    def select_all(self):
        all_chunk_coords = tuple(self.world.all_chunk_coords(self.dimension))
        if all_chunk_coords:
            min_x, min_z = max_x, max_z = all_chunk_coords[0]
            for x, z in all_chunk_coords:
                if x < min_x:
                    min_x = x
                elif x > max_x:
                    max_x = x
                if z < min_z:
                    min_z = z
                elif z > max_z:
                    max_z = z

            self.selection.selection_corners = [
                (
                    (
                        min_x * self.world.sub_chunk_size,
                        self.world.bounds(self.dimension).min[1],
                        min_z * self.world.sub_chunk_size,
                    ),
                    (
                        (max_x + 1) * self.world.sub_chunk_size,
                        self.world.bounds(self.dimension).max[1],
                        (max_z + 1) * self.world.sub_chunk_size,
                    ),
                )
            ]

        else:
            self.selection.selection_corners = []

    def save(self):
        def pre_save() -> Generator[OperationYieldType, None, Any]:
            yield 0, "Running Pre-Save Operations."
            pre_save_op = self.world.pre_save_operation()
            try:
                while True:
                    yield next(pre_save_op)
            except StopIteration as e:
                if e.value:
                    yield from self.create_undo_point_iter()
                else:
                    self.world.restore_last_undo_point()

        def save() -> Generator[OperationYieldType, None, Any]:
            yield 0, "Saving Chunks."
            for chunk_index, chunk_count in self.world.save_iter():
                yield chunk_index / chunk_count

        self._run_operation(
            pre_save, "Running Pre-Save Operations.", "Please wait.", False
        )
        self._run_operation(save, "Saving world.", "Please wait.", False)
        wx.PostEvent(self, SaveEvent())

    if sys.platform == "linux" and os.environ.get("XDG_SESSION_TYPE") == "wayland":

        def mask_gl(self) -> None:
            """
            Cut out the ares of the canvas intersecting the given objects.
            This must be called with an OpenGL context active.
            """
            windows = []
            if self._file_panel is not None:
                windows.extend(self._file_panel.windows())
            if self._tool_sizer is not None:
                windows.extend(self._tool_sizer.windows())
            glEnable(GL_SCISSOR_TEST)
            self_h = self.GetSize()[1]
            for window in windows:
                x, y = window.ClientToScreen(0, 0)
                w, h = window.GetSize()
                rel_x, rel_y = self.ScreenToClient((x, y))
                glScissor(rel_x, self_h - rel_y - h, w, h)
                glClearColor(0.0, 0.0, 0.0, 0.0)
                glClear(GL_COLOR_BUFFER_BIT)
            glDisable(GL_SCISSOR_TEST)

    else:

        def mask_gl(self) -> None:
            pass
