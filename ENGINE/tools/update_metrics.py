#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_metrics.py —— 增量更新节点使用度量表(metrics.json)
================================================================
给 metrics.json 里某个节点累加一次使用记录(调用/字数/token/返工),并盖上时间戳。
数值只增不减(累计型);metrics.json 的"行结构"由 workflow_map.py 维护,本脚本只写数值。

用法(agent 请只看这段说明和 metrics_使用说明.md,不必读源码):
    python3 ENGINE/tools/update_metrics.py --node <节点名或路径> [--calls N] [--chars N] [--tokens N] [--rework N] [--note "备注"]

参数:
    --node    必填。节点的中文名(如 正文生成)或相对路径(如 ENGINE/prompts/正文生成.md)。
    --calls   本次调用次数增量(通常写 1)。默认 0。
    --chars   本次产出/修改的字数增量。默认 0。
    --tokens  本次 token 消耗增量。默认 0。
    --rework  本次返工/重跑次数增量。默认 0。
    --note    覆盖写入该节点备注(可选)。
    --list    只列出所有节点名,不改动。

示例:
    # 正文生成 跑了一次,产出 3200 字,耗 15000 token
    python3 ENGINE/tools/update_metrics.py --node 正文生成 --calls 1 --chars 3200 --tokens 15000
    # 独立正文自查 判定必须修,导致一次返工
    python3 ENGINE/tools/update_metrics.py --node 自查修正 --calls 1 --chars 600 --tokens 4000 --rework 1
"""
import os, sys, json, argparse, datetime, subprocess

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
METRICS_PATH = os.path.join(TOOLS_DIR, "metrics.json")
MAP_SCRIPT = os.path.join(TOOLS_DIR, "workflow_map.py")
ENGINE_ROOT = os.path.dirname(os.path.dirname(TOOLS_DIR))


def sync_map():
    """写完 metrics.json 后自动重跑 workflow_map.py,把新数值刷进 graph.json + workflow_map.html。
    数据面板是静态快照(数值在跑 map 时被内嵌),只写 metrics.json 面板不会变——所以这里自动补上这步,
    杜绝"上报了却忘了重跑 map、面板一直停在旧值"的坑。失败不致命(退化成提示手动跑)。"""
    try:
        r = subprocess.run([sys.executable, MAP_SCRIPT],
                           capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            # 从 map 的控制台体检里捞出孤儿/断链/循环那几行做个一句话回显
            tail = [ln for ln in r.stdout.splitlines()
                    if any(k in ln for k in ("孤儿", "断链", "循环", "节点"))]
            print("✓ 已自动刷新数据面板(graph.json + workflow_map.html)")
            for ln in tail:
                print("   " + ln.strip())
            return True
        print("⚠ 自动刷新数据面板失败(workflow_map.py 报错),请手动跑一次 workflow_map.py:")
        print((r.stderr or r.stdout or "").strip()[:500])
    except Exception as e:
        print(f"⚠ 自动刷新数据面板未执行({e}),请手动跑一次 workflow_map.py。")
    return False

# CLI 参数 → metrics.json 里的中文字段
FIELD_MAP = {"calls": "调用次数", "chars": "累计字数", "tokens": "累计token", "rework": "返工次数"}


def load():
    try:
        with open(METRICS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {"nodes": {}}


def resolve(data, key):
    """把 --node 的值解析成 metrics.json 里的 rel 键。支持:精确路径 / 中文名 / 文件名主干。"""
    rows = data.get("nodes", {})
    if key in rows:
        return key
    cands = []
    for rel, r in rows.items():
        stem = os.path.splitext(os.path.basename(rel))[0]
        if key == r.get("title") or key == stem:
            cands.append(rel)
    if len(cands) == 1:
        return cands[0]
    if len(cands) > 1:
        sys.exit("节点名有歧义,匹配到多个,请改用完整相对路径:\n  " + "\n  ".join(cands))
    return None


def main():
    ap = argparse.ArgumentParser(add_help=True, description="增量更新 metrics.json")
    ap.add_argument("--node")
    ap.add_argument("--calls", type=int, default=0)
    ap.add_argument("--chars", type=int, default=0)
    ap.add_argument("--tokens", type=int, default=0)
    ap.add_argument("--rework", type=int, default=0)
    ap.add_argument("--note")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--no-sync", action="store_true",
                    help="只写 metrics.json、不自动刷新数据面板(批量连报时用,最后再手动跑一次 workflow_map.py)")
    args = ap.parse_args()

    data = load()
    rows = data.setdefault("nodes", {})

    if args.list:
        for rel in sorted(rows):
            print(f"{rows[rel].get('title',''):20} {rel}")
        return

    if not args.node:
        ap.print_help()
        sys.exit("\n错误:必须用 --node 指定节点。")

    rel = resolve(data, args.node)
    if rel is None:
        # 行不存在:若磁盘上有对应文件就新建一行,否则报错
        guess = None
        for base in ("ENGINE/prompts", "ENGINE/knowledge", "ENGINE/templates", "ENGINE", ""):
            p = os.path.join(ENGINE_ROOT, base, args.node if args.node.endswith(".md") else args.node + ".md")
            if os.path.exists(p):
                guess = os.path.relpath(p, ENGINE_ROOT).replace("\\", "/"); break
        if guess is None:
            sys.exit(f"找不到节点 '{args.node}'。用 --list 看所有节点名,或先跑 workflow_map.py 对齐行。")
        rel = guess
        rows[rel] = {v: 0 for v in FIELD_MAP.values()}
        rows[rel].update({"末次更新": "", "备注": "", "title": os.path.splitext(os.path.basename(rel))[0]})

    row = rows[rel]
    for f in FIELD_MAP.values():
        row.setdefault(f, 0)
    before = {f: row[f] for f in FIELD_MAP.values()}
    for arg, field in FIELD_MAP.items():
        row[field] += getattr(args, arg)
    if args.note is not None:
        row["备注"] = args.note
    row["末次更新"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    with open(METRICS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✓ 已更新 [{row.get('title','')}] {rel}")
    for arg, field in FIELD_MAP.items():
        inc = getattr(args, arg)
        if inc:
            print(f"    {field}: {before[field]} → {row[field]}  (+{inc})")
    print(f"    末次更新: {row['末次更新']}")

    # ★ 默认自动把新数值刷进数据面板(graph.json + html);--no-sync 时才退回手动
    if args.no_sync:
        print("提示:--no-sync 已跳过刷新;批量上报完记得手动跑一次 workflow_map.py 刷面板。")
    else:
        sync_map()


if __name__ == "__main__":
    main()
