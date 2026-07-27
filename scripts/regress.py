#!/usr/bin/env python3
"""
regress.py - 风格改动后的像素回归

用法:
    .venv/bin/python scripts/regress.py <style-name>            # 只检查,不写文件
    .venv/bin/python scripts/regress.py <style-name> --write     # 检查后接受新渲染
    .venv/bin/python scripts/regress.py --all                    # 检查全部风格

背景(PLAN.md 第五节独立性约束第4条):设计部改风格是"原地改,但必须通过
regress.py 对所有在用组重渲染确认无破坏"。生产组的 profile.json 不知道、
也不需要知道自己正被拿来做回归检查——本脚本单向地从 production/ 读 style
字段来定位受影响的组,这是"工具反向查询"而非"design/ 反向依赖",
design/ 目录本身不含任何指向 production/ 的引用。

默认是 dry-run:渲染到临时文件比对,不动 production/ 里已提交的 output.png。
只有加 --write 才会用新渲染结果覆盖它们,即"接受这次风格改动带来的变化"。
"""

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import render  # 复用 resolve_card / render_on_page,不重复实现

PROJECT_ROOT = SCRIPT_DIR.parent
PRODUCTION_DIR = PROJECT_ROOT / "production"
STYLES_DIR = PROJECT_ROOT / "design" / "styles"


def parse_args():
    parser = argparse.ArgumentParser(
        description="风格改动后,对所有在用该风格的生产组重渲染做像素 diff")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("style", type=str, nargs="?", help="只检查这一套风格")
    group.add_argument("--all", action="store_true", help="检查全部风格")
    parser.add_argument("--write", action="store_true",
                        help="用新渲染结果覆盖 output.png(即接受这次变化);默认只检查不写")
    args = parser.parse_args()
    if not args.style and not args.all:
        parser.error("须给出风格名,或使用 --all")
    return args


def groups_using_style(style_name):
    """扫描 production/*/profile.json,找出 style 字段匹配的组。

    这是本脚本里唯一"跨过去看 production/"的地方,且只读不写、只服务于
    比对逻辑本身——design/ 目录不因此产生任何对 production/ 的引用。
    """
    if not PRODUCTION_DIR.exists():
        return []
    import json
    groups = []
    for profile_path in sorted(PRODUCTION_DIR.glob("*/profile.json")):
        with profile_path.open("r", encoding="utf-8") as f:
            profile = json.load(f)
        if profile.get("style") == style_name:
            groups.append(profile_path.parent)
    return groups


def find_card_dirs(group_dir):
    cards_dir = group_dir / "cards"
    if not cards_dir.exists():
        return []
    return sorted(
        child for child in cards_dir.iterdir()
        if child.is_dir() and (child / "card.json").exists()
    )


def diff_card(browser, card_dir, tmp_dir):
    """渲染到临时路径,与已提交的 output.png 比较。返回 (状态, detail)。
    状态取值: 'same' / 'changed' / 'new'(committed output.png 尚不存在)。
    """
    committed_path = card_dir / "output.png"
    tmp_path = tmp_dir / f"{card_dir.parent.parent.name}_{card_dir.name}.png"

    engine_path, layout_path, data, params, _ = render.resolve_card(card_dir)
    render.render_on_page(browser, engine_path, layout_path, data, params, tmp_path)

    if not committed_path.exists():
        return "new", tmp_path

    old_bytes = committed_path.read_bytes()
    new_bytes = tmp_path.read_bytes()
    if old_bytes == new_bytes:
        return "same", tmp_path
    return "changed", tmp_path


def check_style(style_name, write, tmp_dir):
    groups = groups_using_style(style_name)
    if not groups:
        print(f"{style_name}: 暂无生产组在用,跳过")
        return True  # 没有在用组,谈不上破坏,视为通过

    print(f"=== {style_name} (在用组: {', '.join(g.name for g in groups)}) ===")

    all_ok = True
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for group_dir in groups:
            for card_dir in find_card_dirs(group_dir):
                label = f"{group_dir.name}/{card_dir.name}"
                try:
                    status, tmp_path = diff_card(browser, card_dir, tmp_dir)
                except SystemExit:
                    print(f"  ✗ {label}: 渲染失败")
                    all_ok = False
                    continue

                if status == "same":
                    print(f"  ✓ {label}: 像素一致")
                elif status == "new":
                    print(f"  + {label}: 尚无已提交的 output.png,视为新增")
                    if write:
                        shutil.copy(tmp_path, card_dir / "output.png")
                else:
                    print(f"  ✗ {label}: 像素有变化" + ("(已写入)" if write else "(未写入,加 --write 接受)"))
                    all_ok = False
                    if write:
                        shutil.copy(tmp_path, card_dir / "output.png")
        browser.close()

    return all_ok or write


def main():
    args = parse_args()

    if args.all:
        style_names = sorted(d.name for d in STYLES_DIR.iterdir() if d.is_dir())
    else:
        if not (STYLES_DIR / args.style).exists():
            print(f"错误: 找不到风格 {STYLES_DIR / args.style}", file=sys.stderr)
            sys.exit(1)
        style_names = [args.style]

    with tempfile.TemporaryDirectory(prefix="kcard-regress-") as tmp:
        tmp_dir = Path(tmp)
        results = [check_style(name, args.write, tmp_dir) for name in style_names]

    ok = all(results)
    print(f"\n{'PASS' if ok else 'FAIL'}"
          + ("" if args.write else "(dry-run,未写入任何 output.png)"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
