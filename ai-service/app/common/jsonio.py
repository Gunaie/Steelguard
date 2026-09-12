"""大模型 JSON 输出的宽松解析工具(3.2 VL / 4.2 报告共用)

百炼兼容端点在长枚举输出时实测会出现: markdown 代码围栏、尾随逗号、
写完完整对象后重复片段并半截断尾。这里集中处理前两类(结构级损坏的
检测项打捞仍留在 vl_infer 业务层)。
"""
from __future__ import annotations

import json
import re


def strip_code_fence(content: str) -> str:
    """提取文本中第一个 {...} 片段; 没有则原样 strip 返回"""
    m = re.search(r"\{.*\}", content, flags=re.DOTALL)
    return m.group(0) if m else content.strip()


def loads_lenient_json(content: str) -> dict:
    """解析模型 JSON, 容忍: 代码围栏 / 尾随垃圾(raw_decode) / 尾随逗号"""
    text = strip_code_fence(content)
    decoder = json.JSONDecoder()
    candidates = [text, re.sub(r",\s*([}\]])", r"\1", text)]  # 原样 + 尾随逗号修复
    for cand in candidates:
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            pass
        try:
            # raw_decode: 容忍完整对象之后的尾随垃圾(模型偶发多吐一段文字)
            obj, _end = decoder.raw_decode(cand.lstrip())
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    raise json.JSONDecodeError("无法以任何宽松方式解析 JSON", text, 0)
