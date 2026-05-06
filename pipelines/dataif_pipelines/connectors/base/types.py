from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class RunContext:
    run_id: str
    started_at: datetime
    source_url: str


RawRecord = dict[str, Any]
NormalizedRecord = dict[str, Any]
