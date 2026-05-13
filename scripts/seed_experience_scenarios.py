"""Round 11 local-demo experience scenario seed entrypoint."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.experience_seed.main import seed_experience_scenarios


if __name__ == "__main__":
    asyncio.run(seed_experience_scenarios())
