"""factory-boy factories that build row dicts for the ocdu test database.

These are plain (non-Django) factories: each call returns a ``dict`` shaped for
the corresponding SQLite table, which tests insert with ``helpers.insert``.
"""

from __future__ import annotations
import factory

BASE_TIME = 1_700_000_000_000
WORK_DIR = "/work/project"

class ProjectFactory(factory.Factory):
    """Build a ``project`` row."""

    class Meta:
        model = dict

    id = factory.Sequence(lambda n: f"prj{n}")
    worktree = "/work"
    vcs = "git"
    name = factory.Sequence(lambda n: f"project-{n}")
    time_created = BASE_TIME
    time_updated = BASE_TIME
    sandboxes = "[]"

class SessionFactory(factory.Factory):
    """Build a ``session`` row."""

    class Meta:
        model = dict

    id = factory.Sequence(lambda n: f"ses{n}")
    project_id = "prj0"
    parent_id = None
    slug = factory.Sequence(lambda n: f"slug-{n}")
    directory = WORK_DIR
    title = factory.Sequence(lambda n: f"Session {n}")
    version = "1.0.0"
    time_created = BASE_TIME
    time_updated = BASE_TIME
    path = ""
    agent = "build"
    model = None
    cost = 0.0
    tokens_input = 0
    tokens_output = 0
    tokens_reasoning = 0

class MessageFactory(factory.Factory):
    """Build a ``message`` row."""

    class Meta:
        model = dict

    id = factory.Sequence(lambda n: f"msg{n}")
    session_id = "ses0"
    time_created = BASE_TIME
    time_updated = BASE_TIME
    data = '{"role": "user"}'

class PartFactory(factory.Factory):
    """Build a ``part`` row."""

    class Meta:
        model = dict

    id = factory.Sequence(lambda n: f"prt{n}")
    message_id = "msg0"
    session_id = "ses0"
    time_created = BASE_TIME
    time_updated = BASE_TIME
    data = '{"type": "text", "text": "hello"}'

class SessionMessageFactory(factory.Factory):
    """Build a ``session_message`` row."""

    class Meta:
        model = dict

    id = factory.Sequence(lambda n: f"sm{n}")
    session_id = "ses0"
    type = "compaction"
    time_created = BASE_TIME
    time_updated = BASE_TIME
    data = "{}"
    seq = factory.Sequence(lambda n: n)

class TodoFactory(factory.Factory):
    """Build a ``todo`` row."""

    class Meta:
        model = dict

    session_id = "ses0"
    content = factory.Sequence(lambda n: f"task {n}")
    status = "pending"
    priority = "medium"
    position = factory.Sequence(lambda n: n)
    time_created = BASE_TIME
    time_updated = BASE_TIME

class EventFactory(factory.Factory):
    """Build an ``event`` row."""

    class Meta:
        model = dict

    id = factory.Sequence(lambda n: f"evt{n}")
    aggregate_id = "ses0"
    seq = factory.Sequence(lambda n: n)
    type = "message.updated"
    data = '{"value": 1}'

class EventSequenceFactory(factory.Factory):
    """Build an ``event_sequence`` row."""

    class Meta:
        model = dict

    aggregate_id = factory.Sequence(lambda n: f"ses{n}")
    seq = 1
    owner_id = None
