"""Qwen-VL 零样本缺陷检测器(阿里云百炼 OpenAI 兼容协议, 预留 Ollama 兜底)

设计要点:
- 零样本: 不做任何视觉样本微调, 靠 6 类缺陷的文字定义让 VLM 直接出框
- 纯 httpx 调用 /chat/completions, dashscope 与 ollama 仅 base_url/key/model 不同
- 输出结构与 YOLO 对齐(pixel 坐标 + 字母序 class_id), 另带 token 用量做成本对决
- parse_vl_content / canonical_class 为纯函数, 独立可单测
- 密钥只从服务端 settings 读取, 永不进前端
"""
from __future__ import annotations

import base64
import json
import re
import time
from typing import Any

import httpx

from app.common.jsonio import loads_lenient_json, strip_code_fence
from app.config import settings
from app.inference.yolo_infer import YOLO_CLASSES, CLASS_NAME_CN, decode_image

# ---------- 零样本 prompt ----------

CLASS_SPEC = """1. crazing: 多条相互交错、分叉的细裂纹/龟裂网状纹理
2. inclusion: 嵌入表面的不规则点状或条状异物、夹渣, 颜色通常偏暗
3. patches: 成片、形状不规则的平坦色斑区域, 面积一般较大
4. pitted_surface: 表面密集分布的小凹坑/麻点, 呈粗糙桔皮状
5. rolled-in_scale: 块状或条状鳞片状氧化皮压入痕迹, 常沿轧制方向延伸
6. scratches: 细长、近似直线的线性机械划伤, 方向较一致"""

SYSTEM_PROMPT = (
    "你是一名热轧钢带表面质量检测专家, 执行零样本目标检测任务。"
    "只依据图片中客观可见的缺陷作答, 不要臆测; 忽略正常的光照不均与轧制纹理。"
)

USER_PROMPT_TEMPLATE = """对这张钢材表面灰度图做目标检测: 找出图中每一处缺陷区域, 逐一为【每一个独立的缺陷区域】输出一个紧贴其边缘的检测框。

缺陷类别只能是以下 6 种, class 字段必须原样使用英文标识:
{class_spec}

类别区分要点:
- crazing 是细长线条交织成的网状裂纹(线状), 不是整片粗糙面
- pitted_surface 是密集小点凹坑构成的粗糙面(面状), 没有长线
- inclusion 是小而暗的点状/细条状异物, 边界清楚
- patches 是色调均匀、形状不规则的平坦色斑, 面积较大但仍是图中局部区域
- rolled-in_scale 是沿轧制方向延伸的条状/羽毛状鳞片压痕, 有明显方向性纹理
- scratches 是细长直线形机械划伤(可横向或纵向), 比 crazing 更直、更长、不成网

严格规则(违反即错误):
1. 一张图中同一类缺陷常包含多个互不相连的区域(本数据集平均每图 2-3 个), 必须逐一枚举, 严禁因为"图主要是某类缺陷"就只给一个框; 但最多只输出 8 个最显著的独立区域, 按严重程度排序
2. 检测框必须紧贴单个缺陷区域边缘, 严禁给出覆盖整张图或大半个图的"代表框"(例如坐标接近 0/0/1/1 的框)
3. bbox 为归一化坐标, x1/y1/x2/y2 均为 0 到 1 之间的小数(原点左上, x1<x2, y1<y2)
4. confidence 为 0 到 1 的把握度; 图中无缺陷时 detections 返回空数组

只输出一个 JSON 对象, 禁止 markdown 代码块、解释或任何多余文字:
{{"detections":[{{"class":"scratches","confidence":0.8,"bbox":{{"x1":0.1,"y1":0.05,"x2":0.2,"y2":0.9}}}}]}}"""

# 类别别名 -> 标准英文标识(模型可能输出中文/连字符差异/单复数等)
CLASS_ALIASES: dict[str, str] = {}
for _c in YOLO_CLASSES:
    CLASS_ALIASES[_c] = _c
CLASS_ALIASES.update(
    {
        "craze": "crazing",
        "crack": "crazing",
        "cracks": "crazing",
        "裂纹": "crazing",
        "龟裂": "crazing",
        "inclusions": "inclusion",
        "slag": "inclusion",
        "夹渣": "inclusion",
        "夹杂": "inclusion",
        "patch": "patches",
        "斑块": "patches",
        "斑痕": "patches",
        "pitted": "pitted_surface",
        "pitted surface": "pitted_surface",
        "pits": "pitted_surface",
        "pitting": "pitted_surface",
        "pit": "pitted_surface",
        "麻点": "pitted_surface",
        "点蚀": "pitted_surface",
        "麻面": "pitted_surface",
        "rolled in scale": "rolled-in_scale",
        "rolled_in_scale": "rolled-in_scale",
        "rolledin_scale": "rolled-in_scale",
        "rolled-in scale": "rolled-in_scale",
        "scale": "rolled-in_scale",
        "氧化铁皮": "rolled-in_scale",
        "氧化皮": "rolled-in_scale",
        "鳞片": "rolled-in_scale",
        "scratch": "scratches",
        "划痕": "scratches",
        "划伤": "scratches",
    }
)


class VlError(Exception):
    """视觉模型调用错误, kind 供路由映射 HTTP 状态码"""

    def __init__(self, message: str, kind: str = "upstream") -> None:
        super().__init__(message)
        self.kind = kind  # config / auth / ratelimit / timeout / upstream / badresponse


def canonical_class(raw: Any) -> str | None:
    """把模型输出的类别名归一到 6 个标准英文标识; 无法识别返回 None"""
    if not isinstance(raw, str):
        return None
    key = raw.strip().lower().replace("-", "_")
    # 先直接匹配标准名
    if key in YOLO_CLASSES:
        return key
    # 再走别名表(统一比较: 小写/去空格/连字符转下划线)
    alias_key = re.sub(r"[\s\-]+", "_", raw.strip().lower())
    for alias, std in CLASS_ALIASES.items():
        a = re.sub(r"[\s\-]+", "_", alias.lower())
        if a == alias_key:
            return std
    return None


# 3.2 历史私有名保留为别名(实现已抽到 app.common.jsonio, 4.2 报告模块共用)
_strip_code_fence = strip_code_fence
_loads_lenient_json = loads_lenient_json


def _salvage_detection_items(content: str) -> list[Any]:
    """从损坏/截断的模型输出中"打捞"已完整生成的 detection 项。

    线上实测: 模型枚举大量区域(上千 token)时, 偶尔会在写完一个完整 JSON 后
    又重复 ", "detections": [...]" 并在半截断尾, 导致整体 JSON 解析失败。
    这里按括号深度扫描(正确跳过字符串内括号), 只收集 detections 数组内
    第一次从深度 2 闭合回 1 的完整对象; 数组一旦闭合或外层对象结束即停止,
    因此重复段不会被二次计入。
    """
    text = _strip_code_fence(content)
    start = text.find("{")
    if start < 0:
        return []

    items: list[Any] = []
    depth_brace = 0
    depth_bracket = 0
    in_str = False
    escape = False
    item_start = -1

    for i, ch in enumerate(text[start:], start):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth_brace += 1
            # 外层对象 brace=1, detections 数组 bracket=1: 此时 brace 1->2 即检测项开始
            if depth_brace == 2 and depth_bracket == 1:
                item_start = i
        elif ch == "}":
            # 只在"递减前深度为 2"时捕获: 这是检测项对象闭合(2->1);
            # 内层 bbox 闭合时深度为 3(3->2), 不能提前捕获半个 item
            if depth_brace == 2 and depth_bracket == 1 and item_start >= 0:
                fragment = text[item_start : i + 1]
                try:
                    obj = json.loads(fragment)
                    if isinstance(obj, dict) and "class" in obj and "bbox" in obj:
                        items.append(obj)
                except json.JSONDecodeError:
                    try:
                        repaired = re.sub(r",\s*([}\]])", r"\1", fragment)
                        obj = json.loads(repaired)
                        if isinstance(obj, dict) and "class" in obj and "bbox" in obj:
                            items.append(obj)
                    except json.JSONDecodeError:
                        pass
                item_start = -1
            depth_brace -= 1
            if depth_brace == 0:
                break  # 外层对象已完整闭合
        elif ch == "[":
            depth_bracket += 1
        elif ch == "]":
            depth_bracket -= 1
            # detections 数组闭合(bracket 1->0)后, 模型再吐重复键/第二段一律不打捞
            if depth_bracket == 0:
                break
    return items


def parse_vl_content(content: str, width: int, height: int) -> list[dict[str, Any]]:
    """把 VLM 文本响应解析为标准检测字典列表(纯函数)

    - 坐标按归一化 0..1 解析并裁剪, 再换算为像素绝对坐标
    - 丢弃: 类别无法识别 / 坐标缺字段 / 退化框(x2<=x1 或 y2<=y1)
    - confidence 缺失给 0.5, 越界裁剪到 0..1
    """
    try:
        payload = _loads_lenient_json(content)
    except (json.JSONDecodeError, TypeError):
        # 最后兜底: 输出整体损坏(重复键/半截断尾)时, 打捞已完整生成的检测项
        salvaged = _salvage_detection_items(content)
        if salvaged:
            payload = {"detections": salvaged}
        else:
            raise VlError(
                f"视觉模型返回不是合法 JSON 且无法打捞任何检测项: {content[:200]!r}",
                kind="badresponse",
            )

    raw_dets = payload.get("detections") if isinstance(payload, dict) else None
    if not isinstance(raw_dets, list):
        # 个别畸形输出连数组都没有, 再试一次打捞
        raw_dets = _salvage_detection_items(content)
        if not raw_dets:
            raise VlError("视觉模型 JSON 缺少 detections 数组", kind="badresponse")

    dets: list[dict[str, Any]] = []
    for item in raw_dets:
        if not isinstance(item, dict):
            continue
        std_name = canonical_class(item.get("class"))
        if std_name is None:
            continue
        bbox = item.get("bbox")
        if not isinstance(bbox, dict):
            continue
        try:
            x1, y1 = float(bbox["x1"]), float(bbox["y1"])
            x2, y2 = float(bbox["x2"]), float(bbox["y2"])
        except (KeyError, TypeError, ValueError):
            continue
        # 归一化裁剪
        x1, x2 = sorted((min(max(x1, 0.0), 1.0), min(max(x2, 0.0), 1.0)))
        y1, y2 = sorted((min(max(y1, 0.0), 1.0), min(max(y2, 0.0), 1.0)))
        if x2 - x1 < 1e-4 or y2 - y1 < 1e-4:
            continue
        try:
            conf = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        conf = min(max(conf, 0.0), 1.0)

        class_id = YOLO_CLASSES.index(std_name)
        dets.append(
            {
                "class_id": class_id,
                "class_name": std_name,
                "class_name_cn": CLASS_NAME_CN[std_name],
                "confidence": round(conf, 4),
                "bbox": {
                    "x1": round(x1 * width, 2),
                    "y1": round(y1 * height, 2),
                    "x2": round(x2 * width, 2),
                    "y2": round(y2 * height, 2),
                },
            }
        )
    # 置信度降序, 与 YOLO 后处理一致
    dets.sort(key=lambda d: d["confidence"], reverse=True)
    return dets


def guess_image_mime(image_bytes: bytes) -> str:
    """按魔数判断图片 MIME(百炼 data URL 需要)"""
    if image_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"  # NEU-DET 全是 jpg, 兜底按 jpeg


def resolve_vl_endpoint(model: str | None = None) -> tuple[str, str, str, str]:
    """返回 (provider, base_url, api_key, model_id)

    model 可传: plus / max / None(用配置选定) / 具体模型 id
    """
    provider = (settings.vl_provider or "dashscope").lower()
    if provider == "ollama":
        return "ollama", settings.ollama_base_url.rstrip("/"), "ollama", (
            model or settings.vl_model_ollama
        )
    # 默认 dashscope
    if not settings.dashscope_api_key:
        raise VlError("未配置 DASHSCOPE_API_KEY, 请在 ai-service/.env 中设置", kind="config")
    alias = {
        "plus": settings.vl_model_plus,
        "max": settings.vl_model_max,
    }
    model_id = alias.get((model or "").lower(), model or settings.vl_model)
    return "dashscope", settings.vl_base_url.rstrip("/"), settings.dashscope_api_key, model_id


class VlDetector:
    """Qwen-VL 零样本检测器(无状态, 每次调用一个 HTTP 请求)"""

    def detect_bytes(
        self,
        image_bytes: bytes,
        model: str | None = None,
    ) -> dict[str, Any]:
        """对图片字节做零样本检测, 返回 VlDetectResponse 的 dict 形态"""
        img = decode_image(image_bytes)  # 复用: 非图直接 ValueError
        height, width = img.shape[:2]

        provider, base_url, api_key, model_id = resolve_vl_endpoint(model)
        mime = guess_image_mime(image_bytes)
        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"

        body = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": USER_PROMPT_TEMPLATE.format(class_spec=CLASS_SPEC)},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
            # prompt 已限制最多 8 个区域, 2048 token 足够; 封顶防止模型"枚举发散"
            # (实测个别图会吐 2800+ token 并出现重复键/截断, 解析侧另有打捞兜底)
            "max_tokens": 2048,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # 超时/限流自动重试 1 次(批量对决时单图偶发抖动不应中断整批)
        started = time.perf_counter()
        resp: httpx.Response | None = None
        for attempt in range(2):
            try:
                with httpx.Client(timeout=settings.vl_timeout) as client:
                    resp = client.post(f"{base_url}/chat/completions", json=body, headers=headers)
            except httpx.TimeoutException as exc:
                if attempt == 0:
                    time.sleep(2.0)
                    continue
                raise VlError(f"视觉模型请求超时({settings.vl_timeout}s, 已重试1次)", kind="timeout") from exc
            except httpx.HTTPError as exc:
                raise VlError(f"视觉模型网络错误: {exc}", kind="upstream") from exc
            if resp.status_code == 429 and attempt == 0:
                time.sleep(3.0)
                continue
            break
        latency_ms = round((time.perf_counter() - started) * 1000, 2)

        if resp is None or resp.status_code != 200:
            assert resp is not None
            self._raise_for_status(resp.status_code, resp.text)

        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {}) or {}
        except (KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            raise VlError(f"视觉模型响应结构异常: {exc}", kind="badresponse") from exc

        if isinstance(content, list):  # 部分兼容端点 content 为分段数组
            content = "".join(
                seg.get("text", "") for seg in content if isinstance(seg, dict)
            )
        if not isinstance(content, str):
            raise VlError("视觉模型响应 content 不是文本", kind="badresponse")

        dets = parse_vl_content(content, width, height)
        return {
            "model": model_id,
            "provider": provider,
            "image_width": width,
            "image_height": height,
            "inference_ms": latency_ms,
            "count": len(dets),
            "detections": dets,
            "tokens": {
                "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                "completion_tokens": int(usage.get("completion_tokens", 0)),
                "total_tokens": int(usage.get("total_tokens", 0)),
            },
        }

    @staticmethod
    def _raise_for_status(status: int, text: str) -> None:
        detail = text[:300]
        if status in (401, 403):
            raise VlError(f"视觉模型鉴权失败(HTTP {status}), 请检查 API Key: {detail}", kind="auth")
        if status == 429:
            raise VlError(f"视觉模型限流/额度不足(HTTP 429): {detail}", kind="ratelimit")
        if status == 400:
            raise VlError(f"视觉模型拒绝请求(HTTP 400), 可能模型名不可用或图片超限: {detail}", kind="upstream")
        raise VlError(f"视觉模型服务错误(HTTP {status}): {detail}", kind="upstream")


vl_detector = VlDetector()
