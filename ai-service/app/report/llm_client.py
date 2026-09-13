"""qwen-plus 结构化报告 LLM 客户端(阿里云百炼 OpenAI 兼容协议)

幻觉控制三重防线(对应简历面试题"如何让 LLM 输出结构化结果?幻觉控制?"):
1. 事实注入: 所有数字由 Java 从 MySQL 聚合, prompt 只给事实包并禁止外部数字
2. 结构约束: response_format=json_object + 温度 0 + 输出前显式 Schema 说明
3. 程序校验: jsonschema 强校验 + 业务白名单(class_analysis 只允许事实包中的类别),
   不合法时携带错误信息修复重试 1 次; 仍不合法则 502, 绝不落库脏报告
"""
from __future__ import annotations

import time
from typing import Any

import httpx
import jsonschema
from jsonschema import Draft7Validator

from app.common.jsonio import loads_lenient_json
from app.config import settings
from app.report import prompts

# 严重度枚举(与 Java SeverityRules 对齐)
SEVERITY_LEVELS = ("low", "medium", "high", "critical")

# 模型叙述块 JSON Schema(最终报告的 narrative 部分)
NARRATIVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "overall_assessment",
        "severity",
        "severity_reason",
        "class_analysis",
        "disposition",
        "risk_summary",
    ],
    "properties": {
        "overall_assessment": {"type": "string", "minLength": 30, "maxLength": 2000},
        "severity": {"type": "string", "enum": list(SEVERITY_LEVELS)},
        "severity_reason": {"type": "string", "minLength": 20, "maxLength": 1200},
        "class_analysis": {
            "type": "array",
            "minItems": 1,
            "maxItems": 6,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["class_name", "finding", "suggestion"],
                "properties": {
                    "class_name": {"type": "string", "minLength": 1, "maxLength": 64},
                    "finding": {"type": "string", "minLength": 10, "maxLength": 1200},
                    "suggestion": {"type": "string", "minLength": 10, "maxLength": 1200},
                },
            },
        },
        "disposition": {
            "type": "array",
            "minItems": 1,
            "maxItems": 6,
            "items": {"type": "string", "minLength": 5, "maxLength": 300},
        },
        "risk_summary": {"type": "string", "minLength": 20, "maxLength": 1200},
    },
}

_VALIDATOR = Draft7Validator(NARRATIVE_SCHEMA)


class ReportError(Exception):
    """报告 LLM 调用错误, kind 供路由映射 HTTP 状态码"""

    def __init__(self, message: str, kind: str = "upstream") -> None:
        super().__init__(message)
        self.kind = kind  # config / auth / ratelimit / timeout / upstream / badresponse


def sanitize_narrative(raw: Any, allowed_classes: frozenset[str]) -> dict[str, Any]:
    """业务层清洗(在 jsonschema 之前做):

    - 非 dict / 缺字段直接抛 badresponse
    - class_analysis: 剔除非 dict 项、类别不在事实包白名单的项, 同类别去重保首条
    - disposition: 只保留非空字符串并 strip
    - 字符串字段统一 strip
    """
    if not isinstance(raw, dict):
        raise ReportError("报告模型返回不是 JSON 对象", kind="badresponse")

    cleaned: dict[str, Any] = {}
    for key in ("overall_assessment", "severity", "severity_reason", "risk_summary"):
        val = raw.get(key)
        cleaned[key] = val.strip() if isinstance(val, str) else val

    analysis: list[dict[str, Any]] = []
    seen_classes: set[str] = set()
    raw_analysis = raw.get("class_analysis")
    if isinstance(raw_analysis, list):
        for item in raw_analysis:
            if not isinstance(item, dict):
                continue
            cls = item.get("class_name")
            if not isinstance(cls, str):
                continue
            cls = cls.strip().lower()
            # 白名单: LLM 只能分析事实包里真实存在的类别, 杜绝臆造类别
            if cls not in allowed_classes or cls in seen_classes:
                continue
            finding = item.get("finding")
            suggestion = item.get("suggestion")
            analysis.append(
                {
                    "class_name": cls,
                    "finding": finding.strip() if isinstance(finding, str) else finding,
                    "suggestion": suggestion.strip() if isinstance(suggestion, str) else suggestion,
                }
            )
            seen_classes.add(cls)
    cleaned["class_analysis"] = analysis

    disposition: list[str] = []
    raw_disp = raw.get("disposition")
    if isinstance(raw_disp, list):
        for item in raw_disp:
            if isinstance(item, str) and item.strip():
                disposition.append(item.strip())
    cleaned["disposition"] = disposition
    return cleaned


def validate_narrative(narrative: dict[str, Any]) -> list[str]:
    """jsonschema 校验, 返回人类可读的错误信息列表(空列表=通过)"""
    return [
        f"{list(err.absolute_path) or '<root>'}: {err.message}"
        for err in sorted(_VALIDATOR.iter_errors(narrative), key=lambda e: e.path)
    ]


def parse_and_validate(content: str, allowed_classes: frozenset[str]) -> dict[str, Any]:
    """解析 -> 业务清洗 -> Schema 校验; 不通过抛 badresponse(供单测直接覆盖)"""
    try:
        raw = loads_lenient_json(content)
    except Exception as exc:  # noqa: BLE001 - JSONDecodeError 等
        raise ReportError(f"报告模型返回不是合法 JSON: {str(exc)[:200]}", kind="badresponse") from exc
    narrative = sanitize_narrative(raw, allowed_classes)
    errors = validate_narrative(narrative)
    if errors:
        raise ReportError(
            "报告模型输出不符合 Schema: " + "; ".join(errors[:6]),
            kind="badresponse",
        )
    return narrative


class ReportLlmClient:
    """qwen-plus 文本报告客户端(无状态, 一次报告 1~2 个 HTTP 请求)"""

    def generate(
        self,
        facts: dict[str, Any],
        class_stats: list[dict[str, Any]],
        model: str | None = None,
    ) -> dict[str, Any]:
        """生成并校验叙述块, 返回 {narrative, model, provider, tokens, latency_ms}"""
        if not settings.dashscope_api_key:
            raise ReportError(
                "未配置 DASHSCOPE_API_KEY, 请在 ai-service/.env 中设置", kind="config"
            )
        model_id = model or settings.llm_model
        allowed = frozenset(c["class_name"] for c in class_stats)
        messages = [
            {"role": "system", "content": prompts.SYSTEM_PROMPT},
            {"role": "user", "content": prompts.build_user_prompt(facts, class_stats)},
        ]

        started = time.perf_counter()
        content, usage = self._chat_with_repair(messages, model_id, allowed)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)

        narrative = parse_and_validate(content, allowed)
        return {
            "narrative": narrative,
            "model": model_id,
            "provider": "dashscope",
            "tokens": usage,
            "latency_ms": latency_ms,
        }

    def _chat_with_repair(
        self,
        messages: list[dict[str, str]],
        model_id: str,
        allowed_classes: frozenset[str],
    ) -> tuple[str, dict[str, int]]:
        """首轮调用; 输出解析/校验失败时携带错误与原文修复重试 1 次"""
        data = self._post_chat(messages, model_id)
        content, usage = self._extract(data)
        try:
            parse_and_validate(content, allowed_classes)
        except ReportError as first_err:
            if first_err.kind != "badresponse":
                raise
            # 修复重试: 重放首轮输出 + 具体校验错误
            repair_messages = [
                *messages,
                {"role": "assistant", "content": content},
                {"role": "user", "content": prompts.build_repair_prompt(
                    # 复用校验逻辑拿到完整错误列表
                    self._collect_errors(content, allowed_classes),
                )},
            ]
            data2 = self._post_chat(repair_messages, model_id)
            content2, usage2 = self._extract(data2)
            try:
                parse_and_validate(content2, allowed_classes)
            except ReportError as second_err:
                if second_err.kind == "badresponse":
                    raise ReportError(
                        f"报告经修复重试仍不符合 Schema: {second_err}",
                        kind="badresponse",
                    ) from second_err
                raise
            return content2, usage2
        return content, usage

    @staticmethod
    def _collect_errors(content: str, allowed_classes: frozenset[str]) -> list[str]:
        """修复 prompt 用: 尽量取出可读错误列表(解析彻底失败时给通用错误)"""
        try:
            raw = loads_lenient_json(content)
            narrative = sanitize_narrative(raw, allowed_classes)
            return validate_narrative(narrative) or ["输出不符合约定结构"]
        except Exception:  # noqa: BLE001 - JSONDecodeError / ReportError 均兜底
            return ["输出不是合法 JSON 或缺少必要字段"]

    @staticmethod
    def _extract(data: dict[str, Any]) -> tuple[str, dict[str, int]]:
        try:
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {}) or {}
        except (KeyError, IndexError, TypeError) as exc:
            raise ReportError(f"报告模型响应结构异常: {exc}", kind="badresponse") from exc
        if isinstance(content, list):  # 兼容 content 为分段数组
            content = "".join(
                seg.get("text", "") for seg in content if isinstance(seg, dict)
            )
        if not isinstance(content, str) or not content.strip():
            raise ReportError("报告模型响应 content 为空", kind="badresponse")
        return content, {
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
        }

    def _post_chat(self, messages: list[dict[str, str]], model_id: str) -> dict[str, Any]:
        """单次百炼 chat/completions HTTP 调用(超时/限流各重试 1 次)"""
        body = {
            "model": model_id,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            # 报告为有界中文输出(总体结论+6类分析+建议), 3000 token 足够封顶
            "max_tokens": 3000,
        }
        headers = {
            "Authorization": f"Bearer {settings.dashscope_api_key}",
            "Content-Type": "application/json",
        }
        resp: httpx.Response | None = None
        for attempt in range(2):
            try:
                with httpx.Client(timeout=settings.llm_timeout) as client:
                    resp = client.post(
                        f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                        json=body,
                        headers=headers,
                    )
            except httpx.TimeoutException as exc:
                if attempt == 0:
                    time.sleep(2.0)
                    continue
                raise ReportError(
                    f"报告模型请求超时({settings.llm_timeout}s, 已重试1次)", kind="timeout"
                ) from exc
            except httpx.HTTPError as exc:
                raise ReportError(f"报告模型网络错误: {exc}", kind="upstream") from exc
            if resp.status_code == 429 and attempt == 0:
                time.sleep(3.0)
                continue
            break

        assert resp is not None
        if resp.status_code != 200:
            self._raise_for_status(resp.status_code, resp.text)
        try:
            return resp.json()
        except ValueError as exc:
            raise ReportError("报告模型响应不是 JSON", kind="badresponse") from exc

    @staticmethod
    def _raise_for_status(status: int, text: str) -> None:
        detail = text[:300]
        if status in (401, 403):
            raise ReportError(f"报告模型鉴权失败(HTTP {status}), 请检查 API Key: {detail}",
                              kind="auth")
        if status == 429:
            raise ReportError(f"报告模型限流/额度不足(HTTP 429): {detail}", kind="ratelimit")
        if status == 400:
            raise ReportError(f"报告模型拒绝请求(HTTP 400), 可能模型名不可用: {detail}",
                              kind="upstream")
        raise ReportError(f"报告模型服务错误(HTTP {status}): {detail}", kind="upstream")


report_llm = ReportLlmClient()
