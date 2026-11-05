"""CPython compatibility shim for MicroPython decorators."""


def native(func):
    """No-op replacement for micropython.native."""
    return func
