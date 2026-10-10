# coding=utf-8
"""Contracts shared by memory storage, extraction and model context selection."""
from dataclasses import dataclass, field


@dataclass
class MemorySnapshot:
    facts: list = field(default_factory=list)
    version: int = 0
    generation: int = 0


@dataclass
class Operation:
    action: str
    entity: str = ''
    attribute: str = ''
    value: str = ''
    target: str = ''
    quote: str = ''
    source: str = ''
    explicit: bool = False
    references: list = field(default_factory=list)


@dataclass
class ChangeSet:
    snapshot: MemorySnapshot
    changes: list = field(default_factory=list)
    rejected: list = field(default_factory=list)


@dataclass(frozen=True)
class Identity:
    application_id: str
    chat_user_id: str
    chat_user_type: str


@dataclass
class TurnTicket:
    event_id: str
    chat_id: str
    version: int
    generation: int
    status: str
    snapshot: MemorySnapshot


@dataclass
class ExtractionResult:
    operations: list = field(default_factory=list)
    status: str = 'ok'
    usage: dict = field(default_factory=dict)


@dataclass
class ContextSelection:
    facts: list = field(default_factory=list)
    history: list = field(default_factory=list)
    block: str = ''
    excluded: list = field(default_factory=list)
    tokens: int = 0
    counting: str = 'model_estimate'
