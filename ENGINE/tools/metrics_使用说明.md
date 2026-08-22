---
node: metrics_使用说明
layer: tool
role: 说明
工坊: 维护工坊
服务: 工作流
简介: 节点使用度量表(metrics.json)的用途与 update_metrics.py 的调用方式,给 agent 看的操作手册。
---

# 使用度量表 · 操作说明（给 agent 看这一份就够，不要去读 .py 源码）

## 这是什么

`ENGINE/tools/metrics.json` 是**工作流各节点的使用度量表**：每个节点一行，累计记录
`调用次数 / 累计字数 / 累计token / 返工次数`（+ 自动算的均值、末次时间）。
它的用途是**优化工作流**——看清哪一步最费 token、最容易返工、产出最多字，据此改进。

- 数值**只增不减**，是长期累计。
- 表的**行结构**（补新节点、标记已删、刷新标题）由 `workflow_map.py` 自动维护，你不用管。
- 表的**数值**由 `update_metrics.py` 增量写入——**这就是你要调用的脚本**。
- 数值会显示在 `workflow_map.html`：选中节点看详情，或点右上"数据面板"看全表。

## 你（agent）要做什么：每跑完一个工作流步骤，上报一次

**硬规则**：每当你执行完本项目的一个工作流步骤（写正文、跑校验、改稿等），
在收尾时调用一次下面的命令，把这一步的用量报上去。

> **★这条最容易被漏（2026-08-22 教训）**：此前各 agent 基本没逐步上报——写了数十章正文，`正文生成` 却只记了个位数次调用，数据面板严重失真。**"每一步收尾都报"是硬规则、不是可选项**；哪怕只写了一章、跑了一次校验，也要报那一次。字数/token 估算即可，关键是**次数别漏**。
>
> **★上报会自动刷新数据面板**：`update_metrics.py` 写完 `metrics.json` 后会**自动重跑 `workflow_map.py`**，把新数值刷进 `graph.json` + `workflow_map.html`（数据面板是静态快照，不自动刷就会停在旧值——这一步已内置，你不用再手动跑图）。连报很多条时可加 `--no-sync` 跳过每条刷新、最后手动跑一次 `workflow_map.py` 统一刷。

```
python3 ENGINE/tools/update_metrics.py --node <节点名> [--calls N] [--chars N] [--tokens N] [--rework N] [--note "备注"]
```

参数：

| 参数 | 含义 | 怎么填 |
|------|------|--------|
| `--node` | 哪个节点（必填） | 中文名如 `正文生成`，或相对路径如 `ENGINE/prompts/正文生成.md` |
| `--calls` | 本次调用次数 | 通常填 `1` |
| `--chars` | 本次**产出或修改**的字数 | 你这一步写/改了多少字（正文、报告、卡片都算）。数不清就估一个数量级 |
| `--tokens` | 本次 token 消耗 | 这一步大致消耗的 token；不确定可估算或省略 |
| `--rework` | 本次返工次数 | 仅当这一步是"因上一步不合格而重跑/返修"时填 `1`，否则省略 |
| `--note` | 备注（会覆盖旧备注） | 可选 |

## 例子

```
# 正文生成 写完一章，约 3200 字，耗约 15000 token
python3 ENGINE/tools/update_metrics.py --node 正文生成 --calls 1 --chars 3200 --tokens 15000

# 独立正文自查 判定"必须修" → 自查修正 返工修了 600 字
python3 ENGINE/tools/update_metrics.py --node 自查修正 --calls 1 --chars 600 --tokens 4000 --rework 1

# 只是跑了一次校验、没产出正文字数
python3 ENGINE/tools/update_metrics.py --node 焦点卡校验 --calls 1 --tokens 3000
```

## 常见问题

- **不知道节点叫什么**：`python3 ENGINE/tools/update_metrics.py --list` 列出所有节点名。
- **节点名报歧义/找不到**：改用完整相对路径（如 `ENGINE/prompts/焦点卡.md`）。
- **字数/token 数不精确**：估算即可，趋势比精度重要；实在没有就省略该参数。
- **要不要手动刷图**：★不用了。`update_metrics.py` 上报后会**自动刷** `graph.json` + `workflow_map.html`（内置重跑 map）。只有加了 `--no-sync`（批量连报）时才需要最后手动跑一次 `workflow_map.py`。
- **历史数据不准怎么办**：2026-08-22 前的数值是少报的（见 `metrics.json` 的 `_说明`），**不补估**（补=造数、污染趋势）。自此如实逐步上报，让数据往前积累即可。
