"""The workshop layout, in one place.

Section 4.1 lists it; these are the names it lists. They were spelled out in ten
places, which meant the layout was real in the document and incidental in the
code. Now a directory that the document names and the code cannot agree about is
one edit.
"""

from __future__ import annotations

from pathlib import Path

CONFIG = "config"
EVENTS = "events"
ARTIFACTS = "artifacts"
PROJECTS = "projects"
TOOLS = "tools"
SKILLS = "skills"
DOMAIN_PACKS = "domain-packs"

EVENT_LOG = "events.jsonl"
LESSONS = "lessons"

# Where a builder leaves a request. He writes here; the control host drains it into
# the event log. No listener, and nothing is lost: the file survives the process
# that wrote it, so a round that is cut off still said what it meant to say.



def config(root: Path) -> Path:      return root / CONFIG
def artifacts(root: Path) -> Path:   return root / ARTIFACTS
def event_log(root: Path) -> Path:   return root / EVENTS / EVENT_LOG
def events_dir(root: Path) -> Path:  return root / EVENTS
def projects(root: Path) -> Path:    return root / PROJECTS
