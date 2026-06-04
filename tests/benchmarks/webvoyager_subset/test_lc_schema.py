"""诊断 LangChain 工具 schema 序列化问题."""
import os
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from agents.ui.tools import tools, tools_by_name
from langchain_core.messages import HumanMessage

# 1. 检查 tools 的 schema
for t in tools[:3]:
    print(f'\n=== {t.name} ===')
    print('args_schema:', t.args)
    print('description:', t.description[:80])

# 2. 拿一个工具, 调用 .invoke 触发 schema 校验
print('\n=== 模拟错误: 单个 tool 绑定, 不传 target ===')
try:
    from agents.ui.tools import click
    # 检查 schema
    import json
    if hasattr(click, 'args_schema') and click.args_schema:
        print('click args_schema fields:', list(click.args_schema.model_fields.keys()))
except Exception as e:
    print('err:', e)
