---
node: CLAUDE
layer: root
role: 入口
工坊: 文档导航
服务: 工作流
简介: 给 Claude Code 开机自动加载的薄入口,转发到 AGENTS.md,并提醒两条★收尾硬规则。
reads:
  - AGENTS.md
---

# CLAUDE.md

> 本文件是给 **Claude Code** 开机自动加载的入口。内容只做薄转发，不重复正文——
> **本项目的权威入口是 `AGENTS.md`，接管项目前请先完整读它。**（`AGENTS.md` 面向所有 agent 工具，Claude Code 以外的工具也读它。）

## 接手第一步

1. **先扫 `ENGINE/tools/graph.json`**——工作流的**机器可读地图**，一个文件就能建立全局理解：每个节点的 `简介`（干嘛的）/`工坊`/`服务`，以及 `pipeline`（管线先后）/`reads`（参考依赖）调用关系。比通读散文档快得多。（`workflow_map.html` 是同一份数据给人看的可视化，agent 不必读。）
2. 再读 `AGENTS.md`（细则），并按其指引读 `ENGINE/工作流总览.md`（写书管线的权威流程）。冲突时一律以 `工作流总览.md` 为准。

## 两条 ★硬规则（每步收尾必做，别漏）

细节见 `AGENTS.md` 的「工作流依赖图与自检」和「使用度量上报」两节，这里只作提醒：

1. **改过任何工作流 md**（`ENGINE/` 下的 prompts / knowledge / templates，以及 `AGENTS.md`、`工作流总览.md` 等）→ 改完必须跑一次：
   ```
   python3 ENGINE/tools/workflow_map.py
   ```
   刷新依赖图（产出项目根的 `workflow_map.html`），并顺手维护改动文件的 frontmatter，跑完连同 `workflow_map.html` 一起提交。

2. **跑完任意一个工作流步骤**（写正文、跑校验、改稿、跑大纲等）→ 收尾时上报本步用量：
   ```
   python3 ENGINE/tools/update_metrics.py --node <节点名> --calls 1 [--chars N] [--tokens N] [--rework 1]
   ```
   完整用法只看 `ENGINE/tools/metrics_使用说明.md`，不要去读脚本源码。
