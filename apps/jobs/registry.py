"""Named background jobs and their schedules. See docs/specs/10-integrations.md section 2.

An app registers a job in its own `jobs.py`:

    @register("ch_sync", "Companies House sync", Daily(time(2, 0)))
    def ch_sync(run):
        ...
        return {"synced": 3}

The function gets the JobRun and returns a dict of counts (or None). It must be
safe to run twice. Schedules are in Europe/London time.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.utils import timezone


@dataclass(frozen=True)
class Every:
    minutes: int

    def last_slot(self, now: datetime) -> datetime:
        local = timezone.localtime(now)
        midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
        steps = int((local - midnight).total_seconds() // (self.minutes * 60))
        return midnight + timedelta(minutes=steps * self.minutes)

    def describe(self) -> str:
        return f"Every {self.minutes} minutes"


@dataclass(frozen=True)
class Daily:
    at: time

    def last_slot(self, now: datetime) -> datetime:
        local = timezone.localtime(now)
        slot = _at(local.date(), self.at)
        return slot if slot <= local else _at(local.date() - timedelta(days=1), self.at)

    def describe(self) -> str:
        return f"Every day at {self.at:%H:%M}"


WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@dataclass(frozen=True)
class Weekly:
    weekday: int  # 0 = Monday
    at: time

    def last_slot(self, now: datetime) -> datetime:
        local = timezone.localtime(now)
        day = local.date() - timedelta(days=(local.weekday() - self.weekday) % 7)
        slot = _at(day, self.at)
        return slot if slot <= local else _at(day - timedelta(days=7), self.at)

    def describe(self) -> str:
        return f"Every {WEEKDAYS[self.weekday]} at {self.at:%H:%M}"


@dataclass(frozen=True)
class Monthly:
    day: int  # 1 to 28, so every month has it
    at: time

    def last_slot(self, now: datetime) -> datetime:
        local = timezone.localtime(now)
        slot = _at(local.date().replace(day=self.day), self.at)
        if slot <= local:
            return slot
        first = local.date().replace(day=1) - timedelta(days=1)
        return _at(first.replace(day=self.day), self.at)

    def describe(self) -> str:
        return f"Monthly on day {self.day} at {self.at:%H:%M}"


def _at(day: date, at: time) -> datetime:
    return timezone.make_aware(datetime.combine(day, at))


Schedule = Every | Daily | Weekly | Monthly


@dataclass(frozen=True)
class Job:
    name: str
    label: str
    schedule: Schedule
    func: Callable
    description: str = ""
    # A job that fails quietly records its own trouble and never notifies the owner.
    notify_on_failure: bool = True


REGISTRY: dict[str, Job] = {}


def register(
    name: str,
    label: str,
    schedule: Schedule,
    *,
    description: str = "",
    notify_on_failure: bool = True,
):
    def decorator(func):
        REGISTRY[name] = Job(name, label, schedule, func, description, notify_on_failure)
        return func

    return decorator


def get(name: str) -> Job:
    try:
        return REGISTRY[name]
    except KeyError:
        raise KeyError(f"No job called {name!r}.") from None


def all_jobs() -> list[Job]:
    return sorted(REGISTRY.values(), key=lambda job: job.label)
