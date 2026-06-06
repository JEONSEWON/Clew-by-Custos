"""pytest conftest — 프로젝트 루트를 sys.path에 추가해 'eval', 'src.clew' 임포트 가능하게."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"

for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)
