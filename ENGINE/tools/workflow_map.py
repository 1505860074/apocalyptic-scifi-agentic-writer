#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工作流地图生成器  workflow_map.py
======================================

【作用】
扫描项目里所有 .md 文件(排除 BOOKS),读取每个文件顶部 YAML frontmatter 里声明的
依赖关系(pipeline_next / reads)与分组信息(工坊 / 服务),构建工作流的有向依赖图,产出:
  1) graph.json         —— 数据集(节点 + 边 + 体检结果),给任何工具二次使用
  2) workflow_map.html  —— 可视化(D3.js v7 力导向图):
        · 按【工坊】聚簇,每个工坊一个虚线框 + 工坊名标签(一眼看清哪个工坊有哪些节点)
        · 按【服务】定形状:○ 圆=服务小说(写书管线)  □ 方=服务工作流本身(维护工坊/文档)
        · 按【层】定颜色(prompt/knowledge/template...);节点可拖动、画布可缩放平移、hover 高亮
  3) 控制台体检报告      —— 孤儿 / 断链 / 循环 / 未加 frontmatter 的文件

【设计原则】
- Python 侧只用标准库(os / json / re)。可视化用 D3.js(CDN)。
- 全部逻辑在脚本里跑,agent 只负责"执行这个脚本",省 token。

【frontmatter 约定】(加在每个 md 文件最顶部)
---
node: 正文生成            # 唯一标识,一般=文件名主干
layer: prompt            # prompt | knowledge | template | root | meta —— 决定节点颜色
role: 步骤               # 自由文本,仅展示 + "总揽/维护工坊不算孤儿"的判断
工坊: 章节工坊           # 所属工坊 —— 决定聚在哪个虚线框里
服务: 小说               # 小说 | 工作流 —— 决定形状(圆/方)
pipeline_next:           # 管线下游(相对本文件的路径)
  - ./独立正文自查.md
reads:                   # 参考依赖(相对本文件的路径)
  - ../knowledge/铁律总纲.md
---

【用法】
    python3 workflow_map.py
输出写到脚本所在目录(ENGINE/tools/)与项目根。
"""

import os
import re
import json

# ── 路径:脚本在 ENGINE/tools/ 下;扫描范围=项目根(含 AGENTS.md/README.md),排除 BOOKS ──
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_ROOT = os.path.dirname(os.path.dirname(TOOLS_DIR))  # tools → ENGINE → 项目根
SKIP_DIRS = {"BOOKS", ".git", "__pycache__", ".claude", "ARCHIVE", "tools",
             "_用词优化留档", "_架构优化留档",
             "02-范文例库", "04-优化留档"}  # tools=脚本/说明; _用词优化留档/_架构优化留档=维护工坊/文风工坊的中间产物; 02-范文例库/04-优化留档=文风包内的数据(范文例子/跑档产物,含第三方版权,同 BOOKS 一样排除)


# ════════════════════════════════════════════════════════════════
# 1) frontmatter 解析(只认我们约定的那点 YAML 子集:标量 + 简单列表)
# ════════════════════════════════════════════════════════════════
def parse_frontmatter(text):
    """把文件顶部 --- ... --- 之间的内容解析成 dict。没有就返回 None。"""
    if not text.startswith("---"):
        return None
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
    if not m:
        return None
    body = m.group(1)
    data = {}
    cur_key = None
    for line in body.split("\n"):
        if not line.strip():
            continue
        item = re.match(r"^\s*-\s+(.*\S)\s*$", line)
        if item and cur_key is not None:
            data.setdefault(cur_key, [])
            if isinstance(data[cur_key], list):
                data[cur_key].append(item.group(1).strip())
            continue
        kv = re.match(r"^(\w+):\s*(.*)$", line)   # \w 含中文,故 工坊/服务 等中文 key 也能解析
        if kv:
            key, val = kv.group(1).strip(), kv.group(2).strip()
            data[key] = val if val else []
            cur_key = key
    return data


def infer_layer(rel_path):
    """没写 layer 时,从路径推断它属于哪一层。"""
    parts = rel_path.replace("\\", "/").split("/")
    if parts and parts[0] == "ENGINE":
        parts = parts[1:]                 # 去掉 ENGINE/ 前缀再判断
    if len(parts) <= 1:
        return "root"                     # 项目根 / ENGINE 顶层的散文档
    return {"prompts": "prompt", "knowledge": "knowledge",
            "templates": "template", "tools": "tool"}.get(parts[0], parts[0])


# ════════════════════════════════════════════════════════════════
# 2) 收集所有 md 节点
# ════════════════════════════════════════════════════════════════
def collect_nodes():
    nodes = {}
    for dirpath, dirs, files in os.walk(ENGINE_ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]  # 不下钻 BOOKS 等
        for fn in files:
            if not fn.endswith(".md"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, ENGINE_ROOT).replace("\\", "/")
            with open(full, encoding="utf-8") as f:
                text = f.read()
            fm = parse_frontmatter(text)
            nodes[rel] = {
                "rel": rel,
                "full": full,
                "layer": (fm.get("layer") if fm else None) or infer_layer(rel),
                "title": (fm.get("node") if fm else None) or os.path.splitext(fn)[0],
                "role": (fm.get("role") if fm else "") or "",
                "gongfang": (fm.get("工坊") if fm else "") or "",   # 所属工坊(聚簇用)
                "fuwu": (fm.get("服务") if fm else "") or "",        # 服务对象:小说 / 工作流(形状用)
                "jianjie": (fm.get("简介") if fm else "") or "",     # 一句话简介(选中时显示)
                "has_fm": fm is not None,
                "_fm": fm or {},
            }
    return nodes


# ════════════════════════════════════════════════════════════════
# 3) 从 frontmatter 建边(pipeline_next / reads)
# ════════════════════════════════════════════════════════════════
def build_edges(nodes):
    edges, broken = [], []
    for rel, info in nodes.items():
        fm = info["_fm"]
        if not fm:
            continue
        for key, etype in (("pipeline_next", "pipeline"), ("reads", "reads")):
            targets = fm.get(key) or []
            if isinstance(targets, str):
                targets = [targets]
            for t in targets:
                tgt_full = os.path.normpath(
                    os.path.join(os.path.dirname(info["full"]), t))
                tgt_rel = os.path.relpath(tgt_full, ENGINE_ROOT).replace("\\", "/")
                exists = os.path.exists(tgt_full)
                edges.append({"source": rel, "target": tgt_rel,
                              "type": etype, "raw": t, "exists": exists})
                if not exists:
                    broken.append({"source": rel, "raw": t, "type": etype})
    return edges, broken


# ════════════════════════════════════════════════════════════════
# 4) 体检:孤儿 / 循环
# ════════════════════════════════════════════════════════════════
def find_orphans(nodes, edges):
    """孤儿 = 没有任何入边。入口(root)、总揽,以及维护工坊/文档导航(按需手动触发的工具/文档)
    天然无人指向,不算孤儿。"""
    pointed_to = {e["target"] for e in edges}
    orphans = []
    for rel, info in nodes.items():
        if rel in pointed_to:
            continue
        if info["layer"] in ("root", "tool"):
            continue
        if info["gongfang"] in ("维护工坊", "文档导航"):
            continue
        if any(k in info["role"] for k in ("总揽", "入口")):
            continue
        orphans.append(rel)
    return orphans


def find_cycles(edges):
    """只在 pipeline 边上找环(管线本应无环)。DFS 三色法。"""
    adj = {}
    for e in edges:
        if e["type"] == "pipeline" and e["exists"]:
            adj.setdefault(e["source"], []).append(e["target"])
    WHITE, GRAY = 0, 1
    color, cycles, stack = {}, [], []

    def dfs(u):
        color[u] = GRAY
        stack.append(u)
        for v in adj.get(u, []):
            if color.get(v, WHITE) == GRAY:
                cycles.append(stack[stack.index(v):] + [v])
            elif color.get(v, WHITE) == WHITE:
                dfs(v)
        stack.pop()
        color[u] = 2

    for n in adj:
        if color.get(n, WHITE) == WHITE:
            dfs(n)
    return cycles


# ════════════════════════════════════════════════════════════════
# 4.5) 使用度量表(metrics.json):每个节点一行,记录调用/字数/token/返工等
#      —— 本脚本每次运行只"对齐行"(补新节点/标记已删/刷新标题),绝不改数值;
#         数值由 update_metrics.py 增量写入。这样 map 与度量互不打架。
# ════════════════════════════════════════════════════════════════
METRICS_PATH = os.path.join(TOOLS_DIR, "metrics.json")
METRIC_FIELDS = ["调用次数", "累计字数", "累计token", "返工次数"]  # 累计型数值,update 脚本累加


def sync_metrics(nodes):
    """对齐 metrics.json 的行,返回 {rel: 度量dict}。只动结构不动数值。"""
    try:
        with open(METRICS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError):
        data = {}
    data.setdefault("_说明", "工作流各节点使用度量,用于优化工作流。"
                    "数值由 ENGINE/tools/update_metrics.py 增量更新;"
                    "workflow_map.py 每次运行只对齐行(补新节点/标记已删/刷新标题),绝不改数值。")
    rows = data.setdefault("nodes", {})
    cur = set(nodes.keys())
    for rel, info in nodes.items():
        r = rows.setdefault(rel, {})
        for f in METRIC_FIELDS:            # 补齐字段(新增字段也能自动长出来)
            r.setdefault(f, 0)
        r.setdefault("末次更新", "")
        r.setdefault("备注", "")
        r["title"] = info["title"]         # 刷新展示信息(改名/换工坊也跟上)
        r["工坊"] = info["gongfang"]
        r["服务"] = info["fuwu"]
        r.pop("节点已删除", None)            # 现存 → 去掉删除标记
    for rel, r in rows.items():            # 已不存在的节点 → 标记删除(保留历史数值)
        if rel not in cur and isinstance(r, dict):
            r["节点已删除"] = True
    with open(METRICS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return rows


def node_metric(rel, metrics):
    """取某节点的度量 + 现算平均值(平均值不落库,避免过期)。"""
    m = metrics.get(rel, {}) if metrics else {}
    calls = m.get("调用次数", 0) or 0
    chars = m.get("累计字数", 0) or 0
    tok = m.get("累计token", 0) or 0
    return {"调用次数": calls, "累计字数": chars, "累计token": tok,
            "返工次数": m.get("返工次数", 0) or 0, "末次更新": m.get("末次更新", "") or "",
            "均字数": round(chars / calls) if calls else 0,
            "均token": round(tok / calls) if calls else 0}


# ════════════════════════════════════════════════════════════════
# 5) 产出 graph.json
# ════════════════════════════════════════════════════════════════
def write_json(nodes, edges, issues, metrics, path):
    data = {
        "nodes": [{"rel": i["rel"], "layer": i["layer"], "title": i["title"],
                   "role": i["role"], "工坊": i["gongfang"], "服务": i["fuwu"],
                   "简介": i["jianjie"], "度量": node_metric(i["rel"], metrics),
                   "has_frontmatter": i["has_fm"]}
                  for i in nodes.values()],
        "edges": [{"source": e["source"], "target": e["target"],
                   "type": e["type"], "exists": e["exists"]} for e in edges],
        "issues": issues,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ════════════════════════════════════════════════════════════════
# 6) 产出 workflow_map.html(D3.js v7 力导向图:按工坊聚簇 + 按服务定形状)
# ════════════════════════════════════════════════════════════════
def write_html(nodes, edges, issues, metrics, path):
    orphan_set = set(issues["orphans"])
    data = {
        "nodes": [{"id": i["rel"], "label": i["title"], "layer": i["layer"],
                   "role": i["role"], "gongfang": i["gongfang"], "fuwu": i["fuwu"],
                   "jianjie": i["jianjie"], "metrics": node_metric(i["rel"], metrics),
                   "orphan": i["rel"] in orphan_set}
                  for i in nodes.values()],
        "edges": [{"source": e["source"], "target": e["target"],
                   "type": e["type"], "exists": e["exists"]} for e in edges],
        "counts": {"nodes": len(nodes), "edges": len(edges),
                   "orphans": len(issues["orphans"]),
                   "broken": len(issues["broken_links"]),
                   "cycles": len(issues["cycles"])},
        "orphans": issues["orphans"],
        "broken": [b["source"] + " → " + b["raw"] for b in issues["broken_links"]],
    }
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = _HTML_TEMPLATE.replace("__GRAPH_DATA__", data_json)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>工作流地图</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
  html,body{width:100%;height:100%;overflow:hidden;}
  body{background:#0d1117;color:#c9d1d9;font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;font-size:13px;}
  svg{display:block;width:100%;height:100%;cursor:grab;}
  svg:active{cursor:grabbing;}
  #topbar{position:absolute;top:0;left:0;right:0;padding:8px 16px;background:rgba(13,17,23,.9);
    border-bottom:1px solid #21262d;display:flex;gap:20px;align-items:center;z-index:10;backdrop-filter:blur(8px);}
  #topbar b{color:#e6edf3;} #topbar .bad{color:#f85149;}
  #topbar .hint{margin-left:auto;color:#6e7681;font-size:11px;}
  #legend{position:absolute;top:52px;left:16px;background:rgba(22,27,34,.92);border:1px solid #30363d;
    border-radius:10px;padding:12px 16px;font-size:12px;line-height:1.85;z-index:10;backdrop-filter:blur(10px);max-height:calc(100vh - 80px);overflow:auto;}
  #legend h4{font-size:10px;color:#9eaab6;text-transform:uppercase;letter-spacing:1px;margin:8px 0 3px;}
  #legend h4:first-child{margin-top:0;}
  .lg{display:flex;align-items:center;gap:8px;}
  .dot{width:12px;height:12px;border-radius:50%;flex-shrink:0;}
  .sq{width:12px;height:12px;flex-shrink:0;}
  .ln{width:22px;height:0;flex-shrink:0;}
  #tooltip{position:absolute;pointer-events:none;background:rgba(22,27,34,.97);border:1px solid #30363d;
    border-radius:8px;padding:8px 12px;font-size:12px;max-width:340px;opacity:0;transition:opacity .12s;
    z-index:1000;box-shadow:0 8px 32px rgba(0,0,0,.6);}
  #tooltip.on{opacity:1;} .tt-name{font-weight:700;color:#e6edf3;} .tt-sub{color:#9eaab6;margin-top:2px;}
  #btnfit{position:absolute;top:52px;right:16px;background:rgba(22,27,34,.95);color:#c9d1d9;
    border:1px solid #30363d;border-radius:8px;padding:6px 14px;font-size:12px;cursor:pointer;z-index:10;}
  #btnfit:hover{background:#30363d;}
  #infopanel{position:absolute;bottom:16px;left:16px;max-width:380px;background:rgba(22,27,34,.96);
    border:1px solid #30363d;border-radius:10px;padding:12px 15px;font-size:12px;z-index:12;
    backdrop-filter:blur(10px);opacity:0;transform:translateY(8px);transition:opacity .15s,transform .15s;}
  #infopanel.on{opacity:1;transform:none;}
  #infopanel .ip-name{font-weight:700;color:#e6edf3;font-size:14px;}
  #infopanel .ip-meta{color:#9eaab6;margin-top:3px;}
  #infopanel .ip-desc{color:#c9d1d9;margin-top:8px;line-height:1.65;}
  #infopanel .ip-id{color:#6e7681;margin-top:8px;font-size:11px;word-break:break-all;}
  #infopanel .ip-metrics{margin-top:8px;padding-top:8px;border-top:1px solid #21262d;color:#adbac7;line-height:1.7;}
  #infopanel .ip-metrics b{color:#e6edf3;}
  #btndata{position:absolute;top:52px;right:104px;background:rgba(22,27,34,.95);color:#c9d1d9;
    border:1px solid #30363d;border-radius:8px;padding:6px 14px;font-size:12px;cursor:pointer;z-index:10;}
  #btndata:hover{background:#30363d;}
  #datapanel{position:absolute;top:90px;right:16px;bottom:16px;width:min(680px,92vw);background:rgba(22,27,34,.97);
    border:1px solid #30363d;border-radius:10px;padding:10px 12px 14px;z-index:20;backdrop-filter:blur(10px);
    display:none;flex-direction:column;box-shadow:0 12px 40px rgba(0,0,0,.6);}
  #datapanel.on{display:flex;}
  #datapanel h3{font-size:13px;color:#e6edf3;margin-bottom:6px;display:flex;align-items:center;gap:8px;}
  #datapanel .dp-hint{color:#6e7681;font-size:11px;font-weight:400;}
  #datapanel .dp-scroll{overflow:auto;flex:1;}
  #datapanel table{border-collapse:collapse;width:100%;font-size:12px;}
  #datapanel th,#datapanel td{padding:5px 8px;text-align:right;white-space:nowrap;border-bottom:1px solid #21262d;}
  #datapanel th:first-child,#datapanel td:first-child{text-align:left;position:sticky;left:0;background:#161b22;}
  #datapanel td:nth-child(2){text-align:left;}
  #datapanel thead th{position:sticky;top:0;background:#1c2128;color:#9eaab6;cursor:pointer;user-select:none;z-index:1;}
  #datapanel thead th:hover{color:#e6edf3;}
  #datapanel tbody tr:hover{background:rgba(88,166,255,.08);}
  #datapanel tbody tr.sel{background:rgba(242,204,96,.12);}
  #datapanel .dp-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle;}
  text.lbl{fill:#9eaab6;font-size:10px;pointer-events:none;paint-order:stroke;stroke:#0d1117;stroke-width:3px;}
  text.boxlbl{font-size:13px;font-weight:700;pointer-events:none;paint-order:stroke;stroke:#0d1117;stroke-width:4px;}
  #toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#238636;color:#fff;
    padding:8px 16px;border-radius:8px;font-size:13px;opacity:0;transition:opacity .2s;z-index:2000;
    pointer-events:none;box-shadow:0 6px 24px rgba(0,0,0,.5);max-width:80%;}
  #toast.on{opacity:1;}
</style></head><body>
<div id="topbar"></div>
<div id="legend"></div>
<button id="btnfit">重置视图</button>
<button id="btndata">数据面板</button>
<div id="datapanel"></div>
<div id="infopanel"></div>
<div id="tooltip"></div>
<svg id="svg"></svg>
<script>
"use strict";
var DATA = __GRAPH_DATA__;
var LAYER = {prompt:"#58a6ff",knowledge:"#3fb950",template:"#f0883e",root:"#8b949e",meta:"#d2a8ff",tool:"#8b949e"};
var LAYER_CN = {prompt:"prompt 步骤",knowledge:"knowledge 知识",template:"template 模板",root:"root 文档/入口",meta:"meta 维护工坊"};

// ── 工坊定义:只有这些"成框工坊"会画虚线框。成员摆成网格钉死在框里(见 layoutBoxed)。
//    知识库/模板库 刻意不列在这里 → 它们不单独成框,靠 reads 边被自由拉到"使用它们的节点"附近。
//    cx/cy=框中心(绝对虚拟坐标,布局与窗口大小无关,最终由"重置视图"自动缩放适配), cat=服务类别(决定框色调)。
//    坐标已排开留白:上排是写书主管线(立项→架构→故事弧),右侧章节工坊,下方是服务工作流的两个框。
var WORKSHOPS = [
  {name:"立项工坊",        cx:180,  cy:230, cat:"小说"},
  {name:"架构工坊",        cx:560,  cy:250, cat:"小说"},
  {name:"故事弧工坊",      cx:940,  cy:210, cat:"小说"},
  {name:"章节工坊",        cx:1330, cy:640, cat:"小说"},
  {name:"人工反馈修复工坊", cx:950,  cy:640, cat:"小说"},
  {name:"维护工坊",        cx:230,  cy:640, cat:"工作流"},
  {name:"文风工坊",        cx:1330, cy:1020, cat:"小说"},
  {name:"文档导航",        cx:620,  cy:700, cat:"工作流"}
];
var WS_BY_NAME = {}; WORKSHOPS.forEach(function(w){ WS_BY_NAME[w.name]=w; });
// 框的配色:服务小说=偏蓝, 服务工作流=偏灰(在"框"这一层再强化一次服务区分)
function boxStroke(cat){ return cat==="工作流" ? "#6e7681" : "#3a6ea5"; }
function boxFill(cat){   return cat==="工作流" ? "rgba(139,148,166,.05)" : "rgba(88,166,255,.045)"; }
function boxLabelColor(cat){ return cat==="工作流" ? "#8b949e" : "#6ea8ff"; }

// ── topbar ──
var c = DATA.counts;
document.getElementById("topbar").innerHTML =
  '<b>工作流地图</b>'
  + '<span>节点 <b>'+c.nodes+'</b></span><span>依赖边 <b>'+c.edges+'</b></span><span>工坊 <b>'+WORKSHOPS.length+'</b></span>'
  + '<span class="'+(c.orphans?'bad':'')+'">孤儿 <b>'+c.orphans+'</b></span>'
  + '<span class="'+(c.broken?'bad':'')+'">断链 <b>'+c.broken+'</b></span>'
  + '<span class="'+(c.cycles?'bad':'')+'">循环 <b>'+c.cycles+'</b></span>'
  + '<span class="hint">滚轮缩放 · 拖节点(松手固定) · 双击解除固定 · 拖背景平移 · 悬停高亮 · <b>点节点选中,Ctrl+C 复制名称+路径</b>　｜　由 ENGINE/tools/workflow_map.py 生成</span>';

// ── legend ──
var lg = '<h4>形状 = 服务对象</h4>'
  + '<div class="lg"><span class="dot" style="background:#58a6ff"></span>○ 圆 = 服务小说(写书管线)</div>'
  + '<div class="lg"><span class="sq" style="background:#161b22;border:1.5px solid #8b949e"></span>□ 方 = 服务工作流本身(维护工坊/文档)</div>'
  + '<h4>颜色 = 节点层</h4>';
["prompt","knowledge","template","meta","root"].forEach(function(k){
  lg += '<div class="lg"><span class="dot" style="background:'+LAYER[k]+'"></span>'+LAYER_CN[k]+'</div>';});
lg += '<h4>框 = 工坊</h4>'
  + '<div class="lg"><span class="sq" style="background:rgba(88,166,255,.045);border:1.5px dashed #3a6ea5"></span>写书工坊(服务小说)</div>'
  + '<div class="lg"><span class="sq" style="background:rgba(139,148,166,.05);border:1.5px dashed #6e7681"></span>工作流自身(服务工作流)</div>'
  + '<div class="lg" style="color:#6e7681;font-size:11px">知识/模板不单独成框,漂浮在使用它们的节点附近</div>'
  + '<h4>边</h4>'
  + '<div class="lg"><span class="ln" style="border-top:2px solid #58a6ff"></span>管线 pipeline_next</div>'
  + '<div class="lg"><span class="ln" style="border-top:2px dashed #8b949e"></span>参考 reads</div>'
  + '<h4>体检</h4>'
  + '<div class="lg"><span class="dot" style="background:none;border:2px solid #f85149"></span>孤儿(无人引用)</div>';
document.getElementById("legend").innerHTML = lg;

// ── 构造节点/边;断链目标(不存在)建红色 ghost 节点 ──
var nodeById = {};
DATA.nodes.forEach(function(n){ nodeById[n.id]=n; });
DATA.edges.forEach(function(e){
  if(!nodeById[e.target]){
    nodeById[e.target] = {id:e.target, label:"❌ "+e.target.split("/").pop(), layer:"broken",
                          gongfang:"", fuwu:"", orphan:false, ghost:true};
    DATA.nodes.push(nodeById[e.target]);
  }
});
var nodes = DATA.nodes, links = DATA.edges;

// degree 决定节点大小
var deg = {};
links.forEach(function(e){ deg[e.source]=(deg[e.source]||0)+1; deg[e.target]=(deg[e.target]||0)+1; });
function radius(d){ return 6 + Math.min((deg[d.id]||0)*1.2, 12); }
function fill(d){
  if(d.ghost) return "#f85149";
  if(d.fuwu==="工作流") return "#161b22";     // 服务工作流 = 灰描边方块,填充用深底
  return LAYER[d.layer]||"#8b949e";           // 服务小说 = 按层上色的实心
}
function stroke(d){
  if(d===selected) return "#f2cc60";
  if(d.orphan||d.ghost) return "#f85149";
  if(d.fuwu==="工作流") return "#8b949e";      // 灰描边
  return "rgba(255,255,255,.15)";
}
function strokeW(d){ return d===selected?4:(d.orphan?2.5:(d.fuwu==="工作流"?1.6:1)); }

var svg = d3.select("#svg");
var W = window.innerWidth, H = window.innerHeight;
var gRoot = svg.append("g");
var gBoxes = gRoot.append("g");   // 工坊框(画在最底层)
var gLinks = gRoot.append("g");
var gNodes = gRoot.append("g");

// 箭头
var defs = svg.append("defs");
[["arrow-pipe","#58a6ff"],["arrow-read","#8b949e"]].forEach(function(a){
  defs.append("marker").attr("id",a[0]).attr("viewBox","0 -5 10 10")
    .attr("refX",20).attr("refY",0).attr("markerWidth",7).attr("markerHeight",7).attr("orient","auto")
    .append("path").attr("d","M0,-4L10,0L0,4Z").attr("fill",a[1]);
});

// 缩放/平移
var zoom = d3.zoom().scaleExtent([0.1,8]).on("zoom",function(ev){ gRoot.attr("transform",ev.transform); });
svg.call(zoom).on("dblclick.zoom", null);        // 关掉双击缩放,双击留给"解除固定节点"
svg.on("click", function(){ selectNode(null); }); // 点背景 = 取消选中
var selected = null;

// ── 节点分两类:成框节点(网格排列并钉死在框里) vs 漂浮节点(知识库/模板库,靠 reads 边被拉到相关节点附近) ──
function isBoxed(d){ return !!WS_BY_NAME[d.gongfang]; }

// 成框工坊的成员表(排版/画框都用它)
var membersOf = {};
WORKSHOPS.forEach(function(w){ membersOf[w.name] = nodes.filter(function(n){return n.gongfang===w.name;}); });

// ── 全局管线拓扑序(rank):沿 pipeline 边做 Kahn 排序,让每个框内节点能按管线先后排列 ──
//    (此时 links 的 source/target 还是字符串 id;forceLink 尚未把它们替换成对象)
var PRANK = (function(){
  var ids = nodes.map(function(n){return n.id;});
  var idx = {}; ids.forEach(function(id,i){ idx[id]=i; });   // 原始顺序,用于稳定排序/兜底
  var padj = {}, indeg = {};
  ids.forEach(function(id){ indeg[id]=0; });
  links.forEach(function(e){
    if(e.type!=="pipeline") return;
    var s=e.source.id||e.source, t=e.target.id||e.target;
    (padj[s]=padj[s]||[]).push(t); indeg[t]=(indeg[t]||0)+1;
  });
  var q = ids.filter(function(id){return indeg[id]===0;}).sort(function(a,b){return idx[a]-idx[b];});
  var rank = {}, r = 0, seen = {};
  while(q.length){
    var u=q.shift(); if(seen[u])continue; seen[u]=1; rank[u]=r++;
    (padj[u]||[]).forEach(function(v){ if(indeg[v]>0)indeg[v]--; if(indeg[v]<=0 && !seen[v]) q.push(v); });
  }
  ids.forEach(function(id){ if(!(id in rank)) rank[id]=99999; });  // 不在管线上的(维护工坊/文档)排到最后
  return rank;
})();

// ── 把每个成框工坊的成员沿"等弧长阿基米德螺旋"摆开并钉死(fx/fy):
//    框大小随节点数自适应、成员也不会被 reads 边拖出框(修掉"两个节点占一大块"的 bug) ──
//    GAP/BSP 沿用老版全局螺旋的参数。
var GAP = 100, BSP = 24, BOXPAD = 26;      // GAP=相邻节点弧长间距, BSP=每弧度半径增量, BOXPAD=框内边距
function layoutBoxed(){
  WORKSHOPS.forEach(function(w){
    var ms = membersOf[w.name]; if(!ms.length) return;
    ms.sort(function(a,b){ return PRANK[a.id]-PRANK[b.id]; });   // 按管线先后排,螺旋从内(先)到外(后)
    // 生成等弧长螺旋点(相邻点弧长≈GAP,不随圈数变稀)
    var pts = [], th = GAP/BSP;
    for(var i=0;i<ms.length;i++){
      var r = BSP*th;
      pts.push([r*Math.cos(th), r*Math.sin(th)]);
      th += GAP/Math.max(r,1);
    }
    // 中心化:让螺旋质心落在框中心,框才对称贴合
    var mx=0, my=0; pts.forEach(function(p){mx+=p[0]; my+=p[1];}); mx/=pts.length; my/=pts.length;
    ms.forEach(function(d,i){
      d.fx = w.cx + pts[i][0] - mx;   // 钉死在螺旋点上
      d.fy = w.cy + pts[i][1] - my;
      d.x = d.fx; d.y = d.fy;
    });
  });
}
layoutBoxed();
// 漂浮节点(知识库/模板库):初始撒在中部空白区,之后由 reads 边 + 斥力自行找位置
nodes.forEach(function(n,i){
  if(isBoxed(n)) return;
  n.x = 820 + ((i*37) % 360 - 180);
  n.y = 450 + ((i*53) % 260 - 130);
});

var sim = d3.forceSimulation(nodes)
  .force("link", d3.forceLink(links).id(function(d){return d.id;})
     .distance(function(l){return l.type==="pipeline"?80:64;})
     .strength(function(l){return l.type==="pipeline"?0.15:0.08;}))
  // 成框节点已钉死,把它们的斥力调小,免得把漂浮节点甩太远
  .force("charge", d3.forceManyBody().strength(function(d){return isBoxed(d)?-40:-120;}).distanceMax(300))
  .force("collide", d3.forceCollide().radius(function(d){return radius(d)+10;}))
  // 只给漂浮节点很弱的中心引力,防止被斥力甩飞;成框节点钉死,不受这些力影响
  .force("cx", d3.forceX(820).strength(function(d){return isBoxed(d)?0:0.025;}))
  .force("cy", d3.forceY(450).strength(function(d){return isBoxed(d)?0:0.025;}));

// ── 工坊框(虚线圆角矩形 + 工坊名),每帧根据成员实际位置重算 ──
var box = gBoxes.selectAll("g.box").data(WORKSHOPS).enter().append("g").attr("class","box");
box.append("rect").attr("rx",14).attr("ry",14).attr("fill",function(w){return boxFill(w.cat);})
  .attr("stroke",function(w){return boxStroke(w.cat);}).attr("stroke-width",1.5).attr("stroke-dasharray","7,5");
box.append("text").attr("class","boxlbl").attr("fill",function(w){return boxLabelColor(w.cat);})
  .text(function(w){return w.name;});
function updateBoxes(){
  box.each(function(w){
    var ms = membersOf[w.name];
    var g = d3.select(this);
    if(!ms.length){ g.style("display","none"); return; }
    var pad = BOXPAD, x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
    ms.forEach(function(n){ if(n.x<x0)x0=n.x; if(n.y<y0)y0=n.y; if(n.x>x1)x1=n.x; if(n.y>y1)y1=n.y; });
    g.select("rect").attr("x",x0-pad).attr("y",y0-pad).attr("width",(x1-x0)+2*pad).attr("height",(y1-y0)+2*pad);
    g.select("text").attr("x",x0-pad+12).attr("y",y0-pad+20);
  });
}

// ── 边 ──
var link = gLinks.selectAll("line").data(links).enter().append("line")
  .attr("stroke", function(d){return d.type==="pipeline"?"#58a6ff":"#8b949e";})
  .attr("stroke-width", function(d){return d.type==="pipeline"?1.8:1;})
  .attr("stroke-dasharray", function(d){return d.type==="pipeline"?null:"6,4";})
  .attr("opacity", function(d){return d.type==="pipeline"?0.75:0.35;})
  .attr("marker-end", function(d){return d.type==="pipeline"?"url(#arrow-pipe)":"url(#arrow-read)";});

// ── 节点:服务小说=圆, 服务工作流/ghost=方 ──
var node = gNodes.selectAll("g").data(nodes).enter().append("g")
  .call(d3.drag().on("start",dS).on("drag",dD).on("end",dE));
node.each(function(d){
  var g = d3.select(this), r = radius(d);
  if(d.fuwu==="工作流"){                                  // 方块
    g.append("rect").attr("class","shape")
      .attr("x",-r).attr("y",-r).attr("width",2*r).attr("height",2*r).attr("rx",2);
  } else {                                                // 圆(含 ghost)
    g.append("circle").attr("class","shape").attr("r",r);
  }
});
node.select(".shape")
  .attr("fill", fill).attr("stroke", stroke).attr("stroke-width", strokeW).attr("cursor","pointer");
node.append("text").attr("class","lbl").attr("dx", function(d){return radius(d)+4;})
  .attr("dy","0.35em").text(function(d){return d.label;});

node.on("mouseover",function(ev,d){ hi(d,true); tip(ev,d); })
    .on("mousemove", mv)
    .on("mouseout", function(ev,d){ hi(d,false); document.getElementById("tooltip").classList.remove("on"); })
    .on("dblclick", function(ev,d){ ev.stopPropagation(); d.fx=null; d.fy=null; sim.alpha(0.3).restart(); })
    .on("click", function(ev,d){ ev.stopPropagation(); selectNode(d); });

sim.on("tick", function(){
  link.attr("x1",function(d){return d.source.x;}).attr("y1",function(d){return d.source.y;})
      .attr("x2",function(d){return d.target.x;}).attr("y2",function(d){return d.target.y;});
  node.attr("transform", function(d){return "translate("+d.x+","+d.y+")";});
  updateBoxes();
});

function dS(ev,d){ if(!ev.active) sim.alphaTarget(0.2).restart(); d.fx=d.x; d.fy=d.y; }
function dD(ev,d){ d.fx=ev.x; d.fy=ev.y; }
function dE(ev,d){ if(!ev.active) sim.alphaTarget(0); }  // 松手保留 fx/fy = 固定在拖到的位置

// ── 选中节点 + Ctrl+C 复制"名称 + 相对路径" ──
function esc(s){ return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function selectNode(d){
  selected = d;
  node.select(".shape").attr("stroke", stroke).attr("stroke-width", strokeW);
  var ip = document.getElementById("infopanel");
  if(d && !d.ghost){
    var meta = [d.fuwu?("服务"+d.fuwu):"", d.gongfang, d.layer, d.role].filter(Boolean).join(" · ");
    var m = d.metrics||{};
    var mrow = '<div class="ip-metrics">'
      + '调用 <b>'+(m.调用次数||0)+'</b> 次　·　产出/改 <b>'+(m.累计字数||0)+'</b> 字　·　token <b>'+(m.累计token||0)+'</b>　·　返工 <b>'+(m.返工次数||0)+'</b>'
      + '<br>均 <b>'+(m.均字数||0)+'</b> 字/次　·　均 <b>'+(m.均token||0)+'</b> token/次'
      + (m.末次更新 ? '　·　末次 '+esc(m.末次更新) : '')
      + '</div>';
    ip.innerHTML = '<div class="ip-name">'+esc(d.label)+'</div>'
      + '<div class="ip-meta">'+esc(meta)+'</div>'
      + '<div class="ip-desc">'+esc(d.jianjie||"（暂无简介）")+'</div>'
      + mrow
      + '<div class="ip-id">'+esc(d.id)+'　·　Ctrl+C 复制名称+路径</div>';
    ip.classList.add("on");
  } else {
    ip.classList.remove("on");
  }
  if(typeof renderDataPanel==="function") renderDataPanel();   // 同步高亮数据面板里的选中行
}
function copyText(t){
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(t).catch(function(){ fbCopy(t); });
  } else { fbCopy(t); }
}
function fbCopy(t){   // file:// 本地打开时 clipboard API 常被禁,用这个兜底
  var ta=document.createElement("textarea"); ta.value=t;
  ta.style.position="fixed"; ta.style.top="-1000px"; document.body.appendChild(ta);
  ta.focus(); ta.select();
  try{ document.execCommand("copy"); }catch(e){}
  document.body.removeChild(ta);
}
var _toast;
function toast(msg){
  if(!_toast){ _toast=document.createElement("div"); _toast.id="toast"; document.body.appendChild(_toast); }
  _toast.textContent=msg; _toast.classList.add("on");
  clearTimeout(_toast._t); _toast._t=setTimeout(function(){ _toast.classList.remove("on"); }, 1600);
}
document.addEventListener("keydown", function(ev){
  if((ev.ctrlKey||ev.metaKey) && (ev.key==="c" || ev.key==="C")){
    if(!selected) return;
    var s = window.getSelection && String(window.getSelection());
    if(s) return;                       // 用户正选中页面文字 → 走浏览器默认复制,不抢
    ev.preventDefault();
    copyText(selected.label + "\t" + selected.id);
    toast("✓ 已复制: " + selected.label + "　" + selected.id);
  }
});

// hover 高亮相连
var adj = {};
links.forEach(function(e){
  var s=e.source.id||e.source, t=e.target.id||e.target;
  (adj[s]=adj[s]||new Set()).add(t); (adj[t]=adj[t]||new Set()).add(s);
});
function hi(d,on){
  if(on){
    var keep = adj[d.id]||new Set(); keep.add(d.id);
    node.style("opacity",function(n){return keep.has(n.id)?1:0.12;});
    link.style("opacity",function(l){var s=l.source.id,t=l.target.id;return (s===d.id||t===d.id)?0.95:0.04;});
  }else{
    node.style("opacity",1);
    link.style("opacity",function(l){return l.type==="pipeline"?0.75:0.35;});
  }
}
var tt = document.getElementById("tooltip");
function tip(ev,d){
  var line2 = d.ghost ? "断链目标(文件不存在)"
    : ((d.fuwu?("服务"+d.fuwu):"") + (d.gongfang?(" · "+d.gongfang):"") + " · " + d.layer
       + (d.role?(" · "+d.role):"") + (d.orphan?" · ⚠孤儿":""));
  tt.innerHTML = '<div class="tt-name">'+d.label+'</div>'
    + '<div class="tt-sub">'+line2+'</div>'
    + '<div class="tt-sub" style="color:#6e7681">'+d.id+'</div>';
  tt.classList.add("on"); mv(ev);
}
function mv(ev){ tt.style.left=(ev.pageX+14)+"px"; tt.style.top=(ev.pageY+14)+"px"; }

// 重置视图 / 初始 fit
function fit(){
  setTimeout(function(){
    var b = gRoot.node().getBBox();
    if(!b.width) return;
    var s = Math.min(W/b.width, H/b.height)*0.9;
    s = Math.max(0.1, Math.min(s, 2));
    var tx = W/2 - s*(b.x+b.width/2), ty = H/2 - s*(b.y+b.height/2);
    svg.transition().duration(400).call(zoom.transform, d3.zoomIdentity.translate(tx,ty).scale(s));
  }, 60);
}
document.getElementById("btnfit").onclick = fit;

// ── 数据面板:全节点度量表(可排序;点行=选中该节点) ──
var DATANODES = nodes.filter(function(n){return !n.ghost;});
var DPCOLS = [
  {t:"节点",   get:function(n){return n.label;},            num:false},
  {t:"工坊",   get:function(n){return n.gongfang||"";},      num:false},
  {t:"调用",   get:function(n){return n.metrics.调用次数||0;}, num:true},
  {t:"字数",   get:function(n){return n.metrics.累计字数||0;}, num:true},
  {t:"token",  get:function(n){return n.metrics.累计token||0;},num:true},
  {t:"返工",   get:function(n){return n.metrics.返工次数||0;}, num:true},
  {t:"均字",   get:function(n){return n.metrics.均字数||0;},   num:true},
  {t:"均token",get:function(n){return n.metrics.均token||0;},  num:true}
];
var dpSort = {col:3, desc:true};   // 默认按累计字数降序
function renderDataPanel(){
  var dp = document.getElementById("datapanel");
  if(!dp.classList.contains("on")) return;
  var rows = DATANODES.slice().sort(function(a,b){
    var c=DPCOLS[dpSort.col], va=c.get(a), vb=c.get(b), r = c.num ? (va-vb) : String(va).localeCompare(String(vb));
    return dpSort.desc ? -r : r;
  });
  var th = DPCOLS.map(function(c,i){
    return '<th data-c="'+i+'">'+esc(c.t)+(i===dpSort.col?(dpSort.desc?" ▼":" ▲"):"")+'</th>';
  }).join("");
  var body = rows.map(function(n){
    var sel = (selected && selected.id===n.id) ? ' class="sel"' : '';
    var dot = '<span class="dp-dot" style="background:'+(LAYER[n.layer]||"#8b949e")+'"></span>';
    var tds = DPCOLS.map(function(c,i){ var v=c.get(n); return '<td>'+(i===0? dot+esc(v):esc(v))+'</td>'; }).join("");
    return '<tr data-id="'+esc(n.id)+'"'+sel+'>'+tds+'</tr>';
  }).join("");
  dp.innerHTML = '<h3>节点使用度量 <span class="dp-hint">点表头排序 · 点行选中节点 · 数值由 update_metrics.py 累积</span></h3>'
    + '<div class="dp-scroll"><table><thead><tr>'+th+'</tr></thead><tbody>'+body+'</tbody></table></div>';
  dp.querySelectorAll("thead th").forEach(function(el){
    el.onclick=function(){ var c=+el.getAttribute("data-c");
      if(dpSort.col===c) dpSort.desc=!dpSort.desc; else { dpSort.col=c; dpSort.desc = c>=2; }
      renderDataPanel(); };
  });
  dp.querySelectorAll("tbody tr").forEach(function(el){
    el.onclick=function(){ selectNode(nodeById[el.getAttribute("data-id")]||null); };
  });
}
document.getElementById("btndata").onclick=function(){
  document.getElementById("datapanel").classList.toggle("on"); renderDataPanel();
};

var _fitted = false;
sim.on("end", function(){ if(!_fitted){ _fitted = true; fit(); } });  // 首次布局完成自动看全一次
</script></body></html>"""


# ════════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════════
def main():
    nodes = collect_nodes()
    edges, broken = build_edges(nodes)
    orphans = find_orphans(nodes, edges)
    cycles = find_cycles(edges)
    no_fm = [r for r, i in nodes.items() if not i["has_fm"]]
    issues = {"orphans": orphans, "broken_links": broken,
              "cycles": cycles, "no_frontmatter": no_fm}

    metrics = sync_metrics(nodes)   # 对齐度量表的行(补新节点/标记已删),再把数值并进图
    write_json(nodes, edges, issues, metrics, os.path.join(TOOLS_DIR, "graph.json"))
    write_html(nodes, edges, issues, metrics, os.path.join(ENGINE_ROOT, "workflow_map.html"))

    print(f"扫描 {len(nodes)} 个 md 节点,{len(edges)} 条依赖边。")
    print(f"  已加 frontmatter:{len(nodes)-len(no_fm)} / {len(nodes)}")
    print(f"  孤儿(无人引用):{len(orphans)}")
    print(f"  断链(指向不存在的文件):{len(broken)}")
    print(f"  循环依赖:{len(cycles)}")
    if orphans:
        print("  孤儿明细:")
        for o in orphans:
            print(f"    - {o}")
    if broken:
        print("  断链明细:")
        for b in broken:
            print(f"    - {b['source']}  →  {b['raw']}")
    print("产出:tools/graph.json(数据集) + 项目根/workflow_map.html(浏览器打开:D3 力导向图,按工坊聚簇/按服务定形状)")


if __name__ == "__main__":
    main()
