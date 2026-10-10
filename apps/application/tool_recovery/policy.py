# coding=utf-8
"""Conservative retry decisions; error text is never a safety signal."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RecoveryPolicy:
    timeout: int = 10
    retries: int = 2
    mode: str = 'unknown'
    retry_errors: tuple = ('timeout', 'transient')
    key_field: str = ''
    retention_hours: int = 24

    @classmethod
    def parse(cls, value):
        value = {} if value is None else value
        if not isinstance(value, dict) or set(value) - set(cls.__dataclass_fields__):
            raise ValueError('Invalid recovery policy')
        p = cls(**value)
        for v, lo, hi in ((p.timeout, 1, 120), (p.retries, 0, 5), (p.retention_hours, 1, 720)):
            if type(v) is not int or not lo <= v <= hi:
                raise ValueError('Recovery limit out of range')
        if p.mode not in {'unknown', 'read_only', 'idempotent_write', 'unprotected_write'}:
            raise ValueError('Invalid tool side effect mode')
        if not isinstance(p.retry_errors, (list, tuple)) or set(p.retry_errors) - {'timeout', 'transient'}:
            raise ValueError('Only transient errors and timeouts can retry')
        if not isinstance(p.key_field, str) or (p.mode == 'idempotent_write' and not p.key_field.isidentifier()):
            raise ValueError('Idempotent writes require an explicit tool key parameter')
        return p


def classify_error(error):
    try:
        import httpx
        if isinstance(error, httpx.TimeoutException):
            return 'timeout'
        if isinstance(error, httpx.NetworkError):
            return 'transient'
    except ImportError:
        pass
    # SDK task groups can wrap transport failures; mixed failures stay conservative.
    children = getattr(error, 'exceptions', None)
    if isinstance(children, tuple) and children:
        kinds = {classify_error(child) for child in children}
        return next(iter(kinds)) if len(kinds) == 1 else 'unknown'
    if isinstance(error, TimeoutError):
        return 'timeout'
    if isinstance(error, PermissionError):
        return 'permission'
    if isinstance(error, (ValueError, TypeError)):
        return 'parameters'
    if isinstance(error, (ConnectionError, EOFError)):
        return 'transient'
    # HTTP statuses are structured, but optional dependencies stay out of pure policy.
    response = getattr(error, 'response', None)
    status = getattr(response, 'status_code', None)
    if status in (401, 403):
        return 'permission'
    if status in (408, 429, 502, 503, 504):
        return 'transient'
    if isinstance(status, int) and 400 <= status < 500:
        return 'parameters'
    return 'unknown'


def can_retry(policy, error_type, attempt_number):
    return (policy.mode in {'read_only', 'idempotent_write'} and
            error_type in policy.retry_errors and attempt_number <= policy.retries)


def failure_status(policy, error_type):
    if policy.mode in {'unknown', 'unprotected_write'} and error_type in {'timeout', 'transient', 'unknown'}:
        return 'outcome_unknown'
    return 'failed'
