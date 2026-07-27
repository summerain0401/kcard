#!/usr/bin/env python3
"""
batch.py - 按生产组批量产卡

用法:
    .venv/bin/python scripts/batch.py production/<group>
    .venv/bin/python scripts/batch.py production/<group> --only tomato,banana

对 <group>/cards/ 下每个含 card.json 的目录调用一次渲染。全组共享同一个
Chromium 实例(render.render_on_page),避免逐卡各起一次浏览器进程的开销
——这是本脚本相对"手动逐张跑 render.py"的唯一区别,渲染逻辑本身完全复用
render.py 的 resolve_card()/render_on_page(),不重新实现。

不做风格宪法校验——那是 style-check.py 的职责,产卡前应先跑过一次组闸门。
"""

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import render  # 复用 resolve_card / render_on_page,不重复实现


def parse_args():
    parser = argparse.ArgumentParser(description="按生产组批量渲染知识卡片")
    parser.add_argument("group_dir", type=str, help="生产组目录 production/<group>")
    parser.add_argument("--only", type=str,
                        help="仅渲染这些卡片(逗号分隔的目录名,如 tomato,banana)")
    return parser.parse_args()


def find_card_dirs(group_dir, only=None):
    cards_dir = group_dir / "cards"
    if not cards_dir.exists():
        print(f"错误: 找不到 {cards_dir}", file=sys.stderr)
        sys.exit(1)

    wanted = set(only.split(",")) if only else None
    card_dirs = []
    for child in sorted(cards_dir.iterdir()):
        if not child.is_dir() or not (child / "card.json").exists():
            continue
        if wanted is not None and child.name not in wanted:
            continue
        card_dirs.append(child)

    if wanted is not None:
        missing = wanted - {d.name for d in card_dirs}
        if missing:
            print(f"错误: --only 指定的卡片不存在: {', '.join(sorted(missing))}", file=sys.stderr)
            sys.exit(1)

    return card_dirs


def main():
    args = parse_args()
    group_dir = Path(args.group_dir).resolve()
    if not (group_dir / "profile.json").exists():
        print(f"错误: {group_dir} 不是生产组目录(缺 profile.json)", file=sys.stderr)
        sys.exit(1)

    card_dirs = find_card_dirs(group_dir, args.only)
    if not card_dirs:
        print(f"{group_dir}/cards 下没有可渲染的卡片", file=sys.stderr)
        sys.exit(1)

    ok, failed = 0, []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for card_dir in card_dirs:
            name = card_dir.name
            try:
                engine_path, layout_path, data, params, out_path = render.resolve_card(card_dir)
                render.render_on_page(browser, engine_path, layout_path, data, params, out_path)
                print(f"✓ {name} -> {out_path}")
                ok += 1
            except SystemExit:
                # resolve_card 对单张卡的数据错误走 sys.exit(1);批量场景下
                # 不能让一张坏卡拖垮整批,记下来继续渲染其余卡片。
                print(f"✗ {name} 渲染失败,已跳过", file=sys.stderr)
                failed.append(name)
        browser.close()

    print(f"\n完成: {ok} 成功, {len(failed)} 失败" + (f" ({', '.join(failed)})" if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
