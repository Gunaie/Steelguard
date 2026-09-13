"""阶段5.2: 推理接口阶梯压测(全链路 客户端→nginx→Java(JWT)→Python YOLO)

只压纯推理网关 POST /api/inference/detect(不落库、不建批), 验收线 P95 < 800ms。
仅依赖 httpx + 标准库(不 import torch/app), 可直接用 ai-service 镜像作压测客户端:

    docker run --rm --network steelguard_default \
      -v $PWD/ai-service/scripts:/app/scripts:ro \
      -v $PWD/ai-service/data/yolo/neu-det-yolo/images/train:/images:ro \
      -v $PWD/ai-service/reports:/reports \
      steelguard-ai-service:gpu \
      python scripts/load_test_detect.py --target http://frontend --image-dir /images \
        --levels 10,20,50 --per-level 500

产物: reports/loadtest_{mode}_{ts}.json + .md
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

ACCEPT_P95_MS = 800.0  # 方案文档验收线


def percentile(sorted_values: list[float], pct: float) -> float:
    """最近秩百分位(输入需已升序)"""
    if not sorted_values:
        return 0.0
    k = max(0, min(len(sorted_values) - 1, round(pct / 100.0 * len(sorted_values)) - 1))
    return sorted_values[k]


def login(client: httpx.Client, target: str, username: str, password: str) -> str:
    resp = client.post(
        f"{target}/api/auth/login",
        json={"username": username, "password": password},
        timeout=10.0,
    )
    resp.raise_for_status()
    body = resp.json()
    token = body.get("data", {}).get("token") or body.get("token")
    if not token:
        raise RuntimeError(f"登录响应无 token: {body}")
    return token


def load_images(image_dir: Path, pool_size: int) -> list[tuple[str, bytes]]:
    files = sorted(
        p for p in image_dir.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if not files:
        raise SystemExit(f"图片目录无可用图片: {image_dir}")
    random.seed(42)
    random.shuffle(files)
    picked = files[:pool_size]
    images: list[tuple[str, bytes]] = []
    for p in picked:
        images.append((p.name, p.read_bytes()))
    return images


def run_level(
    target: str,
    token: str,
    images: list[tuple[str, bytes]],
    concurrency: int,
    total: int,
) -> dict:
    """单档压测, 返回延迟分布与错误统计"""
    latencies_ms: list[float] = []
    status_counter: dict[str, int] = {}
    errors: list[str] = []
    counts: list[int] = []
    # 每线程独立 Client(连接池复用, base 级别并行)
    tls = httpx.Limits(max_connections=concurrency + 4, max_keepalive_connections=concurrency)

    def one(idx: int) -> tuple[float, int, str, int]:
        name, blob = images[idx % len(images)]
        with httpx.Client(base_url=target, timeout=httpx.Timeout(30.0, connect=5.0), limits=tls) as cli:
            t0 = time.perf_counter()
            try:
                r = cli.post(
                    "/api/inference/detect",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"file": (name, blob, "image/jpeg")},
                )
                ms = (time.perf_counter() - t0) * 1000
                det_count = -1
                if r.status_code == 200:
                    try:
                        det_count = int(r.json().get("data", {}).get("count", -1))
                    except Exception:  # noqa: BLE001
                        pass
                return ms, r.status_code, "" if r.status_code < 400 else r.text[:200], det_count
            except Exception as exc:  # noqa: BLE001
                return (time.perf_counter() - t0) * 1000, 0, f"{type(exc).__name__}: {exc}", -1

    wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(one, i) for i in range(total)]
        done = 0
        for fut in as_completed(futures):
            ms, status, err, det_count = fut.result()
            latencies_ms.append(ms)
            status_counter[str(status)] = status_counter.get(str(status), 0) + 1
            if err:
                errors.append(err)
            if det_count >= 0:
                counts.append(det_count)
            done += 1
            if done % 100 == 0:
                print(f"    [{concurrency} 并发] {done}/{total} 已完成", flush=True)
    wall_s = time.perf_counter() - wall_start

    ordered = sorted(latencies_ms)
    ok = status_counter.get("200", 0)
    return {
        "concurrency": concurrency,
        "total": total,
        "success": ok,
        "errors": total - ok,
        "status_codes": status_counter,
        "qps": round(total / wall_s, 2),
        "wall_seconds": round(wall_s, 2),
        "p50_ms": round(percentile(ordered, 50), 1),
        "p90_ms": round(percentile(ordered, 90), 1),
        "p95_ms": round(percentile(ordered, 95), 1),
        "p99_ms": round(percentile(ordered, 99), 1),
        "max_ms": round(ordered[-1], 1),
        "mean_ms": round(sum(ordered) / len(ordered), 1),
        "avg_detections": round(sum(counts) / len(counts), 2) if counts else None,
        "error_samples": errors[:3],
    }


def write_markdown(path: Path, meta: dict, levels: list[dict]) -> None:
    accept_level = next((l for l in levels if l["concurrency"] == 20), levels[1] if len(levels) > 1 else levels[0])
    passed = accept_level["p95_ms"] < ACCEPT_P95_MS and accept_level["errors"] == 0
    lines = [
        "# 推理接口阶梯压测报告",
        "",
        f"- 时间: {meta['timestamp']}",
        f"- 目标: `{meta['target']}`(全链路 nginx→Java/JWT→Python YOLO, {meta['mode']} 模式)",
        f"- 接口: `POST /api/inference/detect`(纯推理网关, 不落库)",
        f"- 图片池: {meta['image_count']} 张 NEU-DET 随机轮换; 每档预热 {meta['warmup']} 请求",
        f"- 并发档: {meta['levels']}, 每档 {meta['per_level']} 请求",
        "",
        "## 结果汇总",
        "",
        "| 并发 | 总请求 | 成功 | 错误 | QPS | P50(ms) | P90(ms) | P95(ms) | P99(ms) | Max(ms) | 平均框数 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for l in levels:
        lines.append(
            f"| {l['concurrency']} | {l['total']} | {l['success']} | {l['errors']} | {l['qps']} | "
            f"{l['p50_ms']} | {l['p90_ms']} | **{l['p95_ms']}** | {l['p99_ms']} | {l['max_ms']} | {l['avg_detections']} |"
        )
    lines += [
        "",
        "## 验收结论",
        "",
        f"- 判据: 20 并发档 P95 < {ACCEPT_P95_MS:.0f}ms 且 0 错误",
        f"- 实测: P95 = **{accept_level['p95_ms']}ms**, 错误 = {accept_level['errors']}",
        f"- 结论: {'✅ 达标' if passed else '❌ 未达标'}",
        "",
        "## 状态码分布",
        "",
    ]
    for l in levels:
        lines.append(f"- {l['concurrency']} 并发: {json.dumps(l['status_codes'], ensure_ascii=False)}")
    if any(l["error_samples"] for l in levels):
        lines += ["", "## 错误样例", ""]
        for l in levels:
            for s in l["error_samples"][:2]:
                lines.append(f"- [{l['concurrency']}] {s}")
    lines += [
        "",
        "## 架构说明(容量边界)",
        "",
        "- Python 侧 YOLO 推理持有进程内全局锁(`YoloInferencer._lock`), 同卡请求严格串行;",
        "  并发升高时延迟主要来自锁排队而非单请求推理变慢, P95 随并发近似线性抬升属预期。",
        "- 进一步扩容方向: 多请求 batch 合并推理 / 多 GPU 副本 + 轮询 / ONNX TensorRT。",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="SteelGuard 推理接口阶梯压测")
    ap.add_argument("--target", default="http://frontend", help="全链路入口(容器网络用服务名)")
    ap.add_argument("--image-dir", required=True)
    ap.add_argument("--levels", default="10,20,50", help="逗号分隔并发档")
    ap.add_argument("--per-level", type=int, default=500)
    ap.add_argument("--warmup", type=int, default=30)
    ap.add_argument("--pool", type=int, default=200, help="内存图片池大小")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="admin123")
    ap.add_argument("--mode", default="gpu", choices=["gpu", "cpu"])
    ap.add_argument("--out", default="/reports")
    args = ap.parse_args()

    images = load_images(Path(args.image_dir), args.pool)
    print(f"图片池就绪: {len(images)} 张; 目标 {args.target}", flush=True)

    with httpx.Client() as client:
        token = login(client, args.target, args.user, args.password)
    print(f"登录成功, 开始预热 {args.warmup} 请求 ...", flush=True)
    warm = run_level(args.target, token, images, 4, args.warmup)
    print(f"预热完成: P95={warm['p95_ms']}ms QPS={warm['qps']}", flush=True)

    levels: list[dict] = []
    for c in (int(x) for x in args.levels.split(",")):
        print(f"=== 压测档: {c} 并发 × {args.per_level} ===", flush=True)
        levels.append(run_level(args.target, token, images, c, args.per_level))
        l = levels[-1]
        print(
            f"    QPS={l['qps']} P50={l['p50_ms']} P95={l['p95_ms']} "
            f"P99={l['p99_ms']} errors={l['errors']}",
            flush=True,
        )

    ts = time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "timestamp": ts,
        "target": args.target,
        "mode": args.mode,
        "image_count": len(images),
        "warmup": args.warmup,
        "levels": args.levels,
        "per_level": args.per_level,
    }
    (out_dir / f"loadtest_{args.mode}_{ts}.json").write_text(
        json.dumps({"meta": meta, "levels": levels}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path = out_dir / f"loadtest_{args.mode}_{ts}.md"
    write_markdown(md_path, meta, levels)
    print(f"报告已写入: {md_path}", flush=True)

    accept = next((l for l in levels if l["concurrency"] == 20), None)
    if accept and (accept["p95_ms"] >= ACCEPT_P95_MS or accept["errors"] > 0):
        print(f"!! 20 并发档未达标: P95={accept['p95_ms']}ms errors={accept['errors']}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
