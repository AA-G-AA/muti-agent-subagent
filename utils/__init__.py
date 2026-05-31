# utils/__init__.py
import sys
from pathlib import Path

# 自动定位到项目根目录并挂载
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)