from __future__ import annotations

import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2] / "services" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app import pnp_powerbi


def test_find_microdados_visual_accepts_exact_pivottable_match() -> None:
    visual_config = {
        "name": "visual-123",
        "singleVisual": {
            "visualType": "pivotTable",
            "projections": {
                "Rows": [{"queryRef": "Microdados.Ano Base", "active": True}],
                "Columns": [{"queryRef": "Microdados.Tipo de microdados", "active": True}],
                "Values": [{"queryRef": "Microdados.MicrodadosURL"}],
            },
            "prototypeQuery": {"Version": 2},
        },
    }
    metadata = {
        "exploration": {
            "sections": [
                {
                    "displayName": "Microdados da PNP",
                    "visualContainers": [{"config": json.dumps(visual_config)}],
                }
            ]
        }
    }

    visual = pnp_powerbi._find_microdados_visual(metadata)

    assert visual["name"] == "visual-123"
    assert visual["singleVisual"]["visualType"] == "pivotTable"


def test_find_microdados_visual_builds_fallback_when_config_is_missing() -> None:
    metadata = {
        "exploration": {
            "sections": [
                {
                    "displayName": "Microdados da PNP",
                    "visualContainers": [
                        {
                            "id": 10231332861,
                            "objectName": "05245e013098d1766963",
                        }
                    ],
                }
            ]
        }
    }

    visual = pnp_powerbi._find_microdados_visual(metadata)

    assert visual["name"] == "05245e013098d1766963"
    assert visual["singleVisual"]["visualType"] == "microdados_catalog_fallback"
    select_names = [item["Name"] for item in visual["singleVisual"]["prototypeQuery"]["Select"]]
    assert select_names == [
        "Microdados.MicrodadosURL",
        "Microdados.Ano Base",
        "Microdados.Tipo de microdados",
    ]
