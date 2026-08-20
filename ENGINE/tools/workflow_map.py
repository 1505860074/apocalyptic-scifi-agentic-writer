#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工作流地图生成器  workflow_map.py
======================================

【作用】
扫描项目里所有 .md 文件(排除 BOOKS),读取每个文件顶部 YAML frontmatter 里声明的
依赖关系(pipeline_next / reads),构建工作流的有向依赖图,产出三样东西:
  1) graph.json         —— 数据集(节点 + 边 + 体检结果),给任何工具二次使用
  2) workflow_map.html  —— 可视化(D3.js v7 力导向图:节点可自由拖动、画布可缩放平移、
                            按层着色、孤儿/断链红标、hover 高亮相连、图例)
  3) 控制台体检报告      —— 孤儿 / 断链 / 循环 / 未加 frontmatter 的文件

【设计原则】
- Python 侧只用标准库(os / json / re)。可视化用 D3.js(CDN),仿 code-review-graph 的力导向图。
- 全部逻辑在脚本里跑,agent 只负责"执行这个脚本",省 token。

【frontmatter 约定】(加在每个 md 文件最顶部)
---
node: 正文生成            # 唯一标识,一般=文件名主干
layer: prompt            # prompt | knowledge | template | root | meta
role: 步骤               # 自由文本,仅展示 + "总揽/元工具不算孤儿"的判断
pipeline_next:           # 管线下游(相对本文件的路径)
  - ./独立正文自查.md
reads:                   # 参考依赖(相对本文件的路径)
  - ../knowledge/铁律总纲.md
---

【用法】
    python3 workflow_map.py
输出写到脚本所在目录(ENGINE/tools/)。
"""

import os
import re
import json

# ── 路径:脚本在 ENGINE/tools/ 下;扫描范围=项目根(含 AGENTS.md/README.md),排除 BOOKS ──
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_ROOT = os.path.dirname(os.path.dirname(TOOLS_DIR))  # tools → ENGINE → 项目根
SKIP_DIRS = {"BOOKS", ".git", "__pycache__", ".claude"}


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
        kv = re.match(r"^([A-Za-z_][\w]*):\s*(.*)$", line)
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
    """孤儿 = 没有任何入边。入口(root)、总揽、元工具 天然无人指向,不算孤儿。"""
    pointed_to = {e["target"] for e in edges}
    orphans = []
    for rel, info in nodes.items():
        if rel in pointed_to:
            continue
        if info["layer"] in ("root", "tool"):
            continue
        if any(k in info["role"] for k in ("总揽", "入口", "元工具")):
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
# 5) 产出 graph.json
# ════════════════════════════════════════════════════════════════
def write_json(nodes, edges, issues, path):
    data = {
        "nodes": [{"rel": i["rel"], "layer": i["layer"], "title": i["title"],
                   "role": i["role"], "has_frontmatter": i["has_fm"]}
                  for i in nodes.values()],
        "edges": [{"source": e["source"], "target": e["target"],
                   "type": e["type"], "exists": e["exists"]} for e in edges],
        "issues": issues,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ════════════════════════════════════════════════════════════════
# 6) 产出 workflow_map.html(D3.js v7 力导向图,可拖动+缩放)
# ════════════════════════════════════════════════════════════════
def write_html(nodes, edges, issues, path):
    orphan_set = set(issues["orphans"])
    data = {
        "nodes": [{"id": i["rel"], "label": i["title"], "layer": i["layer"],
                   "role": i["role"], "orphan": i["rel"] in orphan_set}
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
    border-radius:10px;padding:12px 16px;font-size:12px;line-height:1.9;z-index:10;backdrop-filter:blur(10px);}
  #legend h4{font-size:10px;color:#9eaab6;text-transform:uppercase;letter-spacing:1px;margin:6px 0 2px;}
  .lg{display:flex;align-items:center;gap:8px;}
  .dot{width:12px;height:12px;border-radius:50%;flex-shrink:0;}
  .ln{width:22px;height:0;flex-shrink:0;}
  #tooltip{position:absolute;pointer-events:none;background:rgba(22,27,34,.97);border:1px solid #30363d;
    border-radius:8px;padding:8px 12px;font-size:12px;max-width:340px;opacity:0;transition:opacity .12s;
    z-index:1000;box-shadow:0 8px 32px rgba(0,0,0,.6);}
  #tooltip.on{opacity:1;} .tt-name{font-weight:700;color:#e6edf3;} .tt-sub{color:#9eaab6;margin-top:2px;}
  #btnfit{position:absolute;top:52px;right:16px;background:rgba(22,27,34,.95);color:#c9d1d9;
    border:1px solid #30363d;border-radius:8px;padding:6px 14px;font-size:12px;cursor:pointer;z-index:10;}
  #btnfit:hover{background:#30363d;}
  text.lbl{fill:#9eaab6;font-size:10px;pointer-events:none;paint-order:stroke;stroke:#0d1117;stroke-width:3px;}
</style></head><body>
<div id="topbar"></div>
<div id="legend"></div>
<button id="btnfit">重置视图</button>
<div id="tooltip"></div>
<svg id="svg"></svg>
<script>
"use strict";
var DATA = __GRAPH_DATA__;
var LAYER = {prompt:"#58a6ff",knowledge:"#3fb950",template:"#f0883e",root:"#8b949e",meta:"#d2a8ff",tool:"#8b949e"};
var LAYER_CN = {prompt:"prompt 步骤/校验",knowledge:"knowledge 知识",template:"template 模板",root:"root 总揽/入口",meta:"meta 元工具"};

// topbar
var c = DATA.counts;
document.getElementById("topbar").innerHTML =
  '<b>工作流地图</b>'
  + '<span>节点 <b>'+c.nodes+'</b></span><span>依赖边 <b>'+c.edges+'</b></span>'
  + '<span class="'+(c.orphans?'bad':'')+'">孤儿 <b>'+c.orphans+'</b></span>'
  + '<span class="'+(c.broken?'bad':'')+'">断链 <b>'+c.broken+'</b></span>'
  + '<span class="'+(c.cycles?'bad':'')+'">循环 <b>'+c.cycles+'</b></span>'
  + '<span class="hint">滚轮缩放 · 拖节点(松手固定) · 双击解除固定 · 拖背景平移 · 悬停高亮　｜　由 ENGINE/tools/workflow_map.py 生成</span>';

// legend
var lg = '<h4>节点层</h4>';
["prompt","knowledge","template","root","meta"].forEach(function(k){
  lg += '<div class="lg"><span class="dot" style="background:'+LAYER[k]+'"></span>'+LAYER_CN[k]+'</div>';});
lg += '<h4>边</h4>'
  + '<div class="lg"><span class="ln" style="border-top:2px solid #58a6ff"></span>管线 pipeline_next</div>'
  + '<div class="lg"><span class="ln" style="border-top:2px dashed #8b949e"></span>参考 reads</div>'
  + '<h4>体检</h4>'
  + '<div class="lg"><span class="dot" style="background:none;border:2px solid #f85149"></span>孤儿(无人引用)</div>';
document.getElementById("legend").innerHTML = lg;

// 构造节点/边;断链目标(不存在)建红色 ghost 节点
var nodeById = {};
DATA.nodes.forEach(function(n){ nodeById[n.id]=n; });
DATA.edges.forEach(function(e){
  if(!nodeById[e.target]){
    nodeById[e.target] = {id:e.target, label:"❌ "+e.target.split("/").pop(), layer:"broken", orphan:false, ghost:true};
    DATA.nodes.push(nodeById[e.target]);
  }
});
var nodes = DATA.nodes, links = DATA.edges;
// degree 决定节点大小
var deg = {};
links.forEach(function(e){ deg[e.source]=(deg[e.source]||0)+1; deg[e.target]=(deg[e.target]||0)+1; });
function radius(d){ return 6 + Math.min((deg[d.id]||0)*1.2, 12); }
function fill(d){ return d.ghost ? "#f85149" : (LAYER[d.layer]||"#8b949e"); }

var svg = d3.select("#svg");
var W = window.innerWidth, H = window.innerHeight;
var gRoot = svg.append("g");

// 箭头
var defs = svg.append("defs");
[["arrow-pipe","#58a6ff"],["arrow-read","#8b949e"]].forEach(function(a){
  defs.append("marker").attr("id",a[0]).attr("viewBox","0 -5 10 10")
    .attr("refX",20).attr("refY",0).attr("markerWidth",7).attr("markerHeight",7).attr("orient","auto")
    .append("path").attr("d","M0,-4L10,0L0,4Z").attr("fill",a[1]);
});

// 缩放/平移
var zoom = d3.zoom().scaleExtent([0.1,8]).on("zoom",function(ev){ gRoot.attr("transform",ev.transform); });
svg.call(zoom);

var sim = d3.forceSimulation(nodes)
  .force("link", d3.forceLink(links).id(function(d){return d.id;})
     .distance(function(l){return l.type==="pipeline"?95:60;})
     .strength(function(l){return l.type==="pipeline"?0.5:0.12;}))
  .force("charge", d3.forceManyBody().strength(-320).distanceMax(500))
  .force("collide", d3.forceCollide().radius(function(d){return radius(d)+8;}))
  .force("center", d3.forceCenter(W/2,H/2))
  .force("x", d3.forceX(W/2).strength(0.04))
  .force("y", d3.forceY(H/2).strength(0.04));

var link = gRoot.append("g").selectAll("line").data(links).enter().append("line")
  .attr("stroke", function(d){return d.type==="pipeline"?"#58a6ff":"#8b949e";})
  .attr("stroke-width", function(d){return d.type==="pipeline"?1.8:1;})
  .attr("stroke-dasharray", function(d){return d.type==="pipeline"?null:"6,4";})
  .attr("opacity", function(d){return d.type==="pipeline"?0.75:0.4;})
  .attr("marker-end", function(d){return d.type==="pipeline"?"url(#arrow-pipe)":"url(#arrow-read)";});

var node = gRoot.append("g").selectAll("g").data(nodes).enter().append("g")
  .call(d3.drag().on("start",dS).on("drag",dD).on("end",dE));

node.append("circle")
  .attr("r", radius).attr("fill", fill)
  .attr("stroke", function(d){return d.orphan?"#f85149":"rgba(255,255,255,.15)";})
  .attr("stroke-width", function(d){return d.orphan?2.5:1;})
  .attr("cursor","pointer");

node.append("text").attr("class","lbl").attr("dx", function(d){return radius(d)+4;})
  .attr("dy","0.35em").text(function(d){return d.label;});

node.on("mouseover",function(ev,d){ hi(d,true); tip(ev,d); })
    .on("mousemove", mv)
    .on("mouseout", function(ev,d){ hi(d,false); document.getElementById("tooltip").classList.remove("on"); })
    .on("dblclick", function(ev,d){ d.fx=null; d.fy=null; sim.alpha(0.3).restart(); });

sim.on("tick", function(){
  link.attr("x1",function(d){return d.source.x;}).attr("y1",function(d){return d.source.y;})
      .attr("x2",function(d){return d.target.x;}).attr("y2",function(d){return d.target.y;});
  node.attr("transform", function(d){return "translate("+d.x+","+d.y+")";});
});

function dS(ev,d){ if(!ev.active) sim.alphaTarget(0.2).restart(); d.fx=d.x; d.fy=d.y; }
function dD(ev,d){ d.fx=ev.x; d.fy=ev.y; }
function dE(ev,d){ if(!ev.active) sim.alphaTarget(0); }  // 松手保留 fx/fy = 固定在拖到的位置

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
    link.style("opacity",function(l){return l.type==="pipeline"?0.75:0.4;});
  }
}
var tt = document.getElementById("tooltip");
function tip(ev,d){
  tt.innerHTML = '<div class="tt-name">'+d.label+'</div>'
    + '<div class="tt-sub">'+(d.ghost?"断链目标(文件不存在)":(d.layer+(d.role?" · "+d.role:"")+(d.orphan?" · ⚠孤儿":"")))+'</div>'
    + '<div class="tt-sub" style="color:#6e7681">'+d.id+'</div>';
  tt.classList.add("on"); mv(ev);
}
function mv(ev){ tt.style.left=(ev.pageX+14)+"px"; tt.style.top=(ev.pageY+14)+"px"; }

// 重置视图 / 初始 fit
function fit(){
  setTimeout(function(){
    var b = gRoot.node().getBBox();
    if(!b.width) return;
    var s = Math.min(W/b.width, H/b.height)*0.85;
    s = Math.max(0.1, Math.min(s, 2));
    var tx = W/2 - s*(b.x+b.width/2), ty = H/2 - s*(b.y+b.height/2);
    svg.transition().duration(400).call(zoom.transform, d3.zoomIdentity.translate(tx,ty).scale(s));
  }, 60);
}
document.getElementById("btnfit").onclick = fit;
var _fitted = false;
sim.on("end", function(){ if(!_fitted){ _fitted = true; fit(); } });  // 只在首次布局完成时自动看全一次;之后缩放/拖动都不再自动重置(要复位点右上"重置视图")
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

    write_json(nodes, edges, issues, os.path.join(TOOLS_DIR, "graph.json"))
    write_html(nodes, edges, issues, os.path.join(ENGINE_ROOT, "workflow_map.html"))

    print(f"扫描 {len(nodes)} 个 md 节点,{len(edges)} 条依赖边。")
    print(f"  已加 frontmatter:{len(nodes)-len(no_fm)} / {len(nodes)}")
    print(f"  孤儿(无人引用):{len(orphans)}")
    print(f"  断链(指向不存在的文件):{len(broken)}")
    print(f"  循环依赖:{len(cycles)}")
    if broken:
        print("  断链明细:")
        for b in broken:
            print(f"    - {b['source']}  →  {b['raw']}")
    print("产出:tools/graph.json(数据集) + 项目根/workflow_map.html(浏览器打开:D3 力导向图,可拖动/缩放)")


if __name__ == "__main__":
    main()
