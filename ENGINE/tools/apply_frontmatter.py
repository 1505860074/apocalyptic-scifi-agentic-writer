#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量给工作流 md 文件插入 frontmatter(依赖声明)。
- 幂等:已有 frontmatter 的文件自动跳过(所以能反复跑)。
- 依赖关系依据《工作流总览》的管线顺序 + 第五节"分层加载策略"表 提炼;
  这是一次性铺底,之后各文件的 frontmatter 可手工微调。
- reads 里只登记 ENGINE 内的 knowledge/template(书里的产物文件不算工作流依赖)。
用法: python3 apply_frontmatter.py
"""
import os

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(TOOLS_DIR))  # tools → ENGINE → 项目根

# 依赖表:key=相对项目根的路径; value=该文件的 frontmatter 元数据
DATA = {}

# ── knowledge:叶子知识(被 reads,自己不指向别人)──
for n in ["铁律总纲", "平台与题材规律", "细化等级体系", "少年向与文风", "节奏与爽点",
          "桥段与伏笔", "描写与逻辑规范", "去AI味与叙事质感", "多视角叙事技巧",
          "情绪感知过滤器", "题材与立项候选库", "优秀网文写作法"]:
    DATA[f"ENGINE/knowledge/{n}.md"] = {"layer": "knowledge", "role": "知识"}
DATA["ENGINE/knowledge/知识库地图.md"] = {"layer": "knowledge", "role": "总揽"}

# ── templates:叶子模板 ──
for n in ["场面调度卡-模板", "伏笔登记表-模板", "故事弧大纲-模板", "故事种子-模板",
          "关系情感状态卡-模板", "焦点卡-模板", "金手指卡-模板", "句意稿-模板",
          "立项书-模板", "命名与术语表-模板", "情绪蓄力卡-模板", "人物卡-核心-模板",
          "人物卡-普通-模板", "人物状态维度定义-模板", "人物状态账本-模板",
          "世界观设定卡-模板", "世界基底-模板", "世界线纪要-模板", "演进状态卡-模板",
          "章纲节拍表-模板", "章节状态清单-模板", "状态预算-模板"]:
    DATA[f"ENGINE/templates/{n}.md"] = {"layer": "template", "role": "模板"}

# ── prompts:剩余 19 个(显式管线 next + 参考 reads)──
P = "ENGINE/prompts/"
DATA[P + "立项车间-立项问答.md"] = {"layer": "prompt", "role": "步骤",
    "next": ["./立项车间-立项自查.md"],
    "reads": ["../templates/立项书-模板.md", "../knowledge/题材与立项候选库.md", "../knowledge/平台与题材规律.md"]}
DATA[P + "立项车间-立项自查.md"] = {"layer": "prompt", "role": "校验",
    "next": ["./新建项目.md"], "reads": ["../knowledge/平台与题材规律.md"]}
DATA[P + "新建项目.md"] = {"layer": "prompt", "role": "步骤",
    "next": ["./世界观与金手指.md"], "reads": ["../templates/模板总览.md"]}
DATA[P + "世界观与金手指.md"] = {"layer": "prompt", "role": "步骤",
    "next": ["./人物种子.md"],
    "reads": ["../knowledge/平台与题材规律.md", "../templates/世界观设定卡-模板.md", "../templates/金手指卡-模板.md", "../templates/命名与术语表-模板.md"]}
DATA[P + "人物种子.md"] = {"layer": "prompt", "role": "步骤",
    "next": ["./故事种子与世界基底.md"],
    "reads": ["../knowledge/平台与题材规律.md", "../templates/人物卡-核心-模板.md", "../templates/人物卡-普通-模板.md"]}
DATA[P + "故事种子与世界基底.md"] = {"layer": "prompt", "role": "步骤",
    "next": ["./架构一致性校验.md"],
    "reads": ["../knowledge/桥段与伏笔.md", "../templates/世界基底-模板.md", "../templates/故事种子-模板.md", "../templates/世界线纪要-模板.md", "../templates/人物状态维度定义-模板.md", "../templates/人物状态账本-模板.md", "../templates/命名与术语表-模板.md"]}
DATA[P + "架构一致性校验.md"] = {"layer": "prompt", "role": "校验",
    "next": ["./故事弧大纲.md"], "reads": ["../knowledge/铁律总纲.md"]}
DATA[P + "世界线宏大推演.md"] = {"layer": "prompt", "role": "步骤",
    "next": ["./故事弧大纲.md"], "reads": ["../templates/世界线纪要-模板.md"]}
DATA[P + "故事弧大纲.md"] = {"layer": "prompt", "role": "步骤",
    "next": ["./故事弧状态预算.md"],
    "reads": ["../knowledge/节奏与爽点.md", "../knowledge/桥段与伏笔.md", "../templates/故事弧大纲-模板.md", "../templates/伏笔登记表-模板.md"]}
DATA[P + "故事弧状态预算.md"] = {"layer": "prompt", "role": "步骤",
    "next": ["./章节状态分配.md"],
    "reads": ["../knowledge/桥段与伏笔.md", "../templates/状态预算-模板.md", "../templates/情绪蓄力卡-模板.md", "../templates/关系情感状态卡-模板.md"]}
DATA[P + "章节状态分配.md"] = {"layer": "prompt", "role": "步骤",
    "next": ["./章纲节拍表.md"], "reads": ["../templates/章节状态清单-模板.md"]}
DATA[P + "自查修正.md"] = {"layer": "prompt", "role": "步骤", "next": ["./润色定稿.md"]}
DATA[P + "润色定稿.md"] = {"layer": "prompt", "role": "步骤",
    "next": ["./最终交付检查.md"],
    "reads": ["../knowledge/少年向与文风.md", "../knowledge/去AI味与叙事质感.md"]}
DATA[P + "最终交付检查.md"] = {"layer": "prompt", "role": "校验",
    "reads": ["../knowledge/去AI味与叙事质感.md"]}
DATA[P + "复审修改.md"] = {"layer": "prompt", "role": "步骤",
    "next": ["./回归校验.md"], "reads": ["../knowledge/描写与逻辑规范.md"]}
DATA[P + "回归校验.md"] = {"layer": "prompt", "role": "校验", "reads": ["../knowledge/铁律总纲.md"]}
DATA[P + "通用复审包.md"] = {"layer": "prompt", "role": "元工具",
    "reads": ["../knowledge/描写与逻辑规范.md", "../knowledge/去AI味与叙事质感.md"]}
DATA[P + "卡文诊断.md"] = {"layer": "prompt", "role": "元工具"}
DATA[P + "用词优化工坊.md"] = {"layer": "meta", "role": "元工具",
    "reads": ["./场面调度.md", "./句意稿.md", "./正文生成.md", "./独立正文自查.md"]}

# ── ENGINE 顶层 + 项目根 root 文件 ──
DATA["ENGINE/工作流总览.md"] = {"layer": "root", "role": "总揽"}
DATA["ENGINE/归档结构规范.md"] = {"layer": "root", "role": "规范"}
DATA["ENGINE/_命名映射表-已执行.md"] = {"layer": "root", "role": "文档"}
DATA["AGENTS.md"] = {"layer": "root", "role": "入口", "reads": ["ENGINE/工作流总览.md"]}
DATA["README.md"] = {"layer": "root", "role": "文档"}


def build_fm(relpath, meta):
    node = os.path.splitext(os.path.basename(relpath))[0]
    lines = ["---", f"node: {node}", f"layer: {meta['layer']}", f"role: {meta['role']}"]
    if meta.get("next"):
        lines.append("pipeline_next:")
        lines += [f"  - {x}" for x in meta["next"]]
    if meta.get("reads"):
        lines.append("reads:")
        lines += [f"  - {x}" for x in meta["reads"]]
    lines.append("---")
    return "\n".join(lines)


def main():
    added, skipped, missing = 0, 0, []
    for rel, meta in DATA.items():
        full = os.path.join(PROJECT_ROOT, rel)
        if not os.path.exists(full):
            missing.append(rel)
            continue
        with open(full, encoding="utf-8") as f:
            text = f.read()
        if text.startswith("---"):        # 已有 frontmatter → 跳过(幂等)
            skipped += 1
            continue
        with open(full, "w", encoding="utf-8") as f:
            f.write(build_fm(rel, meta) + "\n\n" + text)
        added += 1
    print(f"插入 frontmatter:{added} 个;跳过(已有):{skipped} 个;表内共 {len(DATA)} 条")
    if missing:
        print("⚠ 找不到的文件(检查路径):")
        for m in missing:
            print("  -", m)


if __name__ == "__main__":
    main()
