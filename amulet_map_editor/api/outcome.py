"""One shape for "what did that actually do", shared by everything that says it.

A function that changes the world has three possible honest answers and only
two of them are a boolean.  It ran and did what it said; it ran and did
nothing; it stopped on an error that somebody else already contained.  A bare
``None`` collapses the last two into the first, which is how a caller comes to
report a success it never saw -- and a bare ``False`` collapses them into each
other, which is how "the tool went away" and "your blocks were not written"
become the same answer.

:class:`Outcome` is the one convention for saying which of the three happened.
It lives here, rather than beside the first caller that needed it, so the next
one does not invent a second convention with the same fields in a different
order.

``bool(outcome)`` is ``ok``, so a caller that only wants a yes or no reads it
as one and an existing ``if not do_the_thing():`` keeps working.  A caller that
has to tell the user *what* went wrong reads ``title`` and ``message``, which
are already in the reader's language and tone where the producer localises
them, and ``reason``, which is a stable token so a surface can decide what to
do without matching on prose.

``reason`` is empty on success.  Its failure tokens are **defined by the
function returning it** and documented there: what stops a paste is not what
stops a world operation, and one shared enumeration would either be wrong for
both or grow into a list nobody reads.  What is shared is the rule -- a token
is a stable identifier, never a sentence, and never the message.

Nothing here imports wx, ``amulet``, or anything with a display, so a test, a
build step or a documentation pass can read the contract without a world.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Outcome"]


@dataclass(frozen=True)
class Outcome:
    """What one attempt to change something actually did.

    ``ok`` says whether the thing the caller asked for happened.  ``reason`` is
    the producer's own stable token for *why not* -- empty on success, and
    sometimes non-empty on success where the caller still wants the detail.
    ``title`` and ``message`` are for showing; ``reason`` is for deciding.
    """

    ok: bool
    reason: str = ""
    title: str = ""
    message: str = ""

    def __bool__(self) -> bool:
        return bool(self.ok)
