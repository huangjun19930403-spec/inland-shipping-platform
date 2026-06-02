from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]

REVIER_SOURCE_CODE = "RIVER_SHAPEFILE_2026"
REVIER_GRAPH_VERSION_CODE = "NAV_GRAPH_REVIER_PROD_V1"
REVIER_GRAPH_SCOPE_CODE = "REVIER_PRODUCTION"
REVIER_SEED_PREFIX = "revier.prod"

SOURCE_LAYERS = (
    "rx",
    "rx8",
    "一级水系",
    "二级水系",
    "三级水系",
    "四级水系",
    "五级水系",
    "六级水系",
    "七级水系",
)

LAYER_CODE_OVERRIDES = {
    "rx": "RX_FULL_WATER_AREA",
    "一级水系": "WATER_LEVEL_1",
    "二级水系": "WATER_LEVEL_2",
    "三级水系": "WATER_LEVEL_3",
    "四级水系": "WATER_LEVEL_4",
    "五级水系": "WATER_LEVEL_5",
    "六级水系": "WATER_LEVEL_6",
    "七级水系": "WATER_LEVEL_7",
    "rx8": "WATER_LEVEL_8_OR_SUPPLEMENT",
}

RIVER_TYPES_ROUTING_ENABLED = {
    "PERENNIAL_DOUBLE_LINE_RIVER",
    "PERENNIAL_SINGLE_LINE_RIVER",
    "CANAL",
    "RIVER",
}

DEFAULT_SEED_DIR = PROJECT_ROOT / "scripts" / "seed_data" / "navigation"
DEFAULT_RUNTIME_DIR = PROJECT_ROOT / "runtime" / "navigation-production"

