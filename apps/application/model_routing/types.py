# coding=utf-8
"""Pure routing contracts."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class OutputContract:
    required_fields: tuple[str, ...] = ()
    citation_field: str = ''
    evidence_reference: tuple[str, ...] = ()

    @property
    def enabled(self):
        return bool(self.required_fields or self.citation_field)


@dataclass(frozen=True)
class RoutingPolicy:
    enabled: bool = False
    low: dict = field(default_factory=dict)
    high: dict = field(default_factory=dict)
    contract: OutputContract = field(default_factory=OutputContract)
    timeout: int = 60
    buffer_bytes: int = 1048576


@dataclass(frozen=True)
class RouteDecision:
    role: str
    rule_id: str
    reason: str
    rule_version: str = '1'


class RoutingError(ValueError):
    """Only safe, stable reason codes cross the node boundary."""
