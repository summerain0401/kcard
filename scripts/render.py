#!/usr/bin/env python3
"""
render.py - 知识卡片渲染脚本(风格无关)

用法:
    .venv/bin/python scripts/render.py <card_dir>

<card_dir> 形如 production/<group>/cards/<topic>。渲染链路:

    production/<group>/profile.json     选定 style / preset / layout,并覆写参数
      → design/styles/<style>/presets/<preset>.json    示范搭配(参数基线)
      → design/styles/<style>/layouts/<layout>.css     版式骨架(头版定位)
      → design/styles/<style>/engine.html              参数化渲染引擎
      → <card_dir>/card.json 的 data                   卡片内容
      → <card_dir>/output.png

参数优先级:profile.params > preset.params。space.json 未声明的参数键一律报错
——未声明即不可调,不静默忽略。
accent 优先级:params["palette.accent"](组级固定色)> card.json 的 themeColor
> 从 hero 图自动取色。

风格约定:
- design/styles/<name>/engine.html 必须挂载 window.renderCard(data, params)
- engine.html 内通过 CSS 自行定义画布尺寸(如 .stage 的 width/min-height),
  render.py 用 full_page 截图,不强行指定 viewport 高度
- 头版定位不在 engine.html 里,由 layouts/<layout>.css 提供,渲染时注入
- data 中约定的图片字段(如 "hero")若是 <card_dir> 内的相对文件名且文件存在,
  render.py 会自动换成 file:// 绝对 URI 再传给引擎;不存在则原样传入,
  由引擎自行处理缺图占位
"""

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
STYLES_DIR = PROJECT_ROOT / "design" / "styles"

# 与 design/styles/*/engine.html 里 body/.stage 的 width 保持一致(目前各风格均为 1080)。
# height 只是 viewport 占位值,full_page 截图会按实际内容高度出图。
VIEWPORT = {"width": 1080, "height": 800}
DEVICE_SCALE_FACTOR = 2


def parse_args():
    parser = argparse.ArgumentParser(
        description="渲染知识卡片。两种模式:生产渲染(传 card_dir)与风格自证预览(传 --style)")
    parser.add_argument("card_dir", type=str, nargs="?",
                        help="生产渲染:卡片目录 production/<group>/cards/<topic>")
    parser.add_argument("--style", type=str,
                        help="风格自证预览:风格名。用风格自带的 sample.json 出图,不碰 production/")
    parser.add_argument("--preset", type=str, help="风格自证预览:搭配名")
    parser.add_argument("--layout", type=str,
                        help="风格自证预览:覆写骨架(默认用搭配指定的)")
    args = parser.parse_args()

    if args.style and not args.preset:
        parser.error("--style 需配合 --preset 使用")
    if not args.style and not args.card_dir:
        parser.error("须给出 card_dir(生产渲染)或 --style/--preset(风格自证预览)")
    return args


def resolve_asset_uris(data, card_dir):
    """把 data 中形如 'hero.png' 的相对文件名换成 card_dir 内的 file:// 绝对 URI。

    只处理约定的图片字段名(等于 hero 或以 Image 结尾),存在即替换,
    不存在则保留原值(模板自行处理缺图占位)。
    返回 {字段名: 本地 Path},供取色等后续步骤使用。
    """
    resolved = {}
    if not isinstance(data, dict):
        return resolved
    for key, value in list(data.items()):
        if isinstance(value, str) and (key == "hero" or key.lower().endswith("image")):
            candidate = card_dir / value
            if candidate.exists():
                data[key] = candidate.as_uri()
                resolved[key] = candidate
    return resolved


def load_space(style_name):
    """读取风格的参数空间声明 space.json,返回 (内容, 路径)。"""
    space_path = STYLES_DIR / style_name / "space.json"
    if not space_path.exists():
        print(f"错误: 找不到风格的参数空间声明 {space_path}", file=sys.stderr)
        sys.exit(1)
    with space_path.open("r", encoding="utf-8") as f:
        return json.load(f), space_path


def accent_config(space, space_path):
    """取出取色配置(space.json 的 accentExtraction 段)。

    "什么算主体色"以及"提亮到什么水平"是风格自己的判断,不同风格取法不同,
    所以这组参数属于风格内部实现(scope=design),不放在生产组的 profile 里。
    缺该段时直接报错,不静默套用默认值。
    """
    cfg = space.get("accentExtraction")
    if not cfg:
        print(f"错误: {space_path} 缺少 accentExtraction 段", file=sys.stderr)
        sys.exit(1)
    return cfg


def load_preset(style_name, preset_name):
    """读取示范搭配(presets/<name>.json)。

    生产组从某个 preset 起步再微调,而不是从空白参数空间调起——
    这是设计部防止"合法但难看"组合的第一道线。
    """
    preset_path = STYLES_DIR / style_name / "presets" / f"{preset_name}.json"
    if not preset_path.exists():
        print(f"错误: 找不到搭配 {preset_path}", file=sys.stderr)
        sys.exit(1)
    with preset_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_params(space, preset, profile, profile_path):
    """合并 preset 与生产组 profile 的参数。

    优先级:profile.params > preset.params。
    space.json 的 params 段未声明的键一律报错——未声明即不可调。
    取值域与跨维不变式的校验属 style-check.py(阶段4),此处只挡未声明的键。
    """
    declared = set(space.get("params", {}))
    overrides = profile.get("params", {})

    unknown = sorted(set(overrides) - declared)
    if unknown:
        print(f"错误: {profile_path} 使用了未声明的参数 {', '.join(unknown)};"
              f"风格的 space.json 未开放这些维度,需向设计部提案扩展", file=sys.stderr)
        sys.exit(1)

    params = dict(preset.get("params", {}))
    params.update(overrides)
    return params


def extract_accent(image_path, cfg):
    """从主图提取一个适合做强调色的主色,返回 '#RRGGBB';失败返回 None。

    取色范围只含主体像素(alpha 足够高、有一定饱和度和亮度),排除阴影与高光。
    以色相直方图取峰值,再把饱和度/明度提到强调色该有的水平——素材本身的
    明度往往偏低,直接用会在深色底上发闷。
    整个过程无随机性,同一张图重复取色结果一致。

    判定阈值全部来自 cfg(风格的 space.json → accentExtraction),不写死在这里。
    """
    try:
        import colorsys

        import numpy as np
        from PIL import Image
    except ImportError as exc:
        print(f"警告: 取色需要 numpy 与 Pillow ({exc}),跳过", file=sys.stderr)
        return None

    size = int(cfg["sampleSize"])
    im = Image.open(image_path).convert("RGBA").resize((size, size), Image.BILINEAR)
    arr = np.asarray(im)
    alpha = arr[..., 3]
    hsv = np.asarray(Image.fromarray(arr[..., :3]).convert("HSV")).astype(np.float32)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    # 只保留主体上"有颜色"的像素:去掉透明区、灰暗阴影和惨白高光
    mask = (alpha > cfg["alphaMin"]) & (sat > cfg["satMin"]) & (val > cfg["valMin"])
    if int(mask.sum()) < int(cfg["minPixels"]):
        return None

    h, s, v = hue[mask], sat[mask], val[mask]
    weight = (s / 255.0) * (v / 255.0)

    # 色相直方图找主色(默认 36 个 bin,每 bin 10°)
    bins = int(cfg["hueBins"])
    idx = np.clip((h / 256.0 * bins).astype(int), 0, bins - 1)
    peak = int(np.argmax(np.bincount(idx, weights=weight, minlength=bins)))

    # 收拢到峰值附近 ±hueSpread 个 bin,注意色相是环形的
    span = (idx - peak + bins // 2) % bins - bins // 2
    near = np.abs(span) <= int(cfg["hueSpread"])
    h, s, v, weight = h[near], s[near], v[near], weight[near]

    # 环形加权均值:先相对峰值展开,算完再折回
    centre = (peak + 0.5) / bins * 256.0
    offset = (h - centre + 128.0) % 256.0 - 128.0
    total = float(weight.sum()) or 1.0
    hue_deg = (centre + float((offset * weight).sum()) / total) % 256.0

    # 提亮提饱和,保证在深色底上够跳
    sat_lo, sat_hi = cfg["outSatRange"]
    val_lo, val_hi = cfg["outValRange"]
    sat_out = min(max(float(np.median(s)) / 255.0, sat_lo), sat_hi)
    val_out = min(max(float(np.median(v)) / 255.0, val_lo), val_hi)

    r, g, b = colorsys.hsv_to_rgb(hue_deg / 256.0, sat_out, val_out)
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


def resolve_style_assets(style_name, layout_name, source_desc):
    """定位并校验风格引擎与版式骨架。"""
    if not layout_name:
        print(f"错误: {source_desc} 未指定 layout", file=sys.stderr)
        sys.exit(1)

    engine_path = STYLES_DIR / style_name / "engine.html"
    if not engine_path.exists():
        print(f"错误: 找不到风格引擎 {engine_path}", file=sys.stderr)
        sys.exit(1)

    layout_path = STYLES_DIR / style_name / "layouts" / f"{layout_name}.css"
    if not layout_path.exists():
        print(f"错误: 找不到版式骨架 {layout_path}", file=sys.stderr)
        sys.exit(1)

    return engine_path, layout_path


def render_page(engine_path, layout_path, data, params, out_path):
    """加载引擎 → 注入骨架 CSS → 注入数据与参数 → 全页截图。"""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=DEVICE_SCALE_FACTOR)
        page.goto(engine_path.as_uri())
        # 骨架 CSS 在引擎样式之后注入,同优先级下后者生效
        page.add_style_tag(path=str(layout_path))
        page.evaluate("document.fonts.ready")
        page.evaluate("({data, params}) => renderCard(data, params)",
                      {"data": data, "params": params})
        page.evaluate("document.fonts.ready")
        page.screenshot(path=str(out_path), full_page=True)
        browser.close()


def run_preview(args):
    """风格自证:用风格自带的 sample.json 渲染某套搭配,全程不访问 production/。

    这是「新增风格与新增生产组彼此独立」的前提——未被任何组采用的新风格
    也必须能自己渲染出预览,否则设计部产能会被生产需求卡住。
    """
    style_name, preset_name = args.style, args.preset

    space, _ = load_space(style_name)
    preset = load_preset(style_name, preset_name)
    params = dict(preset.get("params", {}))

    sample_path = STYLES_DIR / style_name / "sample.json"
    if not sample_path.exists():
        print(f"错误: 风格自证需要 {sample_path}", file=sys.stderr)
        sys.exit(1)
    with sample_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    layout_name = args.layout or preset.get("layout")
    engine_path, layout_path = resolve_style_assets(
        style_name, layout_name, f"搭配 {preset_name}")

    if params.get("palette.accent"):
        data["themeColor"] = params["palette.accent"]

    out_dir = STYLES_DIR / style_name / "preview"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{preset_name}.png"

    render_page(engine_path, layout_path, data, params, out_path)
    print(f"已渲染风格预览({preset_name} / {layout_name}) -> {out_path}")


def run_card(args):
    card_dir = Path(args.card_dir).resolve()
    card_json_path = card_dir / "card.json"
    group_dir = card_dir.parent.parent
    profile_path = group_dir / "profile.json"

    if not profile_path.exists():
        print(f"错误: 找不到 {profile_path}(card_dir 应形如 production/<group>/cards/<topic>)", file=sys.stderr)
        sys.exit(1)
    if not card_json_path.exists():
        print(f"错误: 找不到 {card_json_path}", file=sys.stderr)
        sys.exit(1)

    with profile_path.open("r", encoding="utf-8") as f:
        profile = json.load(f)
    with card_json_path.open("r", encoding="utf-8") as f:
        card = json.load(f)

    style_name = profile.get("style")
    preset_name = profile.get("preset")
    data = card.get("data")

    if not style_name:
        print(f"错误: {profile_path} 缺少 style 字段", file=sys.stderr)
        sys.exit(1)
    if not preset_name:
        print(f"错误: {profile_path} 缺少 preset 字段(生产组须从某个示范搭配起步)", file=sys.stderr)
        sys.exit(1)
    if data is None:
        print(f"错误: {card_json_path} 缺少 data 字段", file=sys.stderr)
        sys.exit(1)

    space, space_path = load_space(style_name)
    preset = load_preset(style_name, preset_name)
    params = resolve_params(space, preset, profile, profile_path)

    # 版式骨架:生产组可覆写 preset 选定的骨架
    layout_name = profile.get("layout") or preset.get("layout")
    engine_path, layout_path = resolve_style_assets(
        style_name, layout_name, f"{profile_path} 与搭配 {preset_name}")

    assets = resolve_asset_uris(data, card_dir)

    # accent 优先级:组级固定色 > 单卡 themeColor > 从主图自动取色
    if params.get("palette.accent"):
        data["themeColor"] = params["palette.accent"]
    elif isinstance(data, dict) and not data.get("themeColor") and "hero" in assets:
        accent = extract_accent(assets["hero"], accent_config(space, space_path))
        if accent:
            data["themeColor"] = accent
            print(f"主题色取自主图 -> {accent}")

    out_path = card_dir / "output.png"
    render_page(engine_path, layout_path, data, params, out_path)
    print(f"已渲染知识卡片 -> {out_path}")


def main():
    args = parse_args()
    if args.style:
        run_preview(args)
    else:
        run_card(args)


if __name__ == "__main__":
    main()
