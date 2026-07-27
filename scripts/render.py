#!/usr/bin/env python3
"""
render.py - 知识卡片渲染脚本(风格无关)

用法:
    .venv/bin/python scripts/render.py <card_dir>

<card_dir> 形如 production/<group>/cards/<topic>。读取同组的
production/<group>/profile.json 取其 "style" 字段定位
design/styles/<style>/card.html,将 <card_dir>/card.json 的 "data" 字段
注入该风格的 renderCard(data) 函数,等待字体加载完成后截图,
产物写到 <card_dir>/output.png。

风格约定:
- design/styles/<name>/card.html 必须挂载 window.renderCard(data)
- card.html 内通过 CSS 自行定义画布尺寸(如 .stage 的 width/min-height),
  render.py 用 full_page 截图,不强行指定 viewport 高度
- data 中约定的图片字段(如 "hero")若是 <card_dir> 内的相对文件名且文件存在,
  render.py 会自动换成 file:// 绝对 URI 再传给模板;不存在则原样传入,
  由模板自行处理缺图占位
"""

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
STYLES_DIR = PROJECT_ROOT / "design" / "styles"

# 与 templates/*/card.html 里 body/.stage 的 width 保持一致(目前各模板均为 1080)。
# height 只是 viewport 占位值,full_page 截图会按实际内容高度出图。
VIEWPORT = {"width": 1080, "height": 800}
DEVICE_SCALE_FACTOR = 2


def parse_args():
    parser = argparse.ArgumentParser(description="渲染知识卡片 output.png")
    parser.add_argument("card_dir", type=str, help="卡片目录,须包含 card.json")
    return parser.parse_args()


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


def load_accent_config(style_name):
    """读取风格的取色配置(space.json 的 accentExtraction 段)。

    "什么算主体色"以及"提亮到什么水平"是风格自己的判断,不同风格取法不同,
    所以这组参数属于风格内部实现(scope=design),不放在生产组的 profile 里。
    缺 space.json 或缺该段时直接报错,不静默套用默认值。
    """
    space_path = STYLES_DIR / style_name / "space.json"
    if not space_path.exists():
        print(f"错误: 自动取色需要 {space_path}", file=sys.stderr)
        sys.exit(1)

    with space_path.open("r", encoding="utf-8") as f:
        space = json.load(f)

    cfg = space.get("accentExtraction")
    if not cfg:
        print(f"错误: {space_path} 缺少 accentExtraction 段", file=sys.stderr)
        sys.exit(1)
    return cfg


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


def main():
    args = parse_args()
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
    data = card.get("data")

    if not style_name:
        print(f"错误: {profile_path} 缺少 style 字段", file=sys.stderr)
        sys.exit(1)
    if data is None:
        print(f"错误: {card_json_path} 缺少 data 字段", file=sys.stderr)
        sys.exit(1)

    template_path = STYLES_DIR / style_name / "card.html"
    if not template_path.exists():
        print(f"错误: 找不到风格 {template_path}", file=sys.stderr)
        sys.exit(1)

    assets = resolve_asset_uris(data, card_dir)

    # themeColor 缺省时从主图取色;显式写了就以数据为准
    if isinstance(data, dict) and not data.get("themeColor") and "hero" in assets:
        accent = extract_accent(assets["hero"], load_accent_config(style_name))
        if accent:
            data["themeColor"] = accent
            print(f"主题色取自主图 -> {accent}")

    out_path = card_dir / "output.png"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=DEVICE_SCALE_FACTOR)
        page.goto(template_path.as_uri())
        page.evaluate("document.fonts.ready")
        page.evaluate("data => renderCard(data)", data)
        page.evaluate("document.fonts.ready")
        page.screenshot(path=str(out_path), full_page=True)
        browser.close()

    print(f"已渲染知识卡片 -> {out_path}")


if __name__ == "__main__":
    main()
