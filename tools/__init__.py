# tools/__init__.py
import sys
from pathlib import Path

# 自动定位到当前 __init__.py 的上一级，也就是你的项目根目录 muti_agent_subagent
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)  # 插到最前面，拥有最高优先级的搜索权