# coding=utf-8
from dataclasses import dataclass


class RecoveryConflict(Exception):
    pass


class RecoveryDenied(Exception):
    pass


@dataclass(frozen=True)
class Identity:
    application_id: str
    chat_user_id: str
    chat_user_type: str


@dataclass(frozen=True)
class Claim:
    run_id: str
    generation: int
    acquired: bool = True
