"""The current request's user and address, so model code can record events."""

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestInfo:
    user: object | None
    ip_address: str | None
    user_agent: str


_current: ContextVar[RequestInfo | None] = ContextVar("current_request_info", default=None)


def get_current() -> RequestInfo | None:
    return _current.get()


def set_current(info: RequestInfo | None):
    return _current.set(info)


def reset(token) -> None:
    _current.reset(token)
