import sys
from pathlib import Path

# 1. 🌟 第一步：依然是雷打不动的路径修复（必须放在最顶部！）
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

# 2. 🌟 第二步：当路径修好后，安全地导入并对外暴露实例
from .calender_agent import calendar_agent
from .email_agent import email_agent
