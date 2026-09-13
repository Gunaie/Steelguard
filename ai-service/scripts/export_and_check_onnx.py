"""阶段3: 导出 best.pt -> ONNX, 并校验 PT 与 ONNX 推理结果一致性

用法(在 ai-service 目录):
    uv run python scripts/export_and_check_onnx.py
    uv run python scripts/export_and_check_onnx.py --samples 20 --conf 0.25

一致性判定(同一张图, PT(GPU/CPU) vs ONNX(onnxruntime)):
  - 检出框数量一致
  - 每个 PT 框能在 ONNX 结果中找到同类、IoU>=0.95 的匹配框
  - 匹配框置信度差 <= 0.03
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path

# 禁止 ultralytics 自动 pip 安装(ONNX 用 CPU provider, 不需要 onnxruntime-gpu)
os.environ["YOLO_AUTOINSTALL"] = "false"
# 配置目录重定向到项目内, 避免写 %APPDATA%(部分环境无权限刷 ERROR 噪声)
os.environ["YOLO_CONFIG_DIR"] = str(Path(__file__).resolve().parents[1] / ".ultralytics")

# 允许直接以脚本方式运行(scripts/ 在包外)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402


def find_data_root() -> Path:
    """探测 NEU-DET IMAGES 目录(支持从 ai-service/ 或项目根运行)"""
    candidates = [
        Path(settings.dataset_root) / settings.dataset_images_dir,
        Path(__file__).resolve().parents[2] / "data" / "raw" / "NEU-DET" / "IMAGES",
        Path.cwd() / "data" / "raw" / "NEU-DET" / "IMAGES",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"找不到 NEU-DET IMAGES 目录, 已尝试: {candidates}")


def iou(box_a: dict, box_b: dict) -> float:
    """两个 xyxy 框的 IoU"""
    ax1, ay1, ax2, ay2 = box_a["x1"], box_a["y1"], box_a["x2"], box_a["y2"]
    bx1, by1, bx2, by2 = box_b["x1"], box_b["y1"], box_b["x2"], box_b["y2"]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0


def match_dets(pt_dets: list[dict], onnx_dets: list[dict], iou_thr: float, conf_tol: float) -> list[str]:
    """贪心匹配两边的检测框, 返回不一致原因列表(空列表=完全一致)"""
    problems: list[str] = []
    if len(pt_dets) != len(onnx_dets):
        problems.append(f"框数量不一致 pt={len(pt_dets)} onnx={len(onnx_dets)}")

    used: set[int] = set()
    for pd in pt_dets:
        best_j, best_iou = -1, iou_thr
        for j, od in enumerate(onnx_dets):
            if j in used or od["class_id"] != pd["class_id"]:
                continue
            v = iou(pd["bbox"], od["bbox"])
            if v >= best_iou:
                best_j, best_iou = j, v
        if best_j < 0:
            problems.append(
                f"PT 框 {pd['class_name']} conf={pd['confidence']} 在 ONNX 结果中无 IoU>={iou_thr} 的同类匹配"
            )
            continue
        used.add(best_j)
        conf_diff = abs(pd["confidence"] - onnx_dets[best_j]["confidence"])
        if conf_diff > conf_tol:
            problems.append(
                f"{pd['class_name']} 匹配框置信度差 {conf_diff:.4f} > {conf_tol}"
            )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="导出 ONNX 并校验 PT/ONNX 一致性")
    parser.add_argument("--samples", type=int, default=12, help="抽样图片数(每类至少 1 张)")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--iou-thr", type=float, default=0.95)
    parser.add_argument("--conf-tol", type=float, default=0.03)
    args = parser.parse_args()

    from ultralytics import YOLO

    weights = Path(settings.yolo_weights)
    if not weights.exists():
        raise FileNotFoundError(f"权重不存在: {weights}")
    onnx_path = weights.with_suffix(".onnx")

    # 1) 导出
    print(f"[1/3] 导出 ONNX: {weights} -> {onnx_path} (imgsz={settings.yolo_imgsz})")
    model_pt = YOLO(str(weights))
    model_pt.export(
        format="onnx",
        imgsz=settings.yolo_imgsz,
        opset=12,
        simplify=True,
        dynamic=False,
    )
    if not onnx_path.exists():
        raise FileNotFoundError(f"导出后未找到 {onnx_path}")
    print(f"      ONNX 大小: {onnx_path.stat().st_size / 1024 / 1024:.1f} MB")

    # 2) 抽样(6 类各取 1 张保底, 其余随机补足)
    images_dir = find_data_root()
    all_imgs = sorted(images_dir.glob("*.jpg"))
    must: list[Path] = []
    for prefix in ("crazing_1", "inclusion_1", "patches_1", "pitted_surface_1", "rolled-in_scale_1", "scratches_1"):
        p = images_dir / f"{prefix}.jpg"
        if p.exists():
            must.append(p)
    rest = [p for p in all_imgs if p not in must]
    rnd = random.Random(42)
    rnd.shuffle(rest)
    sample_paths = (must + rest)[: max(args.samples, len(must))]
    print(f"[2/3] 抽样 {len(sample_paths)} 张图片做一致性比对")

    # 3) PT vs ONNX 逐张比对(PT 走 GPU, ONNX 强制 CPU provider)
    from app.inference.yolo_infer import YOLO_CLASSES, parse_detections, resolve_device

    # 导出后的实例重新加载, 保证比对环境干净
    model_pt = YOLO(str(weights))
    pt_device = resolve_device(settings.model_device)
    model_onnx = YOLO(str(onnx_path), task="detect")

    def infer(model, img_path: Path, device: str) -> list[dict]:
        res = model.predict(
            str(img_path),
            device=device,
            imgsz=settings.yolo_imgsz,
            conf=args.conf,
            iou=settings.yolo_iou,
            verbose=False,
        )[0]
        names = {int(k): str(v) for k, v in res.names.items()}
        h, w = res.orig_shape
        return parse_detections(res.boxes, names, w, h)

    bad = 0
    for p in sample_paths:
        pt_dets = infer(model_pt, p, pt_device)
        onnx_dets = infer(model_onnx, p, "cpu")
        problems = match_dets(pt_dets, onnx_dets, args.iou_thr, args.conf_tol)
        status = "OK " if not problems else "DIFF"
        print(f"  [{status}] {p.name}: pt={len(pt_dets)} onnx={len(onnx_dets)}")
        for msg in problems:
            bad += 1
            print(f"         - {msg}")

    if bad:
        print(f"[3/3] 一致性校验失败: {bad} 处差异")
        return 1

    print(
        f"[3/3] 一致性校验通过 ✓ {len(sample_paths)} 张图, "
        f"IoU>={args.iou_thr}, 置信度容差 {args.conf_tol}, 类别顺序 {YOLO_CLASSES}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
