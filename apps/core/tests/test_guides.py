"""The guides Stage 13 adds (spec 12 section 4) exist, and GO-LIVE has every line of section 5."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GUIDES = ["DEPLOY", "RUNBOOK", "BACKUPS", "SUBPROCESSORS", "STAFF-GUIDE", "GO-LIVE"]


def checklist_lines() -> list[str]:
    spec = (ROOT / "docs/specs/12-deploy-and-operations.md").read_text()
    section = spec.split("## 5. Go-live checklist", 1)[1].split("\n## ", 1)[0]
    return [line[2:].strip() for line in section.splitlines() if line.startswith("- ")]


@pytest.mark.parametrize("name", GUIDES)
def test_each_guide_exists(name):
    assert (ROOT / f"docs/{name}.md").stat().st_size > 500


def test_go_live_has_every_line_of_the_checklist_as_a_tick_box():
    golive = (ROOT / "docs/GO-LIVE.md").read_text()
    ticks = [line for line in golive.splitlines() if line.startswith("- [ ] ")]
    lines = checklist_lines()
    assert len(lines) == 23
    for line in lines:
        wanted = line.rstrip(".")
        assert any(wanted in tick for tick in ticks), line
