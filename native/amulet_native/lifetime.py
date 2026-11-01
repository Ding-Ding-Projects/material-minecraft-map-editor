"""Explicit native ownership teardown after the application event loop exits."""

from shiboken6 import delete, isValid


def destroy_presentation(engine, backend):
    """Keep context properties alive through every QML destruction callback.

    Do not clear the context property: that would invalidate live bindings.
    Application close already waits for the controller's child to stop.
    Synchronous deletion is intentional here because the main event loop has
    exited and a deleteLater request may otherwise never be processed.
    """
    if isValid(backend):
        backend.assert_stopped()
    if isValid(engine):
        for root in engine.rootObjects():
            if isValid(root):
                delete(root)
        delete(engine)
    if isValid(backend):
        delete(backend)
