"""阶段4.2 结构化报告模块单测(不发起真实 HTTP / 不连 Milvus)"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.config import settings
from app.report import prompts, similar
from app.report.builder import SCHEMA_VERSION, build_report
from app.report.llm_client import (
    ReportError,
    ReportLlmClient,
    parse_and_validate,
    sanitize_narrative,
    validate_narrative,
)
from app.report.router import _run_generate
from app.report.schemas import (
    BatchFacts,
    ClassFact,
    ReportRequest,
    RepresentativeCase,
)


# ---------- 工厂夹具 ----------

def make_class_stats() -> list[dict]:
    return [
        {"class_name": "scratches", "class_name_cn": "划痕", "count": 12,
         "ratio": 0.6, "avg_confidence": 0.81},
        {"class_name": "inclusion", "class_name_cn": "夹杂", "count": 8,
         "ratio": 0.4, "avg_confidence": 0.72},
    ]


def make_facts(**overrides) -> dict:
    base = {
        "batch_id": 99,
        "batch_no": "BATCH-TEST-0001",
        "name": "4.2单测批次",
        "source": "dataset",
        "detect_model": "yolo11s",
        "image_count": 20,
        "defect_image_count": 10,
        "defect_count": 20,
        "case_count": 20,
        "defect_rate": 0.5,
        "box_density": 1.0,
        "avg_inference_ms": 13.2,
        "high_risk_count": 12,
        "rule_severity": "high",
    }
    base.update(overrides)
    return base


def make_narrative(**overrides) -> dict:
    base = {
        "overall_assessment": "本批次缺陷率达到百分之五十, 框密度1.0, 以划痕类线性缺陷为主, 整体表面质量偏差。",
        "severity": "high",
        "severity_reason": "缺陷率0.5且高危类划痕占比0.6, 符合 high 定级的事实特征, 对后续涂镀影响较大。",
        "class_analysis": [
            {"class_name": "scratches",
             "finding": "划痕12处占比六成, 平均置信度0.81, 线性机械损伤特征明显。",
             "suggestion": "重点排查轧辊与导向辊表面是否存在硬物磕碰, 并检查开卷张力波动。"},
            {"class_name": "inclusion",
             "finding": "夹杂8处, 平均置信度0.72, 点状异物嵌入, 与连铸保护渣卷入可能相关。",
             "suggestion": "回溯连铸工序保护渣加注与钢水洁净度记录, 必要时增加板面吹扫。"},
        ],
        "disposition": [
            "本批次建议降级处理, 不得直接进入涂镀工序",
            "组织复判划痕长度与深度, 评估修磨可行性",
            "回溯轧制工序辊面检查记录并更换可疑辊",
        ],
        "risk_summary": "若直接放行存在较高涂装起泡与疲劳裂纹扩展风险, 建议对该批次加倍抽检并人工复核。",
    }
    base.update(overrides)
    return base


def make_llm_response(content: str) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 800, "completion_tokens": 600, "total_tokens": 1400},
    }


# ---------- prompt 构建 ----------

def test_prompt_contains_all_key_facts():
    prompt = prompts.build_user_prompt(make_facts(), make_class_stats())
    for token in ["BATCH-TEST-0001", "defect_rate", "0.5", "scratches",
                  "inclusion", "rule_severity", "high", "class_stats"]:
        assert token in prompt


def test_prompt_forbids_external_numbers():
    prompt = prompts.build_user_prompt(make_facts(), make_class_stats())
    assert "事实包之外" in prompt
    assert "不得新增类别" in prompt


def test_repair_prompt_lists_errors():
    msg = prompts.build_repair_prompt(["severity: 枚举错误", "disposition: 太短"])
    assert "severity: 枚举错误" in msg and "JSON" in msg


# ---------- 业务清洗 + Schema 校验 ----------

def test_sanitize_drops_unknown_and_duplicate_classes():
    raw = make_narrative()
    raw["class_analysis"].append(
        {"class_name": "rust", "finding": "编造的锈蚀" + "x" * 40,
         "suggestion": "建议" + "y" * 40})
    raw["class_analysis"].append(
        {"class_name": "SCRATCHES", "finding": "重复的划痕" + "x" * 40,
         "suggestion": "重复建议" + "y" * 40})
    cleaned = sanitize_narrative(raw, frozenset({"scratches", "inclusion"}))
    assert [c["class_name"] for c in cleaned["class_analysis"]] == ["scratches", "inclusion"]


def test_sanitize_strips_strings_and_filters_disposition():
    raw = make_narrative()
    raw["overall_assessment"] = "  带空格的结论 " + "z" * 50
    raw["disposition"] = [" 正经建议" + "a" * 20, "", "   "]
    cleaned = sanitize_narrative(raw, frozenset({"scratches", "inclusion"}))
    assert cleaned["overall_assessment"].startswith("带空格的结论")
    assert cleaned["disposition"] == ["正经建议" + "a" * 20]


def test_sanitize_rejects_non_dict():
    with pytest.raises(ReportError) as ei:
        sanitize_narrative(["not", "dict"], frozenset())
    assert ei.value.kind == "badresponse"


def test_validate_accepts_valid_narrative():
    assert validate_narrative(make_narrative()) == []


@pytest.mark.parametrize("mutator", [
    lambda n: n.pop("severity"),
    lambda n: n.update(severity="extreme"),
    lambda n: n.update(overall_assessment="太短"),
    lambda n: n.update(disposition=[]),
    lambda n: n.update(class_analysis=[]),
    lambda n: n.update(extra_field=123),
])
def test_validate_rejects_bad_shapes(mutator):
    narrative = make_narrative()
    mutator(narrative)
    assert validate_narrative(narrative) != []


def test_parse_valid_content_with_fence_and_trailing_comma():
    import json

    narrative = make_narrative()
    content = "```json\n" + json.dumps(narrative, ensure_ascii=False) + ",\n```"
    parsed = parse_and_validate(content, frozenset({"scratches", "inclusion"}))
    assert parsed["severity"] == "high"


def test_parse_bad_json_raises_badresponse():
    with pytest.raises(ReportError) as ei:
        parse_and_validate("我认为本批次质量一般", frozenset({"scratches"}))
    assert ei.value.kind == "badresponse"


def test_parse_all_classes_filtered_out_raises():
    content = (
        '{"overall_assessment": "' + "x" * 60 + '",'
        '"severity":"low","severity_reason":"' + "y" * 40 + '",'
        '"class_analysis":[{"class_name":"ghost","finding":"' + "a" * 40
        + '","suggestion":"' + "b" * 40 + '"}],'
        '"disposition":["' + "c" * 20 + '"],"risk_summary":"' + "d" * 60 + '"}'
    )
    with pytest.raises(ReportError) as ei:
        parse_and_validate(content, frozenset({"scratches"}))
    assert ei.value.kind == "badresponse"


# ---------- LLM 客户端(打桩 _post_chat, 不发真实请求) ----------

def test_generate_success(monkeypatch):
    monkeypatch.setattr(settings, "dashscope_api_key", "test-key")
    import json

    captured: dict = {}

    def fake_post(self, messages, model_id):
        captured["messages"] = messages
        captured["model"] = model_id
        return make_llm_response(json.dumps(make_narrative(), ensure_ascii=False))

    monkeypatch.setattr(ReportLlmClient, "_post_chat", fake_post)
    result = ReportLlmClient().generate(make_facts(), make_class_stats())
    assert result["model"] == settings.llm_model
    assert result["provider"] == "dashscope"
    assert result["tokens"]["total_tokens"] == 1400
    assert result["narrative"]["severity"] == "high"
    # system+user 两条消息, user 中注入了事实包
    assert len(captured["messages"]) == 2
    assert "BATCH-TEST-0001" in captured["messages"][1]["content"]


def test_generate_missing_api_key(monkeypatch):
    monkeypatch.setattr(settings, "dashscope_api_key", "")
    with pytest.raises(ReportError) as ei:
        ReportLlmClient().generate(make_facts(), make_class_stats())
    assert ei.value.kind == "config"


def test_generate_repair_retry_then_success(monkeypatch):
    monkeypatch.setattr(settings, "dashscope_api_key", "test-key")
    import json

    bad = make_narrative()
    bad["severity"] = "weird"  # 枚举非法 -> 触发修复
    calls = {"n": 0}

    def fake_post(self, messages, model_id):
        calls["n"] += 1
        if calls["n"] == 1:
            return make_llm_response(json.dumps(bad, ensure_ascii=False))
        # 修复轮: 校验对话里确实带上了错误反馈
        assert "不符合约定" in messages[-1]["content"]
        assert messages[-2]["role"] == "assistant"
        return make_llm_response(json.dumps(make_narrative(), ensure_ascii=False))

    monkeypatch.setattr(ReportLlmClient, "_post_chat", fake_post)
    result = ReportLlmClient().generate(make_facts(), make_class_stats())
    assert calls["n"] == 2
    assert result["narrative"]["severity"] == "high"


def test_generate_repair_still_bad_raises(monkeypatch):
    monkeypatch.setattr(settings, "dashscope_api_key", "test-key")

    def fake_post(self, messages, model_id):
        return make_llm_response("不是json")

    monkeypatch.setattr(ReportLlmClient, "_post_chat", fake_post)
    with pytest.raises(ReportError) as ei:
        ReportLlmClient().generate(make_facts(), make_class_stats())
    assert ei.value.kind == "badresponse"


def test_extract_handles_segmented_content(monkeypatch):
    data = {
        "choices": [{"message": {"content": [
            {"text": "第一段"}, {"text": "第二段"}]}}],
        "usage": {},
    }
    content, usage = ReportLlmClient._extract(data)
    assert content == "第一段第二段"
    assert usage["total_tokens"] == 0


# ---------- 报告装配 ----------

def test_build_report_facts_authoritative_and_severity_rule_wins():
    narrative = make_narrative(severity="critical")  # LLM 想上调定级
    report = build_report(
        batch_facts=make_facts(),
        class_stats=make_class_stats(),
        similar_cases=[{"case_id": 1, "class_name": "scratches"}],
        llm_result={"narrative": narrative, "model": "qwen-plus",
                    "provider": "dashscope", "tokens": {"total_tokens": 1400},
                    "latency_ms": 5.0},
        generated_at="2026-09-13T12:00:00",
    )
    assert report["schema_version"] == SCHEMA_VERSION
    # 顶层严重度以程序规则为准, LLM 分歧留痕
    assert report["severity"] == "high"
    assert report["severity_adjusted"] is True
    assert report["narrative"]["severity"] == "critical"
    # 事实块与类统计原样透传, 模型无法触碰
    assert report["facts"]["defect_rate"] == 0.5
    assert report["class_stats"][0]["count"] == 12
    assert report["similar_cases"][0]["case_id"] == 1
    assert report["tokens"]["total_tokens"] == 1400


def test_build_report_severity_consistent_flag_false():
    report = build_report(
        make_facts(), make_class_stats(), [],
        {"narrative": make_narrative(), "model": "qwen-plus"},
    )
    assert report["severity_adjusted"] is False


# ---------- 相似案例(打桩 Milvus/store) ----------

def _make_reps():
    return [
        RepresentativeCase(class_name="scratches", milvus_pk="r1-0", record_id=1),
        RepresentativeCase(class_name="inclusion", milvus_pk="r2-1", record_id=2),
    ]


def test_find_similar_cases_happy_path(monkeypatch):
    monkeypatch.setattr(similar.milvus_client, "query_vectors",
                        lambda pks: {"r1-0": [0.1] * 4, "r2-1": [0.2] * 4})
    captured: dict = {}

    def fake_search(vector, top_k, class_name, exclude_record_id, exclude_batch_id):
        captured["exclude_batch_id"] = exclude_batch_id
        return [{"pk": f"{class_name}-h1", "score": 0.91, "class_name": class_name,
                 "record_id": 100, "batch_id": 4, "confidence": 0.8},
                {"pk": f"{class_name}-h2", "score": 0.88, "class_name": class_name,
                 "record_id": 101, "batch_id": 4, "confidence": 0.7}]

    monkeypatch.setattr(similar.milvus_client, "search_cases", fake_search)

    def fake_enrich(hits):
        return [{"case_id": i + 1, "milvus_pk": h["pk"], "score": h["score"],
                 "class_name": h["class_name"], "record_id": h["record_id"],
                 "batch_id": h["batch_id"], "batch_no": "HIST-NEUDET-RAW",
                 "image_name": f"{h['class_name']}_1.jpg",
                 "detect_confidence": h["confidence"],
                 "crop_url": None, "source_image_url": None}
                for i, h in enumerate(hits)]

    monkeypatch.setattr(similar, "enrich_hits", fake_enrich)

    results = similar.find_similar_cases(_make_reps(), exclude_batch_id=99)
    assert captured["exclude_batch_id"] == 99
    assert len(results) == 4
    assert results[0]["class_name"] == "scratches"
    assert results[0]["class_name_cn"] == "划痕"
    assert {r["class_name"] for r in results} == {"scratches", "inclusion"}


def test_find_similar_cases_empty_reps():
    assert similar.find_similar_cases([], exclude_batch_id=99) == []


def test_find_similar_cases_dedupes_case_ids(monkeypatch):
    monkeypatch.setattr(similar.milvus_client, "query_vectors", lambda pks: {"r1-0": [0.1]})
    monkeypatch.setattr(
        similar.milvus_client, "search_cases",
        lambda *a, **k: [{"pk": "same", "score": 0.9, "class_name": "scratches",
                          "record_id": 100, "batch_id": 4, "confidence": 0.8}])
    monkeypatch.setattr(
        similar, "enrich_hits",
        lambda hits: [{"case_id": 7, "milvus_pk": "same", "class_name": "scratches"}])
    reps = [RepresentativeCase(class_name="scratches", milvus_pk="r1-0", record_id=1)]
    # 单代表只搜一次, 天然一条; 主要验证不报错并补中文名
    out = similar.find_similar_cases(reps, exclude_batch_id=99)
    assert len(out) == 1 and out[0]["class_name_cn"] == "划痕"


# ---------- 路由整体(打桩 LLM + 相似检索) ----------

def _make_report_request():
    return ReportRequest(
        batch=BatchFacts(**make_facts()),
        class_stats=[ClassFact(**c) for c in make_class_stats()],
        representatives=_make_reps(),
    )


def test_router_run_generate_success(monkeypatch):
    import json

    from app.report import router as report_router

    monkeypatch.setattr(
        report_router, "find_similar_cases",
        lambda reps, exclude_batch_id: [{"case_id": 1, "class_name": "scratches"}])

    def fake_generate(facts, class_stats, model):
        return {"narrative": make_narrative(), "model": "qwen-plus",
                "provider": "dashscope",
                "tokens": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                "latency_ms": 4.2}

    monkeypatch.setattr(report_router.report_llm, "generate", fake_generate)
    resp = _run_generate(_make_report_request())
    assert resp.model == "qwen-plus"
    assert resp.tokens.total_tokens == 30
    assert resp.report["facts"]["batch_no"] == "BATCH-TEST-0001"
    assert resp.report["narrative"]["disposition"][0].startswith("本批次")
    # 整个响应必须可 JSON 序列化(要经 HTTP 下发并原样落 MySQL LONGTEXT)
    json.loads(json.dumps(resp.model_dump(mode="json"), ensure_ascii=False))


def test_router_run_generate_similar_failure_degrades(monkeypatch):
    from app.report import router as report_router

    def boom(reps, exclude_batch_id):
        raise RuntimeError("milvus down")

    monkeypatch.setattr(report_router, "find_similar_cases", boom)

    def fake_generate(facts, class_stats, model):
        return {"narrative": make_narrative(), "model": "qwen-plus",
                "provider": "dashscope",
                "tokens": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "latency_ms": 1.0}

    monkeypatch.setattr(report_router.report_llm, "generate", fake_generate)
    resp = _run_generate(_make_report_request())
    assert resp.similar_cases == []  # 证据块降级, 报告照常
    assert resp.report["narrative"]["severity"] == "high"


def test_router_run_generate_llm_config_error_maps_503(monkeypatch):
    from app.report import router as report_router

    monkeypatch.setattr(report_router, "find_similar_cases", lambda reps, bid: [])

    def fake_generate(facts, class_stats, model):
        raise ReportError("未配置 key", kind="config")

    monkeypatch.setattr(report_router.report_llm, "generate", fake_generate)
    with pytest.raises(HTTPException) as ei:
        _run_generate(_make_report_request())
    assert ei.value.status_code == 503
