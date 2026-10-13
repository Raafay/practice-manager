"""Activity log. Import `record` and `notify` from here: `from apps import events`."""


def record(*args, **kwargs):
    from .services import record as _record

    return _record(*args, **kwargs)


def notify(*args, **kwargs):
    from .services import notify as _notify

    return _notify(*args, **kwargs)
