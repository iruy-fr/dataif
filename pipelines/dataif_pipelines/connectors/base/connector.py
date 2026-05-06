from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from .types import NormalizedRecord, RawRecord, RunContext


class BaseConnector(ABC):
    @abstractmethod
    def connector_id(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def fetch(self, run_context: RunContext) -> list[RawRecord]:
        raise NotImplementedError

    @abstractmethod
    def normalize(self, raw_records: list[RawRecord], run_context: RunContext) -> list[NormalizedRecord]:
        raise NotImplementedError

    @abstractmethod
    def load_raw(self, normalized_records: list[NormalizedRecord], run_context: RunContext) -> int:
        raise NotImplementedError

    @abstractmethod
    def post_load_checks(self, run_id: str) -> dict[str, object]:
        raise NotImplementedError
