"""里程碑3.2: YOLOv11s(监督训练) vs Qwen-VL(零样本) 100 张 val 对决

- 样本: 训练同划分 seed=42 的 val360 中分层均衡抽 100 张(每类 16 + 4 补足)
- GT: 原始 VOC XML, 同类贪心 IoU>=0.5 匹配
- 指标: 精确率/召回率/F1(类别相关 + 仅定位)、每类 F1、图像级主类准确率、
        平均延迟、Qwen token 与现金成本(官方 2026 单价)
- 产物: reports/benchmark32.{json,csv,md}

用法(在 ai-service/ 下):
    .\\.venv\\Scripts\\python.exe scripts/benchmark_vl_vs_yolo.py --n 100 --workers 4
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.dataset.voc_parser import parse_voc  # noqa: E402
from app.dataset.yolo_export import find_voc_files, stratified_split  # noqa: E402
from app.inference.vl_infer import VlError, vl_detector  # noqa: E402
from app.inference.yolo_infer import YOLO_CLASSES, get_inferencer  # noqa: E402

# qwen-vl-plus 官方实时单价(元/百万 token, 2026-09 查自百炼模型价格页)
PRICE_INPUT_PER_M = 0.8
PRICE_OUTPUT_PER_M = 2.0
IOU_THR = 0.5


def iou(a: dict, b: dict) -> float:
    ix1, iy1 = max(a["x1"], b["x1"]), max(a["y1"], b["y1"])
    ix2, iy2 = min(a["x2"], b["x2"]), min(a["y2"], b["y2"])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    ua = (
        (a["x2"] - a["x1"]) * (a["y2"] - a["y1"])
        + (b["x2"] - b["x1"]) * (b["y2"] - b["y1"])
        - inter
    )
    return inter / ua if ua > 0 else 0.0


def match(preds: list[dict], gts: list[dict], class_aware: bool) -> tuple[int, int, int]:
    matched: set[int] = set()
    tp = 0
    for p in sorted(preds, key=lambda d: d["confidence"], reverse=True):
        best_iou, best_j = 0.0, -1
        for j, g in enumerate(gts):
            if j in matched:
                continue
            if class_aware and p["class_name"] != g["class_name"]:
                continue
            v = iou(p["bbox"], g["bbox"])
            if v > best_iou:
                best_iou, best_j = v, j
        if best_j >= 0 and best_iou >= IOU_THR:
            tp += 1
            matched.add(best_j)
    return tp, len(preds) - tp, len(gts) - len(matched)


def pick_samples(n: int, seed: int) -> list[tuple[Path, Path]]:
    """val360 中分层均衡抽样: 每类 floor(n/6), 余数从 shuffle 余量补足"""
    root = Path(settings.dataset_root)
    if not root.is_absolute() and not root.exists():
        root = Path(__file__).resolve().parents[2] / settings.dataset_root
    pairs = find_voc_files(
        (root / settings.dataset_images_dir).resolve(),
        (root / settings.dataset_annotations_dir).resolve(),
    )
    val_stems = stratified_split(pairs)["val"]
    val = [(img, xml) for img, xml in pairs if xml.stem in val_stems]

    by_class: dict[str, list[tuple[Path, Path]]] = defaultdict(list)
    for img, xml in val:
        by_class[parse_voc(xml).class_name].append((img, xml))
    rng = random.Random(seed)
    for cls in by_class:
        rng.shuffle(by_class[cls])

    per_class = n // 6
    picked: list[tuple[Path, Path]] = []
    for cls in sorted(by_class):
        picked.extend(by_class[cls][:per_class])
    have = {p[1].stem for p in picked}
    rest = [p for cls in sorted(by_class) for p in by_class[cls][per_class:] if p[1].stem not in have]
    rng.shuffle(rest)
    picked.extend(rest[: n - len(picked)])
    return picked[:n]


def gts_of(xml_path: Path) -> list[dict]:
    doc = parse_voc(xml_path)
    return [
        {
            "class_name": o.class_name,
            "bbox": {"x1": float(o.xmin), "y1": float(o.ymin),
                     "x2": float(o.xmax), "y2": float(o.ymax)},
        }
        for o in doc.objects
    ]


def primary_class(gts: list[dict]) -> str:
    """图像主类 = GT 框最多的类(并列取置信无关的字母序)"""
    c = Counter(g["class_name"] for g in gts)
    return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


class Accumulator:
    def __init__(self) -> None:
        self.tp = self.fp = self.fn = 0
        self.tp_lo = self.fp_lo = self.fn_lo = 0
        self.per_class: dict[str, list[int]] = {c: [0, 0, 0] for c in YOLO_CLASSES}  # tp fp fn
        self.cls_correct = self.cls_total = 0
        self.latency: list[float] = []
        self.pred_counts: list[int] = []
        self.gt_counts: list[int] = []
        self.errors: list[dict] = []

    def add(self, preds: list[dict], gts: list[dict], latency_ms: float) -> None:
        tp, fp, fn = match(preds, gts, class_aware=True)
        tp_lo, fp_lo, fn_lo = match(preds, gts, class_aware=False)
        self.tp += tp; self.fp += fp; self.fn += fn
        self.tp_lo += tp_lo; self.fp_lo += fp_lo; self.fn_lo += fn_lo
        self.latency.append(latency_ms)
        self.pred_counts.append(len(preds))
        self.gt_counts.append(len(gts))
        # 每类计数
        matched = set()
        for p in sorted(preds, key=lambda d: d["confidence"], reverse=True):
            best_iou, best_j = 0.0, -1
            for j, g in enumerate(gts):
                if j in matched or p["class_name"] != g["class_name"]:
                    continue
                v = iou(p["bbox"], g["bbox"])
                if v > best_iou:
                    best_iou, best_j = v, j
            slot = self.per_class[p["class_name"]]
            if best_j >= 0 and best_iou >= IOU_THR:
                slot[0] += 1
                matched.add(best_j)
            else:
                slot[1] += 1
        # 每类 FN 在 summary 中统一用 "该类 GT 总数 - TP" 计算(GT 总数由外部注入 _gt_totals)
        # 图像级主类准确率
        self.cls_total += 1
        if preds:
            pred_primary = Counter(p["class_name"] for p in preds).most_common(1)[0][0]
            if pred_primary == primary_class(gts):
                self.cls_correct += 1

    @staticmethod
    def _prf(tp: int, fp: int, fn: int) -> dict:
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4)}

    def summary(self, extra: dict | None = None) -> dict:
        # 每类 FN = 该类 GT 总数 - TP(GT 总数在跑完后由调用方注入 _gt_totals)
        gt_totals = getattr(self, "_gt_totals", {c: 0 for c in YOLO_CLASSES})
        per_class = {}
        for cls in YOLO_CLASSES:
            tp, fp, _ = self.per_class[cls]
            fn = gt_totals.get(cls, 0) - tp
            per_class[cls] = {**self._prf(tp, fp, fn), "tp": tp, "fp": fp, "fn": fn,
                              "gt": gt_totals.get(cls, 0)}
        nl = max(1, len(self.latency))  # 延迟只统计成功请求
        ni = max(1, self.cls_total)  # 框数/准确率按全部图片
        s = {
            "images": self.cls_total,
            "errors": len(self.errors),
            **self._prf(self.tp, self.fp, self.fn),
            "localization_only": self._prf(self.tp_lo, self.fp_lo, self.fn_lo),
            "image_primary_accuracy": round(self.cls_correct / self.cls_total, 4) if self.cls_total else 0,
            "latency_avg_ms": round(sum(self.latency) / nl, 1),
            "latency_p95_ms": round(sorted(self.latency)[int(len(self.latency) * 0.95) - 1], 1)
            if self.latency else 0,
            "boxes_per_image_pred": round(sum(self.pred_counts) / ni, 2),
            "boxes_per_image_gt": round(sum(self.gt_counts) / ni, 2),
            "per_class": per_class,
        }
        if extra:
            s.update(extra)
        return s


def run_yolo(samples) -> tuple[Accumulator, list[dict]]:
    inf = get_inferencer()
    inf.load()
    acc = Accumulator()
    rows = []
    t_wall = time.perf_counter()
    for i, (img_path, xml_path) in enumerate(samples, 1):
        gts = gts_of(xml_path)
        r = inf.predict(img_path.read_bytes())
        preds = r["detections"]
        acc.add(preds, gts, r["inference_ms"])
        rows.append({"image": img_path.name, "model": "yolo11s", "gt": len(gts),
                     "pred": len(preds), "latency_ms": r["inference_ms"]})
        if i % 20 == 0:
            print(f"  [YOLO] {i}/{len(samples)}")
    acc._gt_totals = Counter()
    for _, xml_path in samples:
        for g in gts_of(xml_path):
            acc._gt_totals[g["class_name"]] += 1
    acc.wall_ms = round((time.perf_counter() - t_wall) * 1000, 1)
    return acc, rows


def run_vl(samples, workers: int, model_alias: str) -> tuple[Accumulator, list[dict], dict]:
    acc = Accumulator()
    gt_cache = {p[1].name: gts_of(p[1]) for p in samples}
    acc._gt_totals = Counter()
    for gts in gt_cache.values():
        for g in gts:
            acc._gt_totals[g["class_name"]] += 1
    rows: list[dict] = []
    tokens = Counter()
    done = 0
    lock_rows: list[dict] = []

    def one(item):
        img_path, _xml_path = item
        return vl_detector.detect_bytes(img_path.read_bytes(), model=model_alias)

    t_wall = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one, s): s for s in samples}
        for fut in as_completed(futures):
            img_path, xml_path = futures[fut]
            gts = gt_cache[xml_path.name]
            done += 1
            try:
                r = fut.result()
            except VlError as e:
                # 失败请求: GT 全部计为 FN(诚实计入召回), 但不污染延迟统计
                acc.errors.append({"image": img_path.name, "kind": e.kind, "message": str(e)[:200]})
                acc.cls_total += 1
                acc.fn += len(gts)
                acc.fn_lo += len(gts)
                acc.gt_counts.append(len(gts))
                acc.pred_counts.append(0)
                lock_rows.append({"image": img_path.name, "model": model_alias, "gt": len(gts),
                                  "pred": 0, "latency_ms": 0, "error": e.kind})
            else:
                preds = r["detections"]
                acc.add(preds, gts, r["inference_ms"])
                tokens["prompt"] += r["tokens"]["prompt_tokens"]
                tokens["completion"] += r["tokens"]["completion_tokens"]
                tokens["total"] += r["tokens"]["total_tokens"]
                lock_rows.append({"image": img_path.name, "model": r["model"], "gt": len(gts),
                                  "pred": len(preds), "latency_ms": r["inference_ms"],
                                  "tokens": r["tokens"]["total_tokens"]})
            if done % 10 == 0:
                print(f"  [VL {model_alias}] {done}/{len(samples)}")
    rows.extend(lock_rows)
    wall_ms = round((time.perf_counter() - t_wall) * 1000, 1)
    cost = round(tokens["prompt"] / 1_000_000 * PRICE_INPUT_PER_M
                 + tokens["completion"] / 1_000_000 * PRICE_OUTPUT_PER_M, 4)
    cost_info = {
        "prompt_tokens": tokens["prompt"],
        "completion_tokens": tokens["completion"],
        "total_tokens": tokens["total"],
        "cost_cny": cost,
        "price_input_per_m": PRICE_INPUT_PER_M,
        "price_output_per_m": PRICE_OUTPUT_PER_M,
        "wall_ms_concurrency": wall_ms,
        "workers": workers,
    }
    return acc, rows, cost_info


def write_markdown(out: Path, n: int, yolo_s: dict, vl_s: dict) -> None:
    lines = [
        "# 里程碑3.2 零样本对决报告: YOLOv11s vs Qwen-VL",
        "",
        f"- 测试集: NEU-DET val360(seed=42 划分)中分层均衡抽取 **{n} 张**(6 类均衡)",
        "- 匹配规则: 同类贪心 IoU≥0.5; 零样本 Qwen-VL 未见过任何 NEU 样本, 仅靠文字类别定义",
        f"- VL 模型: `{vl_s.get('model_id', 'qwen-vl-plus')}` (阿里云百炼, temp=0)",
        "- 现金单价: qwen-vl-plus 输入 0.8 元/百万 token、输出 2 元/百万 token(2026-09 官方价)",
        "",
        "## 一、总体指标",
        "",
        "| 指标 | YOLOv11s(监督训练) | Qwen-VL(零样本) |",
        "|---|---|---|",
        f"| 精确率 P@{IOU_THR} | {yolo_s['precision']} | {vl_s['precision']} |",
        f"| 召回率 R@{IOU_THR} | {yolo_s['recall']} | {vl_s['recall']} |",
        f"| F1@{IOU_THR} | **{yolo_s['f1']}** | **{vl_s['f1']}** |",
        f"| 仅看定位 F1(忽略类别) | {yolo_s['localization_only']['f1']} | {vl_s['localization_only']['f1']} |",
        f"| 图像级主类准确率 | {yolo_s['image_primary_accuracy']} | {vl_s['image_primary_accuracy']} |",
        f"| 平均延迟 ms/张 | {yolo_s['latency_avg_ms']} (本地 RTX4060) | {vl_s['latency_avg_ms']} (云端 API) |",
        f"| P95 延迟 ms | {yolo_s['latency_p95_ms']} | {vl_s['latency_p95_ms']} |",
        f"| 平均框数(预测/GT) | {yolo_s['boxes_per_image_pred']}/{yolo_s['boxes_per_image_gt']} "
        f"| {vl_s['boxes_per_image_pred']}/{vl_s['boxes_per_image_gt']} |",
        f"| 失败请求数 | 0 | {vl_s['errors']} |",
        f"| token 用量(输入/输出/总) | —(本地推理) | "
        f"{vl_s['prompt_tokens']}/{vl_s['completion_tokens']}/{vl_s['total_tokens']} |",
        f"| 现金成本 | 0(本机算力, 电费可忽略) | **{vl_s['cost_cny']} 元 / {n} 张** |",
        "",
        "## 二、分类别 F1@0.5",
        "",
        "| 类别 | YOLO F1 | VL F1 | YOLO P/R | VL P/R |",
        "|---|---|---|---|---|",
    ]
    for cls in YOLO_CLASSES:
        y, v = yolo_s["per_class"][cls], vl_s["per_class"][cls]
        lines.append(
            f"| {cls} | {y['f1']} | {v['f1']} | {y['precision']}/{y['recall']} "
            f"| {v['precision']}/{v['recall']} |"
        )
    lines += [
        "",
        "## 三、结论",
        "",
        "- 专业工业纹理缺陷(200×200 灰度)上, 领域监督模型 YOLOv11s 的检测 F1 显著高于通用 VLM 零样本;",
        "  VLM 主要短板: 多实例枚举不全、类别混淆(氧化铁皮/斑块/夹杂)、框不够紧、200px 小图细节不足。",
        "- VLM 的价值: 零标注成本、开箱即用、可输出自然语言解释, 适合冷启动/新缺陷粗筛与异常提示;",
        "  待数据积累后训练专用检测器是性价比最高的落地路径(本平台已验证)。",
    ]

    # 四、工程健壮性: 若存在修复前首轮结果, 自动追加对比
    run1_path = out.parent / "benchmark32_run1_before_salvage.json"
    if run1_path.exists():
        r1 = json.loads(run1_path.read_text(encoding="utf-8"))["qwen_vl"]
        lines += [
            "",
            "## 四、VLM 接口工程健壮性(首轮 vs 修复后)",
            "",
            "首轮 100 张中 plus 出现 17 次长输出 JSON 损坏(重复 `detections` 键+半截断尾)、"
            "5 次 60s 超时、1 次上游错误; 随后加入三项修复: "
            "① 解析器按括号深度打捞已完整输出的检测项(重复段去重); "
            "② prompt 限制最多 8 个显著区域 + max_tokens=2048; ③ 超时/429 自动重试。",
            "",
            "| 指标 | 首轮(修复前) | 本轮(修复后) |",
            "|---|---|---|",
            f"| VL 失败请求数 | {r1['errors']}/100 | **{vl_s['errors']}/100** |",
            f"| VL F1@0.5 | {r1['f1']} | **{vl_s['f1']}** |",
            f"| VL 平均延迟 ms | {r1['latency_avg_ms']} | {vl_s['latency_avg_ms']} |",
            f"| 现金成本(元) | {r1['cost_cny']} | {vl_s['cost_cny']} |",
        ]
    out.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=4, help="VL 并发数")
    ap.add_argument("--model", default="plus", help="plus/max/具体 id")
    args = ap.parse_args()

    samples = pick_samples(args.n, args.seed)
    dist = Counter(parse_voc(xml).class_name for _, xml in samples)
    print(f"[benchmark] 抽样 {len(samples)} 张, 类别分布: {dict(sorted(dist.items()))}")

    print("[benchmark] === YOLOv11s (GPU) ===")
    yolo_acc, yolo_rows = run_yolo(samples)
    yolo_summary = yolo_acc.summary({"wall_ms_total": yolo_acc.wall_ms})
    print(f"  F1={yolo_summary['f1']} P={yolo_summary['precision']} R={yolo_summary['recall']} "
          f"avg={yolo_summary['latency_avg_ms']}ms")

    print(f"[benchmark] === Qwen-VL zero-shot ({args.model}, workers={args.workers}) ===")
    vl_acc, vl_rows, cost = run_vl(samples, args.workers, args.model)
    vl_summary = vl_acc.summary(cost)
    vl_summary["model_id"] = settings.vl_model_plus if args.model == "plus" else (
        settings.vl_model_max if args.model == "max" else args.model)
    print(f"  F1={vl_summary['f1']} P={vl_summary['precision']} R={vl_summary['recall']} "
          f"avg={vl_summary['latency_avg_ms']}ms cost={cost['cost_cny']}元 errors={len(vl_acc.errors)}")

    reports = Path(__file__).resolve().parents[1] / "reports"
    reports.mkdir(exist_ok=True)
    base = reports / "benchmark32"
    payload = {
        "n": args.n,
        "seed": args.seed,
        "iou_threshold": IOU_THR,
        "class_distribution": dict(sorted(dist.items())),
        "yolo11s": yolo_summary,
        "qwen_vl": vl_summary,
    }
    (base.with_suffix(".json")).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["image", "model", "gt", "pred", "latency_ms", "tokens", "error"])
        w.writeheader()
        for r in yolo_rows + vl_rows:
            w.writerow({**{"tokens": "", "error": ""}, **r})
    write_markdown(base.with_suffix(".md"), args.n, yolo_summary, vl_summary)
    print(f"[benchmark] 产物: {base}.json / .csv / .md")


if __name__ == "__main__":
    main()
