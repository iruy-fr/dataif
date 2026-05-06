from __future__ import annotations

import os
from dataclasses import dataclass

from dataif_pipelines.connectors.nilo_pecanha.powerbi_microdados import DEFAULT_POWERBI_MICRODADOS_URL


@dataclass(frozen=True)
class NiloConfig:
    endpoint: str
    timeout_seconds: int


def load_config() -> NiloConfig:
    return NiloConfig(
        endpoint=os.getenv("NILO_PECANHA_ENDPOINT", DEFAULT_POWERBI_MICRODADOS_URL),
        timeout_seconds=int(os.getenv("NILO_TIMEOUT_SECONDS", "60")),
    )
