"""Process-bounded regular-expression search shared by every search field."""

from __future__ import annotations

from dataclasses import dataclass
import multiprocessing
from multiprocessing.connection import Connection
import pickle
import re
import threading
import time
from typing import Callable, List, Optional, Pattern, Sequence, Tuple

MAX_PATTERN_LENGTH = 4096
MAX_SAMPLE_LENGTH = 100_000
MAX_BATCH_ITEMS = 4096
MAX_CAPTURE_MATCHES = 200
MAX_RESULT_TEXT_LENGTH = 32_768
MAX_RESULT_PAYLOAD_BYTES = 131_072
SUPPORTED_FLAGS = re.IGNORECASE | re.MULTILINE | re.DOTALL
DEFAULT_TIMEOUT_SECONDS = 0.75
DEFAULT_DEBOUNCE_SECONDS = 0.18
_NESTED_QUANTIFIER = re.compile(r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)[+*{]")


@dataclass(frozen=True)
class RegexResult:
    valid: bool
    error: Optional[str] = None
    matches: Tuple[str, ...] = ()
    groups: Tuple[Tuple[Optional[str], ...], ...] = ()
    matched_indices: Tuple[int, ...] = ()
    first_matches: Tuple[str, ...] = ()
    first_spans: Tuple[Tuple[int, int], ...] = ()
    timed_out: bool = False
    truncated: bool = False


@dataclass(frozen=True)
class RegexEvaluationRequest:
    """A bounded, pickle-safe request sent to one disposable worker."""

    pattern: str
    flags: int = 0
    regex_enabled: bool = False
    values: Tuple[str, ...] = ()
    capture_matches: bool = False


class RegexBuilder:
    """Build Python ``re`` requests without running them on a UI thread."""

    def __init__(self, pattern: str = "", flags: int = 0, regex_enabled: bool = False):
        self.pattern = pattern
        self.flags = flags
        self.regex_enabled = regex_enabled

    def compile(self) -> Pattern[str]:
        """Compile locally for non-UI code that explicitly owns that boundary."""

        if len(self.pattern) > MAX_PATTERN_LENGTH:
            raise ValueError(f"Pattern is limited to {MAX_PATTERN_LENGTH} characters")
        if self.flags & ~SUPPORTED_FLAGS:
            raise ValueError("Unsupported regular-expression flags")
        if self.regex_enabled and _NESTED_QUANTIFIER.search(self.pattern):
            raise ValueError(
                "Nested quantifiers are disabled to protect the UI from catastrophic backtracking"
            )
        return re.compile(
            self.pattern if self.regex_enabled else re.escape(self.pattern), self.flags
        )

    def request(
        self, values: Sequence[str] = (), *, capture_matches: bool = False
    ) -> RegexEvaluationRequest:
        return RegexEvaluationRequest(
            self.pattern,
            self.flags,
            self.regex_enabled,
            tuple(values),
            capture_matches,
        )

    def validate(self, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> RegexResult:
        return evaluate_regex_bounded(self.request(), timeout=timeout)

    def evaluate(
        self, sample: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS
    ) -> RegexResult:
        return evaluate_regex_bounded(
            self.request((sample,), capture_matches=True), timeout=timeout
        )

    def search(
        self, values: List[str], *, timeout: float = DEFAULT_TIMEOUT_SECONDS
    ) -> List[str]:
        """Return matching values while preserving source order and a hard timeout."""

        result = evaluate_regex_bounded(self.request(values), timeout=timeout)
        if result.timed_out:
            raise TimeoutError(
                result.error or "Regular-expression evaluation timed out"
            )
        if not result.valid:
            raise ValueError(result.error or "Invalid regular expression")
        return [values[index] for index in result.matched_indices]


def plain_text_match_indices(
    values: Sequence[str], query: str, *, ignore_case: bool = False
) -> Tuple[int, ...]:
    """Match bounded literals without invoking the regex engine or a worker."""

    if len(query) > MAX_PATTERN_LENGTH:
        raise ValueError(f"Pattern is limited to {MAX_PATTERN_LENGTH} characters")
    if len(values) > MAX_BATCH_ITEMS:
        raise ValueError(f"Search is limited to {MAX_BATCH_ITEMS} values")
    if sum(len(value) for value in values) > MAX_SAMPLE_LENGTH:
        raise ValueError(f"Sample is limited to {MAX_SAMPLE_LENGTH} characters")
    needle = query.casefold() if ignore_case else query
    return tuple(
        index
        for index, value in enumerate(values)
        if needle in (value.casefold() if ignore_case else value)
    )


def has_top_level_alternation(pattern: str) -> bool:
    """Return whether ``pattern`` has an unescaped ``|`` outside groups/classes."""

    escaped = False
    in_class = False
    depth = 0
    for character in pattern:
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if in_class:
            if character == "]":
                in_class = False
            continue
        if character == "[":
            in_class = True
        elif character == "(":
            depth += 1
        elif character == ")" and depth:
            depth -= 1
        elif character == "|" and depth == 0:
            return True
    return False


def _validate_request(request: RegexEvaluationRequest) -> Optional[RegexResult]:
    if len(request.pattern) > MAX_PATTERN_LENGTH:
        return RegexResult(
            False, f"Pattern is limited to {MAX_PATTERN_LENGTH} characters"
        )
    if len(request.values) > MAX_BATCH_ITEMS:
        return RegexResult(False, f"Search is limited to {MAX_BATCH_ITEMS} values")
    if sum(len(value) for value in request.values) > MAX_SAMPLE_LENGTH:
        return RegexResult(
            False, f"Sample is limited to {MAX_SAMPLE_LENGTH} characters"
        )
    if request.capture_matches and len(request.values) > 1:
        return RegexResult(False, "Capture feedback accepts one sample at a time")
    return None


def _evaluate_regex_in_worker(request: RegexEvaluationRequest) -> RegexResult:
    """Evaluate inside the disposable worker process only."""

    invalid = _validate_request(request)
    if invalid is not None:
        return invalid
    try:
        compiled = RegexBuilder(
            request.pattern, request.flags, request.regex_enabled
        ).compile()
        if request.capture_matches:
            sample = request.values[0] if request.values else ""
            matches = []
            groups = []
            truncated = False
            result_text_length = 0
            for index, match in enumerate(compiled.finditer(sample)):
                if index >= MAX_CAPTURE_MATCHES:
                    truncated = True
                    break
                match_text = match.group(0)
                match_groups = tuple(match.groups())
                item_text_length = len(match_text) + sum(
                    len(group) for group in match_groups if group is not None
                )
                if result_text_length + item_text_length > MAX_RESULT_TEXT_LENGTH:
                    truncated = True
                    break
                matches.append(match_text)
                groups.append(match_groups)
                result_text_length += item_text_length
            return _bound_result_payload(
                RegexResult(
                    True,
                    matches=tuple(matches),
                    groups=tuple(groups),
                    truncated=truncated,
                )
            )

        matched_indices = []
        first_matches = []
        first_spans = []
        result_text_length = 0
        truncated = False
        for index, value in enumerate(request.values):
            match = compiled.search(value)
            if match is not None:
                matched_indices.append(index)
                first_match = match.group(0)
                if result_text_length + len(first_match) > MAX_RESULT_TEXT_LENGTH:
                    first_match = ""
                    truncated = True
                else:
                    result_text_length += len(first_match)
                first_matches.append(first_match)
                first_spans.append(match.span())
        return _bound_result_payload(
            RegexResult(
                True,
                matched_indices=tuple(matched_indices),
                first_matches=tuple(first_matches),
                first_spans=tuple(first_spans),
                truncated=truncated,
            )
        )
    except (re.error, ValueError) as exc:
        return RegexResult(False, str(exc))


def _bound_result_payload(result: RegexResult) -> RegexResult:
    """Keep every worker response below one deterministic serialized budget."""

    candidate = RegexResult(
        result.valid,
        (result.error or "")[:1024] or None,
        result.matches,
        result.groups,
        result.matched_indices,
        result.first_matches,
        result.first_spans,
        result.timed_out,
        result.truncated,
    )
    if len(pickle.dumps(candidate, protocol=pickle.HIGHEST_PROTOCOL)) <= (
        MAX_RESULT_PAYLOAD_BYTES
    ):
        return candidate
    count = len(candidate.matched_indices)
    while count:
        count //= 2
        candidate = RegexResult(
            candidate.valid,
            candidate.error,
            candidate.matches,
            candidate.groups,
            candidate.matched_indices[:count],
            candidate.first_matches[:count],
            candidate.first_spans[:count],
            candidate.timed_out,
            True,
        )
        if len(pickle.dumps(candidate, protocol=pickle.HIGHEST_PROTOCOL)) <= (
            MAX_RESULT_PAYLOAD_BYTES
        ):
            return candidate
    return RegexResult(
        candidate.valid,
        candidate.error,
        timed_out=candidate.timed_out,
        truncated=True,
    )


def _regex_worker(connection: Connection, request: RegexEvaluationRequest) -> None:
    try:
        connection.send(_evaluate_regex_in_worker(request))
    except BaseException as exc:  # pragma: no cover - worker crash boundary
        try:
            connection.send(RegexResult(False, f"Regex worker failed: {exc}"))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        _close_connection(connection)


def _close_connection(connection: Optional[Connection]) -> None:
    if connection is None:
        return
    try:
        connection.close()
    except (OSError, RuntimeError, ValueError):
        return


def _new_worker(
    request: RegexEvaluationRequest,
) -> Tuple[multiprocessing.Process, Connection, Connection]:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    try:
        process = context.Process(target=_regex_worker, args=(sender, request))
        process.daemon = True
    except BaseException:
        _close_connection(receiver)
        _close_connection(sender)
        raise
    return process, receiver, sender


def _stop_worker(process: multiprocessing.Process) -> None:
    """Best-effort termination that never prevents surrounding cleanup."""

    try:
        if process.pid is None:
            return
        if process.is_alive():
            process.terminate()
        process.join(0.5)
        if process.is_alive():
            process.kill()
            process.join(0.5)
    except (OSError, RuntimeError, ValueError):
        return


def _worker_failure(message: str) -> RegexResult:
    return _bound_result_payload(RegexResult(False, message))


def evaluate_regex_bounded(
    request: RegexEvaluationRequest, *, timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> RegexResult:
    """Synchronously wait on a terminable worker, never on Python ``re`` itself."""

    invalid = _validate_request(request)
    if invalid is not None:
        return _bound_result_payload(invalid)
    process: Optional[multiprocessing.Process] = None
    receiver: Optional[Connection] = None
    sender: Optional[Connection] = None
    try:
        try:
            process, receiver, sender = _new_worker(request)
        except (OSError, RuntimeError, ValueError) as exc:
            return _worker_failure(f"Regex worker could not be created: {exc}")
        process.start()
        _close_connection(sender)
        sender = None
        if receiver.poll(max(0.05, timeout)):
            try:
                result = receiver.recv()
            except (EOFError, OSError) as exc:
                return _worker_failure(f"Regex worker exited without a result: {exc}")
            return _bound_result_payload(result)
        return _bound_result_payload(
            RegexResult(
                False,
                "Regular-expression evaluation timed out",
                timed_out=True,
            )
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return _worker_failure(f"Regex worker failed: {exc}")
    finally:
        if sender is not None:
            _close_connection(sender)
        if receiver is not None:
            _close_connection(receiver)
        if process is not None:
            _stop_worker(process)


class RegexEvaluationController:
    """Debounce UI requests and terminate superseded or timed-out workers."""

    def __init__(
        self,
        dispatcher: Callable[[Callable[[], None]], None],
        *,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        failure_message: str = "Regular-expression evaluation failed",
        timeout_message: str = "Regular-expression evaluation timed out",
    ) -> None:
        self._dispatcher = dispatcher
        self._debounce_seconds = max(0.0, debounce_seconds)
        self._timeout_seconds = max(0.05, timeout_seconds)
        self._failure_message = failure_message[:1024]
        self._timeout_message = timeout_message[:1024]
        self._lock = threading.RLock()
        self._generation = 0
        self._closed = False
        self._timer: Optional[threading.Timer] = None
        self._active: Optional[Tuple[int, multiprocessing.Process, Connection]] = None
        self._running_generations: set[int] = set()

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def active_worker_pid(self) -> Optional[int]:
        with self._lock:
            if self._active is None:
                return None
            return self._active[1].pid

    @property
    def is_idle(self) -> bool:
        with self._lock:
            timer_running = self._timer is not None and self._timer.is_alive()
            return (
                not timer_running
                and self._active is None
                and not self._running_generations
            )

    def submit(
        self,
        request: RegexEvaluationRequest,
        callback: Callable[[RegexResult], None],
        *,
        immediate: bool = False,
    ) -> int:
        with self._lock:
            if self._closed:
                raise RuntimeError("Regex evaluation controller is closed")
            self._generation += 1
            generation = self._generation
            if self._timer is not None:
                self._timer.cancel()
            self._cancel_active_locked()
            invalid = _validate_request(request)
            timer = threading.Timer(
                0.0 if immediate else self._debounce_seconds,
                (
                    self._deliver_preflight
                    if invalid is not None
                    else self._run_generation
                ),
                (
                    (generation, _bound_result_payload(invalid), callback)
                    if invalid is not None
                    else (generation, request, callback)
                ),
            )
            timer.daemon = True
            self._timer = timer
            timer.start()
            return generation

    def _deliver_preflight(
        self,
        generation: int,
        result: RegexResult,
        callback: Callable[[RegexResult], None],
    ) -> None:
        with self._lock:
            deliver = not self._closed and generation == self._generation
        if deliver:
            self._dispatch_if_current(generation, result, callback)

    def _dispatch_if_current(
        self,
        generation: int,
        result: RegexResult,
        callback: Callable[[RegexResult], None],
    ) -> None:
        """Recheck ownership when the UI dispatcher actually runs the callback."""

        def deliver() -> None:
            with self._lock:
                if self._closed or generation != self._generation:
                    return
                callback(result)

        self._dispatcher(deliver)

    def cancel(self) -> None:
        """Invalidate pending work and terminate the active disposable worker."""

        with self._lock:
            if self._closed:
                return
            self._generation += 1
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._cancel_active_locked()

    def _cancel_active_locked(self) -> None:
        if self._active is None:
            return
        _generation, process, receiver = self._active
        _close_connection(receiver)
        if process.pid is not None and process.is_alive():
            process.terminate()
        self._active = None

    def _run_generation(
        self,
        generation: int,
        request: RegexEvaluationRequest,
        callback: Callable[[RegexResult], None],
    ) -> None:
        with self._lock:
            if self._closed or generation != self._generation:
                return
            self._running_generations.add(generation)

        process: Optional[multiprocessing.Process] = None
        receiver: Optional[Connection] = None
        sender: Optional[Connection] = None
        result: Optional[RegexResult] = None
        try:
            process, receiver, sender = _new_worker(request)
            process.start()
            _close_connection(sender)
            sender = None
            with self._lock:
                if self._closed or generation != self._generation:
                    _stop_worker(process)
                    _close_connection(sender)
                    _close_connection(receiver)
                    return
                self._active = (generation, process, receiver)
            try:
                if receiver.poll(self._timeout_seconds):
                    try:
                        result = receiver.recv()
                    except (EOFError, OSError):
                        result = _worker_failure(self._failure_message)
                else:
                    result = _bound_result_payload(
                        RegexResult(
                            False,
                            self._timeout_message,
                            timed_out=True,
                        )
                    )
            except (EOFError, OSError, RuntimeError, ValueError):
                result = _worker_failure(self._failure_message)
        except (OSError, RuntimeError, ValueError):
            result = _worker_failure(self._failure_message)
        finally:
            if sender is not None:
                _close_connection(sender)
            if receiver is not None:
                _close_connection(receiver)
            if process is not None:
                _stop_worker(process)
            with self._lock:
                if self._active is not None and self._active[0] == generation:
                    self._active = None
                self._running_generations.discard(generation)
                if self._timer is threading.current_thread():
                    self._timer = None

        with self._lock:
            deliver = (
                result is not None
                and not self._closed
                and generation == self._generation
            )
        if deliver:
            self._dispatch_if_current(generation, result, callback)

    def wait_for_idle(self, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            if self.is_idle:
                return True
            time.sleep(0.01)
        return self.is_idle

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._generation += 1
            timer = self._timer
            self._timer = None
            if timer is not None:
                timer.cancel()
            self._cancel_active_locked()
        if timer is not None and timer is not threading.current_thread():
            timer.join(1.0)
