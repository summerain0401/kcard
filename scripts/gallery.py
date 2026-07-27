#!/usr/bin/env python3
"""
gallery.py - 从各风格的 STYLE.md / space.json / layouts / presets 生成 design/GALLERY.md

用法:
    .venv/bin/python scripts/gallery.py

GALLERY 是设计部与生产部唯一的交汇点(PLAN.md 第五节独立性约束第5条),
记三件事:有哪些风格可选、每套风格当前被哪些组使用、版本与冻结状态。
本脚本接管此前阶段5a手写的占位版本,之后不应再手改 design/GALLERY.md
——要更新看板,改风格自身的 STYLE.md/space.json/presets,重跑本脚本。

数据来源(只读):
    design/styles/<name>/STYLE.md      "这套风格是什么"段落 + 硬约束条数
    design/styles/<name>/space.json    版本号、可调参数数量
    design/styles/<name>/layouts/*.css 首行注释 "/* 名称 — 一句话简介"
    design/styles/<name>/presets/*.json  displayName / description / layout
    design/styles/<name>/preview/*.png   预览图是否存在
    production/*/profile.json          style 字段,用于统计"被哪些组使用"
                                        (只读查询,design/ 侧不产生任何反向引用)
"""

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
STYLES_DIR = PROJECT_ROOT / "design" / "styles"
PRODUCTION_DIR = PROJECT_ROOT / "production"
OUT_PATH = PROJECT_ROOT / "design" / "GALLERY.md"

LAYOUT_HEADER_RE = re.compile(r"/\*\s*([\w-]+)\s*—\s*(.+)")


def used_by(style_name):
    if not PRODUCTION_DIR.exists():
        return []
    groups = []
    for profile_path in sorted(PRODUCTION_DIR.glob("*/profile.json")):
        with profile_path.open("r", encoding="utf-8") as f:
            profile = json.load(f)
        if profile.get("style") == style_name:
            groups.append(profile_path.parent.name)
    return groups


def extract_summary(style_md_text):
    """取"## 一、这套风格是什么"到下一个"## "之间的正文,原样保留 Markdown 强调符号。"""
    m = re.search(r"^## 一、.*?\n(.*?)(?=^## )", style_md_text, re.S | re.M)
    return m.group(1).strip() if m else "(STYLE.md 缺少「这套风格是什么」小节)"


def count_hard_constraints(style_md_text):
    return len(re.findall(r"^\| H\d+ \|", style_md_text, re.M))


def parse_layouts(style_dir):
    layouts = []
    for css_path in sorted((style_dir / "layouts").glob("*.css")):
        first_line = css_path.read_text(encoding="utf-8").splitlines()[0]
        m = LAYOUT_HEADER_RE.match(first_line)
        name, desc = (m.group(1), m.group(2)) if m else (css_path.stem, "")
        layouts.append({"name": name, "desc": desc})
    return layouts


def parse_presets(style_dir):
    presets = []
    for preset_path in sorted((style_dir / "presets").glob("*.json")):
        with preset_path.open("r", encoding="utf-8") as f:
            preset = json.load(f)
        preview_path = style_dir / "preview" / f"{preset['name']}.png"
        presets.append({
            "name": preset["name"],
            "displayName": preset.get("displayName", preset["name"]),
            "description": preset.get("description", ""),
            "layout": preset.get("layout", ""),
            "preview": preview_path.name if preview_path.exists() else None,
        })
    return presets


def load_style(style_dir):
    with (style_dir / "space.json").open("r", encoding="utf-8") as f:
        space = json.load(f)
    style_md_text = (style_dir / "STYLE.md").read_text(encoding="utf-8")

    return {
        "name": style_dir.name,
        "version": space.get("version", "?"),
        "param_count": len(space.get("params", {})),
        "summary": extract_summary(style_md_text),
        "hard_constraint_count": count_hard_constraints(style_md_text),
        "layouts": parse_layouts(style_dir),
        "presets": parse_presets(style_dir),
        "used_by": used_by(style_dir.name),
    }


def render_style_section(style):
    lines = [f"## {style['name']}", "", style["summary"], ""]

    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| 版本 | {style['version']} |")
    lines.append(f"| 可调维度 | {style['param_count']} 个(完整取值域见 `space.json`)|")
    lines.append(f"| 硬约束 | {style['hard_constraint_count']} 条(完整规则见 "
                 f"[STYLE.md](styles/{style['name']}/STYLE.md))|")
    lines.append(f"| 被哪些组使用 | {', '.join(f'`{g}`' for g in style['used_by']) or '(暂无)'} |")
    lines.append("")

    lines.append("**骨架**")
    lines.append("")
    lines.append("| 名称 | 简介 |")
    lines.append("|---|---|")
    for layout in style["layouts"]:
        lines.append(f"| `{layout['name']}` | {layout['desc']} |")
    lines.append("")

    lines.append("**搭配**")
    lines.append("")
    lines.append("| 名称 | 说明 | 预览 |")
    lines.append("|---|---|---|")
    for preset in style["presets"]:
        preview_cell = (f"[{preset['preview']}](styles/{style['name']}/preview/{preset['preview']})"
                        if preset["preview"] else "(无)")
        lines.append(f"| `{preset['name']}` · {preset['displayName']} | "
                     f"{preset['description']} | {preview_cell} |")
    lines.append("")

    return "\n".join(lines)


def render_gallery(styles):
    lines = [
        "# 风格选型看板",
        "",
        "> 设计部与生产部**唯一的交汇点**。生产部选型只需读这一页;",
        "> 设计部改动风格前先看这里评估影响面。",
        ">",
        "> 本文件由 `scripts/gallery.py` 从各风格的 `STYLE.md` / `space.json` /",
        "> `layouts/` / `presets/` 自动生成,**请勿手改**——改风格自身的文件,",
        "> 重新运行 `python scripts/gallery.py` 即可更新本页。",
        "",
        "## 在用一览",
        "",
        "| 风格 | 版本 | 骨架 | 搭配 | 被哪些组使用 |",
        "|---|---|---|---|---|",
    ]
    for style in styles:
        used = ", ".join(f"`{g}`" for g in style["used_by"]) or "(暂无)"
        lines.append(f"| [{style['name']}](styles/{style['name']}/) | {style['version']} | "
                     f"{len(style['layouts'])} | {len(style['presets'])} | {used} |")
    lines.append("")
    lines.append("「暂无组使用」是正常状态——设计部可以先囤方案,不必等生产需求。"
                 "风格与生产组的新增彼此独立,详见 `PLAN.md` 第五节。")
    lines.append("")
    lines.append("---")
    lines.append("")

    for i, style in enumerate(styles):
        lines.append(render_style_section(style))
        if i < len(styles) - 1:
            lines.append("---")
            lines.append("")

    return "\n".join(lines) + "\n"


def main():
    if not STYLES_DIR.exists():
        print(f"错误: 找不到 {STYLES_DIR}", file=sys.stderr)
        sys.exit(1)

    style_dirs = sorted(d for d in STYLES_DIR.iterdir() if d.is_dir())
    if not style_dirs:
        print(f"错误: {STYLES_DIR} 下没有任何风格", file=sys.stderr)
        sys.exit(1)

    styles = [load_style(d) for d in style_dirs]
    OUT_PATH.write_text(render_gallery(styles), encoding="utf-8")
    print(f"已生成 -> {OUT_PATH}")


if __name__ == "__main__":
    main()
