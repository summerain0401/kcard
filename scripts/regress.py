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
    group.add_argument("--engine-defaults", type=str, metavar="STYLE",
                        help="校验风格的 engine.html :root 默认值是否与 space.json 的"
                             " default 逐位一致(见下方说明),不涉及 production/")
    parser.add_argument("--write", action="store_true",
                        help="用新渲染结果覆盖 output.png(即接受这次变化);默认只检查不写")
    args = parser.parse_args()
    if not args.style and not args.all and not args.engine_defaults:
        parser.error("须给出风格名、使用 --all,或使用 --engine-defaults")
    if args.engine_defaults and args.write:
        parser.error("--engine-defaults 不支持 --write(它不产生要接受的变更,只报告是否一致)")
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


def committed_paths_for(card_dir, page_count):
    """按本次渲染实际写出的页数,推出已提交目录里"应该"对应的路径。
    page_count=1 时用不带后缀的 output.png——这是分页功能上线前就有的命名,
    非分页卡永远走这条,与改造前完全兼容。"""
    if page_count == 1:
        return [card_dir / "output.png"]
    return [card_dir / f"output-{i:02d}.png" for i in range(1, page_count + 1)]


def find_orphan_pages(card_dir, keep):
    """已提交目录里属于本卡产物、但这次渲染用不到的文件——多半是页数变化后
    遗留的旧页(比如 4 页改 3 页,或者分页改回长图/长图改成分页)。
    dry-run 时要点名报出来,--write 时要删,否则会静默滞留并被误提交。"""
    keep_names = {p.name for p in keep}
    existing = list(card_dir.glob("output.png")) + list(card_dir.glob("output-*.png"))
    return [p for p in sorted(existing) if p.name not in keep_names]


def diff_card(browser, card_dir, tmp_dir):
    """渲染到临时路径,与已提交的产物比较。返回 (状态, written, committed, orphans)。

    状态取值:
      'same'    页数与逐页像素都一致
      'changed' 逐页像素有差异,或存在孤儿页(页数变化)
      'new'     已提交目录里一张对应产物都不存在
    written/committed 长度相同、逐一对应;orphans 是已提交目录里多出来的旧页,
    仅分页卡在页数变化时可能非空。
    """
    tmp_stem = f"{card_dir.parent.parent.name}_{card_dir.name}"
    engine_path, layout_path, data, params, _ = render.resolve_card(card_dir)
    written = render.render_on_page(
        browser, engine_path, layout_path, data, params, tmp_dir / f"{tmp_stem}.png")

    committed = committed_paths_for(card_dir, len(written))
    orphans = find_orphan_pages(card_dir, committed)

    if not any(c.exists() for c in committed):
        return "new", written, committed, orphans

    same = all(c.exists() and c.read_bytes() == w.read_bytes()
               for c, w in zip(committed, written))
    if same and not orphans:
        return "same", written, committed, orphans
    return "changed", written, committed, orphans


def check_engine_defaults(style_name, tmp_dir):
    """校验 engine.html 的 `:root` 默认值是否与 space.json 的 default 逐位一致。

    背景:render.py 的 resolve_params() 总是用 space.json 的 default 补全
    未被 preset/profile 覆写的键(见 render.py 里的说明),所以生产渲染与
    风格预览实际上**从不**依赖 engine.html 的 `:root` 兜底——applyParams()
    的 has(k) 判断永远为真,`:root` 的硬编码值是死代码。既然如此,这条检查
    就不是运行时正确性闸门,而是给 `:root` 那句"默认值等于 space.json 的
    default"的注释做纪律检查:它曾经真的漂移过(层高/主体尺寸两个参数与
    default 相差 80–60px,被 preset 全量声明长期掩盖,直到六套 preset 稀疏化
    才第一次因为真的依赖 `:root` 兜底而暴露),留着这条检查是为了不再靠"六套
    preset 恰好全覆盖"这种偶然性来发现下一次类似漂移。

    做法:同一份 sample.json、同一个骨架,分别传空参数 {} 与 space.json 的
    全部 default 各渲染一次。前者完全依赖 `:root`,后者显式传值——
    两者字节一致,才说明 `:root` 没有漂移。
    """
    space, space_path = render.load_space(style_name)
    declared = space.get("params", {})
    defaults = {k: v["default"] for k, v in declared.items() if "default" in v}

    sample_path = STYLES_DIR / style_name / "sample.json"
    if not sample_path.exists():
        print(f"{style_name}: 缺 {sample_path},无法校验")
        return False

    import json
    with sample_path.open("r", encoding="utf-8") as f:
        data_template = json.load(f)

    presets_dir = STYLES_DIR / style_name / "presets"
    preset_paths = sorted(presets_dir.glob("*.json"))
    if not preset_paths:
        print(f"{style_name}: presets/ 下没有搭配,无法取一个骨架名来渲染")
        return False
    with preset_paths[0].open("r", encoding="utf-8") as f:
        layout_name = json.load(f).get("layout")

    engine_path, layout_path = render.resolve_style_assets(
        style_name, layout_name, f"regress --engine-defaults({preset_paths[0].name})")

    import copy
    # "空参数"这一侧并非真的传 {}:render.py 自己在 Python 层消费 canvas.height
    # (据此决定视口截图还是 full_page、以及画布多高),这一档不给值,两次渲染
    # 会在 render.py 层面就分道扬镳,页数不同,校验退化成误报。故只补这一个键,
    # 其余全部留空交给引擎 :root 兜底——那才是本检查要验的东西。
    render_level_keys = {"canvas.height"}
    minimal = {k: defaults[k] for k in render_level_keys if k in defaults}

    empty_out = tmp_dir / f"{style_name}-engine-defaults-empty.png"
    full_out = tmp_dir / f"{style_name}-engine-defaults-full.png"
    written_empty = render.render_page(
        engine_path, layout_path, copy.deepcopy(data_template), minimal, empty_out)
    written_full = render.render_page(
        engine_path, layout_path, copy.deepcopy(data_template), defaults, full_out)

    if len(written_empty) != len(written_full):
        print(f"{style_name}: ✗ 页数不一致(空参数 {len(written_empty)} 页 vs "
              f"全 default {len(written_full)} 页)—— :root 与 space.json 的 "
              f"canvas.height 相关默认值可能不一致")
        return False

    mismatches = [
        i for i, (e, f) in enumerate(zip(written_empty, written_full), 1)
        if e.read_bytes() != f.read_bytes()
    ]
    if mismatches:
        print(f"{style_name}: ✗ 第 {mismatches} 页像素不一致——"
              f"engine.html 的 :root 与 space.json 的 default 有漂移,"
              f"逐参数比对两处取值")
        return False

    print(f"{style_name}: ✓ engine.html 的 :root 与 space.json 的 "
          f"default 逐位一致({len(defaults)} 项)")
    return True


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
                    status, written, committed, orphans = diff_card(browser, card_dir, tmp_dir)
                except SystemExit:
                    print(f"  ✗ {label}: 渲染失败")
                    all_ok = False
                    continue
                except render.RenderOverflow as exc:
                    print(f"  ✗ {label}: 内容溢出画布 ({exc})")
                    all_ok = False
                    continue

                page_note = f"(共 {len(written)} 页)" if len(written) > 1 else ""

                if status == "same":
                    print(f"  ✓ {label}{page_note}: 像素一致")
                elif status == "new":
                    print(f"  + {label}{page_note}: 尚无已提交的产物,视为新增")
                    if write:
                        for c, w in zip(committed, written):
                            shutil.copy(w, c)
                else:
                    detail = "像素有变化"
                    if orphans:
                        detail += f",且有 {len(orphans)} 个页数变化遗留的旧页待清理"
                    print(f"  ✗ {label}{page_note}: {detail}"
                          + ("(已写入)" if write else "(未写入,加 --write 接受)"))
                    all_ok = False
                    if write:
                        for c, w in zip(committed, written):
                            shutil.copy(w, c)
                        for orphan in orphans:
                            orphan.unlink()
        browser.close()

    return all_ok or write


def main():
    args = parse_args()

    if args.engine_defaults:
        if not (STYLES_DIR / args.engine_defaults).exists():
            print(f"错误: 找不到风格 {STYLES_DIR / args.engine_defaults}", file=sys.stderr)
            sys.exit(1)
        with tempfile.TemporaryDirectory(prefix="kcard-regress-") as tmp:
            ok = check_engine_defaults(args.engine_defaults, Path(tmp))
        print(f"\n{'PASS' if ok else 'FAIL'}")
        sys.exit(0 if ok else 1)

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
