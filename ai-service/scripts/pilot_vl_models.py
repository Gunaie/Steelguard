"""Qwen-VL 零样本 pilot: qwen-vl-plus vs qwen-vl-max 小样本实测选优

评估方式:
- 从 val360(seed=42 分层划分, 与训练集无泄漏)中每类抽 --per-class 张
- 两模型用完全相同的零样本 prompt/参数(temp=0, JSON)
- 与 VOC GT 做同类贪心 IoU 匹配(阈值 0.5), 统计 P/R/F1(类别相关 + 类别无关定位)
- 记录延迟/token/JSON 合法率, 结果写 reports/vl_pilot.json

用法(在 ai-service/ 下):
    .\\.venv\\Scripts\\python.exe scripts/pilot_vl_models.py --per-class 2
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.dataset.voc_parser import parse_voc  # noqa: E402
from app.dataset.yolo_export import find_voc_files, stratified_split  # noqa: E402
from app.inference.vl_infer import VlError, vl_detector  # noqa: E402

IOU_THR = 0.5


def iou(a: dict, b: dict) -> float:
    """两个 xyxy 像素框的 IoU"""
    ix1, iy1 = max(a["x1"], b["x1"]), max(a["y1"], b["y1"])
    ix2, iy2 = min(a["x2"], b["x2"]), min(a["y2"], b["y2"])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (
        (a["x2"] - a["x1"]) * (a["y2"] - a["y1"])
        + (b["x2"] - b["x1"]) * (b["y2"] - b["y1"])
        - inter
    )
    return inter / ua if ua > 0 else 0.0


def match(preds: list[dict], gts: list[dict], class_aware: bool) -> tuple[int, int, int]:
    """同类贪心 IoU 匹配, 返回 (TP, FP, FN)"""
    matched_gt: set[int] = set()
    tp = 0
    # 按置信度降序匹配(输入已降序, 稳妥起见再排)
    for p in sorted(preds, key=lambda d: d["confidence"], reverse=True):
        best_iou, best_j = 0.0, -1
        for j, g in enumerate(gts):
            if j in matched_gt:
                continue
            if class_aware and p["class_name"] != g["class_name"]:
                continue
            v = iou(p["bbox"], g["bbox"])
            if v > best_iou:
                best_iou, best_j = v, j
        if best_j >= 0 and best_iou >= IOU_THR:
            tp += 1
            matched_gt.add(best_j)
    fp = len(preds) - tp
    fn = len(gts) - len(matched_gt)
    return tp, fp, fn


def pick_val_images(per_class: int, seed: int) -> list[tuple[str, Path, Path]]:
    """复现训练时 val 划分, 每类抽 per_class 张, 返回 (class, img, xml)"""
    import random

    from app.config import settings

    root = Path(settings.dataset_root)
    if not root.is_absolute() and not root.exists():
        root = Path(__file__).resolve().parents[2] / settings.dataset_root
    images_dir = (root / settings.dataset_images_dir).resolve()
    annotations_dir = (root / settings.dataset_annotations_dir).resolve()

    pairs = find_voc_files(images_dir, annotations_dir)
    split = stratified_split(pairs)
    val_pairs = [(img, xml) for img, xml in pairs if xml.stem in split["val"]]

    by_class: dict[str, list[tuple[Path, Path]]] = defaultdict(list)
    for img, xml in val_pairs:
        by_class[parse_voc(xml).class_name].append((img, xml))

    rng = random.Random(seed)
    picked: list[tuple[str, Path, Path]] = []
    for cls in sorted(by_class):
        lst = sorted(by_class[cls], key=lambda p: p[1].stem)
        rng.shuffle(lst)
        for img, xml in lst[:per_class]:
            picked.append((cls, img, xml))
    return picked


def evaluate_model(model_alias: str, samples: list) -> dict:
    """跑一个模型并汇总指标"""
    agg = {
        "tp": 0, "fp": 0, "fn": 0,  # 类别相关
        "tp_lo": 0, "fp_lo": 0, "fn_lo": 0,  # 类别无关(只看定位)
        "per_class": defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "gt": 0}),
        "latency_ms": [],
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "json_ok": 0,
        "errors": [],
        "images": [],
    }
    for idx, (cls, img_path, xml_path) in enumerate(samples, 1):
        doc = parse_voc(xml_path)
        gts = [
            {
                "class_name": o.class_name,
                "bbox": {"x1": float(o.xmin), "y1": float(o.ymin),
                         "x2": float(o.xmax), "y2": float(o.ymax)},
            }
            for o in doc.objects
        ]
        try:
            t0 = time.perf_counter()
            r = vl_detector.detect_bytes(img_path.read_bytes(), model=model_alias)
            wall = round((time.perf_counter() - t0) * 1000, 2)
        except VlError as e:
            print(f"  [{idx:>2}/{len(samples)}] {img_path.name}: ERROR {e.kind} {e}")
            agg["errors"].append({"image": img_path.name, "kind": e.kind, "message": str(e)})
            continue

        agg["json_ok"] += 1
        agg["latency_ms"].append(r["inference_ms"])
        agg["prompt_tokens"] += r["tokens"]["prompt_tokens"]
        agg["completion_tokens"] += r["tokens"]["completion_tokens"]
        agg["total_tokens"] += r["tokens"]["total_tokens"]

        tp, fp, fn = match(r["detections"], gts, class_aware=True)
        tp_lo, fp_lo, fn_lo = match(r["detections"], gts, class_aware=False)
        agg["tp"] += tp; agg["fp"] += fp; agg["fn"] += fn
        agg["tp_lo"] += tp_lo; agg["fp_lo"] += fp_lo; agg["fn_lo"] += fn_lo
        # 每类 GT 以 GT 类别累计; 预测命中在 match 时同类
        for g in gts:
            agg["per_class"][g["class_name"]]["gt"] += 1
        # 每类 TP/FP 按预测类别
        # (简化: 重新逐预测匹配一次拿命中类)
        matched_gt = set()
        for p in sorted(r["detections"], key=lambda d: d["confidence"], reverse=True):
            best_iou, best_j = 0.0, -1
            for j, g in enumerate(gts):
                if j in matched_gt:
                    continue
                if p["class_name"] != g["class_name"]:
                    continue
                v = iou(p["bbox"], g["bbox"])
                if v > best_iou:
                    best_iou, best_j = v, j
            slot = agg["per_class"][p["class_name"]]
            if best_j >= 0 and best_iou >= IOU_THR:
                slot["tp"] += 1
                matched_gt.add(best_j)
            else:
                slot["fp"] += 1
        # 每类 FN
        for cls_name, slot in agg["per_class"].items():
            slot["fn"] = slot["gt"] - slot["tp"]

        print(
            f"  [{idx:>2}/{len(samples)}] {img_path.name[:22]:<22} GT={len(gts)} "
            f"pred={r['count']:<2} TP={tp} FP={fp} FN={fn} "
            f"{r['inference_ms']:>7.0f}ms tok={r['tokens']['total_tokens']}"
        )
        agg["images"].append(
            {
                "image": img_path.name,
                "gt_count": len(gts),
                "pred_count": r["count"],
                "tp": tp, "fp": fp, "fn": fn,
                "latency_ms": r["inference_ms"],
                "wall_ms": wall,
                "tokens": r["tokens"],
                "detections": r["detections"],
            }
        )

    def prf(tp: int, fp: int, fn: int) -> dict:
        p = tp / (tp + fp) if tp + fp else 0.0
        r_ = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * r_ / (p + r_) if p + r_ else 0.0
        return {"precision": round(p, 4), "recall": round(r_, 4), "f1": round(f1, 4)}

    n = max(1, len(agg["latency_ms"]))
    agg["summary"] = {
        "images_ok": agg["json_ok"],
        "images_error": len(agg["errors"]),
        **prf(agg["tp"], agg["fp"], agg["fn"]),
        "localization_only": prf(agg["tp_lo"], agg["fp_lo"], agg["fn_lo"]),
        "latency_avg_ms": round(sum(agg["latency_ms"]) / n, 1),
        "latency_max_ms": round(max(agg["latency_ms"], default=0), 1),
        "tokens_per_image": round(agg["total_tokens"] / n, 1),
        "prompt_tokens": agg["prompt_tokens"],
        "completion_tokens": agg["completion_tokens"],
        "total_tokens": agg["total_tokens"],
    }
    agg["per_class"] = {
        k: {**v, **prf(v["tp"], v["fp"], v["fn"])} for k, v in agg["per_class"].items()
    }
    return agg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=2, help="每类抽样张数(默认2, 共12张)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    samples = pick_val_images(args.per_class, args.seed)
    print(f"[pilot] 抽样 {len(samples)} 张(val, 每类 {args.per_class} 张)")
    for c, img, _ in samples:
        print(f"  {c:<16} {img.name}")

    results: dict[str, dict] = {}
    for alias, label in (("plus", "qwen-vl-plus"), ("max", "qwen-vl-max")):
        print(f"\n[pilot] === {label} ===")
        results[label] = evaluate_model(alias, samples)

    # 汇总对比
    print("\n" + "=" * 78)
    print(f"{'指标':<22}{'qwen-vl-plus':>26}{'qwen-vl-max':>26}")
    print("-" * 78)
    for key, name in (
        ("precision", "精确率 P"),
        ("recall", "召回率 R"),
        ("f1", "F1"),
        ("json_ok", "JSON 合法图数"),
        ("latency_avg_ms", "平均延迟 ms"),
        ("latency_max_ms", "最大延迟 ms"),
        ("tokens_per_image", "token/张"),
    ):
        sp, sm = results["qwen-vl-plus"]["summary"], results["qwen-vl-max"]["summary"]
        print(f"{name:<22}{str(sp.get(key)):>26}{str(sm.get(key)):>26}")
    print("-" * 78)
    for cls in sorted(results["qwen-vl-plus"]["per_class"]):
        p = results["qwen-vl-plus"]["per_class"][cls]
        m = results["qwen-vl-max"]["per_class"].get(cls, {})
        print(
            f"F1 {cls:<16}{p['f1']:>26}{m.get('f1', '-'):>26}"
            f"   (plus P{p['precision']}/R{p['recall']}  max P{m.get('precision')}/R{m.get('recall')})"
        )

    reports = Path(__file__).resolve().parents[1] / "reports"
    reports.mkdir(exist_ok=True)
    out = reports / "vl_pilot.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[pilot] 明细已写 {out}")


if __name__ == "__main__":
    main()
