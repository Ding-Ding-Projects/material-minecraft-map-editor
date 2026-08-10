from .context_manager import ContextManager
from .drawable import Drawable
from .thread_generator import ThreadedObject, ThreadedObjectContainer


def check_opengl(checked=False):
    try:
        import OpenGL.GL
    except ImportError:
        import platform

        if platform.system() == "Darwin" and platform.release() >= "20." and not checked:
            import ctypes.util

            real_find_library = ctypes.util.find_library

            def find_library(name):
                if name in {"OpenGL", "GLUT"}:  # add more names here if necessary
                    return f"/System/Library/Frameworks/{name}.framework/{name}"
                return real_find_library(name)

            ctypes.util.find_library = find_library
            check_opengl(True)
        else:
            raise
