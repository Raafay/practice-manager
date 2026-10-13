from datetime import datetime, time, timedelta

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import manager, owner, portal_user, sign_in, staff
from apps.events.models import Notification
from apps.jobs import registry, services
from apps.jobs.models import JobLock, JobRun

pytestmark = pytest.mark.django_db

CALLS = []


def local(*args) -> datetime:
    return timezone.make_aware(datetime(*args))


@pytest.fixture
def test_jobs():
    saved = dict(registry.REGISTRY)
    CALLS.clear()

    @registry.register("test_ok", "Test job", registry.Daily(time(2, 0)))
    def ok(run):
        CALLS.append(run.pk)
        return {"done": 1, "message": "All fine"}

    @registry.register("test_fail", "Failing job", registry.Daily(time(2, 0)))
    def fail(run):
        raise RuntimeError("person@example.com broke it")

    @registry.register("test_nested", "Nested job", registry.Daily(time(2, 0)))
    def nested(run):
        CALLS.append(services.run_job("test_nested"))
        return {}

    # Seen long ago, so the schedule counts every slot.
    for name in ("test_ok", "test_fail", "test_nested"):
        lock = JobLock.objects.create(name=name)
        JobLock.objects.filter(pk=lock.pk).update(created_at=local(2020, 1, 1))
    yield
    registry.REGISTRY.clear()
    registry.REGISTRY.update(saved)


def test_schedules_give_the_last_slot():
    now = local(2026, 10, 13, 1, 30)  # a Tuesday
    assert registry.Daily(time(2, 0)).last_slot(now) == local(2026, 10, 12, 2, 0)
    assert registry.Daily(time(2, 0)).last_slot(local(2026, 10, 13, 2, 0)) == local(
        2026, 10, 13, 2, 0
    )
    assert registry.Every(15).last_slot(local(2026, 10, 13, 9, 44)) == local(2026, 10, 13, 9, 30)
    assert registry.Weekly(6, time(3, 0)).last_slot(now) == local(2026, 10, 11, 3, 0)
    assert registry.Monthly(1, time(4, 0)).last_slot(now) == local(2026, 10, 1, 4, 0)
    assert registry.Monthly(20, time(4, 0)).last_slot(now) == local(2026, 9, 20, 4, 0)


def test_a_job_runs_and_its_run_is_logged(test_jobs):
    run = services.run_job("test_ok")
    assert run.state == JobRun.State.DONE
    assert run.counts == {"done": 1}
    assert run.message == "All fine"
    assert run.finished_at is not None
    assert not services.is_running("test_ok")


def test_a_job_is_not_run_twice_at_once(test_jobs):
    run = services.run_job("test_nested")
    assert run.state == JobRun.State.DONE
    assert CALLS == [None]  # the inner attempt found the lock held
    assert JobRun.objects.filter(name="test_nested").count() == 1


def test_a_held_lock_blocks_another_worker_until_it_goes_stale(test_jobs):
    now = timezone.now()
    JobLock.objects.filter(name="test_ok").update(running_since=now)
    assert services.run_job("test_ok", now=now) is None
    later = now + services.STALE_LOCK + timedelta(minutes=1)
    assert services.run_job("test_ok", now=later).state == JobRun.State.DONE


def test_a_failing_job_is_recorded_notifies_the_owner_and_is_tried_again(test_jobs):
    boss = owner()
    other = manager()
    slot = local(2026, 10, 13, 2, 0)
    runs = services.run_due(now=slot + timedelta(minutes=1))
    failed = next(r for r in runs if r.name == "test_fail")
    assert failed.state == JobRun.State.FAILED
    assert failed.message == "Failed: RuntimeError"  # never the error text
    assert not services.is_running("test_fail")
    assert Notification.objects.filter(user=boss, message__contains="Failing job").exists()
    assert not Notification.objects.filter(user=other).exists()
    # Not again in the same slot...
    assert "test_fail" not in [j.name for j, _ in services.due_jobs(slot + timedelta(minutes=5))]
    # ...but again at the next one.
    next_slot = slot + timedelta(days=1)
    assert "test_fail" in [j.name for j, _ in services.due_jobs(next_slot)]


def test_a_slot_runs_once(test_jobs):
    now = local(2026, 10, 13, 2, 1)
    assert {r.name for r in services.run_due(now=now)} == {"test_ok", "test_fail", "test_nested"}
    assert services.run_due(now=now + timedelta(minutes=1)) == []


def test_a_new_job_waits_for_its_first_slot(test_jobs):
    JobLock.objects.filter(name="test_ok").delete()
    assert "test_ok" not in [j.name for j, _ in services.due_jobs(timezone.now())]


def test_run_now_is_picked_up_by_the_worker(test_jobs):
    boss = owner()
    services.request_run(boss, "test_ok")
    now = local(2026, 10, 13, 1, 0)
    JobRun.objects.create(
        name="test_ok", started_at=now, slot=local(2026, 10, 12, 2, 0), state="done"
    )
    runs = [r for r in services.run_due(now=now) if r.name == "test_ok"]
    assert len(runs) == 1
    assert runs[0].trigger == JobRun.Trigger.MANUAL
    assert runs[0].started_by == boss
    assert JobLock.objects.get(name="test_ok").requested_at is None


def test_run_job_command(test_jobs, capsys):
    call_command("run_job", "test_ok")
    assert "Done" in capsys.readouterr().out


def test_worker_once(test_jobs, capsys):
    call_command("worker", "--once")
    assert services.worker_last_seen() is not None


def test_the_jobs_page_is_owner_only(client, test_jobs):
    url = reverse("jobs:list")
    run_url = reverse("jobs:run_now", args=["test_ok"])
    assert "/login/" in client.get(url)["Location"]
    for person in (manager(), staff(), portal_user()):
        sign_in(client, person)
        assert client.get(url).status_code == 403
        assert client.post(run_url).status_code == 403
    sign_in(client, owner())
    response = client.get(url)
    assert response.status_code == 200
    assert "Test job" in response.content.decode()
    assert client.post(run_url).status_code == 302
    assert JobLock.objects.get(name="test_ok").requested_at is not None
    assert client.post(reverse("jobs:run_now", args=["nope"])).status_code == 404
