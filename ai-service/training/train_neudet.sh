#!/bin/bash
# SteelGuard 阶段2: NEU-DET YOLOv11s 训练脚本(AutoDL / 任意带 GPU 的 Linux)
#
# 前提:
#   1. 已选镜像 PyTorch 2.3 + Python 3.10 + CUDA 12.1(测试通过的稳妥组合)
#   2. neu-det-yolo.zip 与本脚本放在同一目录(建议 /root/autodl-tmp/), 已 unzip
#      即目录结构:
#        /root/autodl-tmp/neu-det-yolo/{data.yaml,images,labels,splits.txt}
#        /root/autodl-tmp/train_neudet.sh
#   3. pip install ultralytics   (AutoDL 默认 pip 源已是国内镜像)
#
# 用法: bash train_neudet.sh
set -e

WORKDIR="$(cd "$(dirname "$0")" && pwd)"
DATA_YAML="$WORKDIR/neu-det-yolo/data.yaml"
RUN_NAME="neu-det-yolo11s"

echo "== GPU 信息 =="
nvidia-smi || { echo "未检测到 GPU"; exit 1; }

echo "== 安装 ultralytics =="
pip install -U "ultralytics>=8.3"

echo "== 快速校验数据集 =="
python - "$DATA_YAML" <<'PY'
import sys
from pathlib import Path
import yaml
yaml_path = Path(sys.argv[1])
y = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
base = yaml_path.parent
for part in ("train", "val"):
    img_dir = base / "images" / part
    lbl_dir = base / "labels" / part
    n_img = len(list(img_dir.glob("*.jpg")))
    n_lbl = len(list(lbl_dir.glob("*.txt")))
    print(part, "images=", n_img, "labels=", n_lbl)
    assert n_img == n_lbl and n_img > 0
print("nc=", y["nc"], "names=", y["names"])
PY

echo "== 开始训练: YOLOv11s, 120 epochs, imgsz=224 =="
yolo detect train \
  model=yolo11s.pt \
  data="$DATA_YAML" \
  epochs=120 \
  imgsz=224 \
  batch=32 \
  device=0 \
  workers=8 \
  patience=30 \
  project="$WORKDIR/runs" \
  name="$RUN_NAME" \
  exist_ok=True

echo "== 用 best.pt 在 val(360 张干净原图)上复算 mAP =="
yolo detect val \
  model="$WORKDIR/runs/$RUN_NAME/weights/best.pt" \
  data="$DATA_YAML" \
  imgsz=224 \
  batch=32 \
  device=0

echo "== 训练产物 =="
ls -lh "$WORKDIR/runs/$RUN_NAME/weights/"
echo "best.pt 路径: $WORKDIR/runs/$RUN_NAME/weights/best.pt"
