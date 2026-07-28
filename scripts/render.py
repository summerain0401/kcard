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
- design/styles/<name>/engine.html 必须挂载 window.renderCard(data, params, pageNum?)
- 默认(params 未声明 canvas.height,或声明为 null)是长图模式:engine.html 通过
  CSS 自行定义画布尺寸(如 .stage 的 width/min-height),render.py 用 full_page
  截图,不强行指定 viewport 高度。<card_dir>/output.png 只有一张
- canvas.height 非空则是分页模式(目前仅 aurora-glass 的部分骨架支持):
  画布定高,render.py 改用视口截图,按 renderCard() 返回的 pages 循环出图,
  写成 output-01.png / output-02.png / ...;内容溢出画布直接抛 RenderOverflow,
  不静默裁切
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
# height 800 只是长图模式的 viewport 占位值,full_page 截图会按实际内容高度出图,
# 与这个数字无关。分页模式(params 声明了 canvas.height)会在渲染前把 viewport
# 高度改写成 canvas.height,那时这个占位值同样不生效。
VIEWPORT = {"width": 1080, "height": 800}
DEVICE_SCALE_FACTOR = 2


class RenderOverflow(Exception):
    """分页模式下,某一页内容超出固定画布。只在 canvas.height 非空时可能触发。

    用普通异常而非 sys.exit——batch.py 需要能逐卡捕获后继续处理其余卡,
    不能让一张溢出的卡带崩整批。"""


def _cleanup_stale_outputs(out_path, written):
    """删掉与 out_path 同名、但这次渲染没写到的旧产物。

    典型场景:一套搭配从长图切到分页(或反过来),旧模式遗留的文件
    (不带页码的单文件,或 -01/-02/... 一组)会在磁盘上滞留,不会被
    覆盖也不会被发现——这正是本轮开发中 amber/onyx 切到分页后,
    preview/amber.png 这张旧长图仍在、被 gallery.py 误当成"代表预览"
    选中的真实事故。清理逻辑放在 render_on_page 这个唯一的截图出口,
    而不是指望每个调用方(run_card/run_preview/batch.py)各自记得处理。
    """
    keep = {p.name for p in written}
    stem, suffix = out_path.stem, out_path.suffix
    candidates = [out_path] + sorted(out_path.parent.glob(f"{stem}-*{suffix}"))
    for candidate in candidates:
        if candidate.exists() and candidate.name not in keep:
            candidate.unlink()


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
    """合并 space.json 的 default、preset 与生产组 profile 的参数。

    优先级:profile.params > preset.params > space.json 的 default。
    space.json 的 params 段未声明的键一律报错——未声明即不可调。
    取值域与跨维不变式的校验属 style-check.py(阶段4),此处只挡未声明的键。

    返回值总是包含 space.json 声明的**全部**参数键(未被 preset/profile
    覆写的填 default)。这不是可选的便利——preset 允许只写与 default 的
    差异(稀疏化,便于阅读哪一版改了什么),但下游两处消费者都要求拿到
    完整字典,单靠 engine.html 的 CSS `:root` 回落救不了它们:
      1. style-check.py 的不变式求值器直接按键查 params,缺键就
         ValueError("引用了未声明的参数"),不会静默跳过。
      2. 本文件自己的分页判断 `params.get("canvas.height")`
         是 Python 分支,不经过 CSS,preset 不声明就读不到 space.json 的 default。
    """
    declared = space.get("params", {})
    overrides = profile.get("params", {})

    unknown = sorted(set(overrides) - set(declared))
    if unknown:
        print(f"错误: {profile_path} 使用了未声明的参数 {', '.join(unknown)};"
              f"风格的 space.json 未开放这些维度,需向设计部提案扩展", file=sys.stderr)
        sys.exit(1)

    params = {k: v["default"] for k, v in declared.items() if "default" in v}
    params.update(preset.get("params", {}))
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


def render_on_page(browser, engine_path, layout_path, data, params, out_path):
    """在已有的 browser 实例上开一个新页渲染。batch.py 批量产卡时复用同一个
    browser 调用本函数,免去每张卡各起一次 Chromium 进程的开销。

    返回写出的文件路径列表。长图模式(params 无 canvas.height)只写一个文件,
    列表长度恒为 1,与改造前完全等价——调用方原有的位置解包不用跟着改。
    分页模式下画布定高,按 renderCard() 报告的总页数循环出图,写成
    <out_path 主干>-01.png / -02.png / ...;某页溢出画布则抛 RenderOverflow,
    不静默裁切,由调用方决定怎么处理(batch.py 逐卡捕获继续,单卡渲染直接报错)。
    """
    canvas_height = params.get("canvas.height")
    page = browser.new_page(viewport=VIEWPORT, device_scale_factor=DEVICE_SCALE_FACTOR)
    page.goto(engine_path.as_uri())
    # 骨架 CSS 在引擎样式之后注入,同优先级下后者生效
    page.add_style_tag(path=str(layout_path))
    page.evaluate("document.fonts.ready")

    if not canvas_height:
        page.evaluate("({data, params}) => renderCard(data, params)",
                      {"data": data, "params": params})
        page.evaluate("document.fonts.ready")
        page.screenshot(path=str(out_path), full_page=True)
        page.close()
        _cleanup_stale_outputs(out_path, [out_path])
        return [out_path]

    # 分页模式:画布定高,不用 full_page——视口本身就是画布,截出来正好是整张。
    page.set_viewport_size({"width": VIEWPORT["width"], "height": int(canvas_height)})

    def render_page_n(n):
        info = page.evaluate(
            "({data, params, n}) => renderCard(data, params, n)",
            {"data": data, "params": params, "n": n})
        page.evaluate("document.fonts.ready")
        if info.get("overflow"):
            page.close()
            # info['page'] 才是引擎实际报告溢出的那一页,不一定等于本次请求
            # 的 n——分页方案是每次调用都从头整体重算的(见 engine.html
            # buildPagingPlan 的注释),第 1 页那次调用建方案时若在后面某页
            # 探测到溢出,会在那次调用里就直接报出来,此时 n=1 但溢出的是别页。
            overflow_page = info.get("page", n)
            block_note = (f",第 {info['overflowBlockIndex']} 块单独超高"
                          if info.get("overflowBlockIndex") is not None else "")
            raise RenderOverflow(
                f"{out_path.stem} 第 {overflow_page} 页内容溢出画布:内容高 "
                f"{info.get('contentHeight')}px > 画布 {info.get('canvasHeight')}px"
                f"(共 {info.get('pages')} 页{block_note})")
        return info

    info = render_page_n(1)
    pages = int(info.get("pages", 1))
    written = []
    for n in range(1, pages + 1):
        if n > 1:
            render_page_n(n)
        page_path = out_path.with_name(f"{out_path.stem}-{n:02d}{out_path.suffix}")
        page.screenshot(path=str(page_path))
        written.append(page_path)
    page.close()
    _cleanup_stale_outputs(out_path, written)
    return written


def render_page(engine_path, layout_path, data, params, out_path):
    """加载引擎 → 注入骨架 CSS → 注入数据与参数 → 截图(长图或分页,见 render_on_page)。
    单卡渲染用,自行管理 browser 生命周期(用完即关)。返回写出的文件路径列表。"""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        written = render_on_page(browser, engine_path, layout_path, data, params, out_path)
        browser.close()
        return written


def run_preview(args):
    """风格自证:用风格自带的 sample.json 渲染某套搭配,全程不访问 production/。

    这是「新增风格与新增生产组彼此独立」的前提——未被任何组采用的新风格
    也必须能自己渲染出预览,否则设计部产能会被生产需求卡住。
    """
    style_name, preset_name = args.style, args.preset

    space, space_path = load_space(style_name)
    preset = load_preset(style_name, preset_name)
    # 预览没有生产组 profile,传空字典即"无覆写"——resolve_params() 补齐的
    # 是与生产渲染同一份逻辑,保证预览与生产对同一份 preset 渲染结果一致
    # (稀疏 preset 若只在这里手动拼字典,会拿到与生产路径不同的缺省值)。
    params = resolve_params(space, preset, {}, space_path)

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

    written = render_page(engine_path, layout_path, data, params, out_path)
    if len(written) == 1:
        print(f"已渲染风格预览({preset_name} / {layout_name}) -> {written[0]}")
    else:
        names = ", ".join(str(p) for p in written)
        print(f"已渲染风格预览({preset_name} / {layout_name},共 {len(written)} 页) -> {names}")


def resolve_card(card_dir):
    """加载 <card_dir> 对应的 profile/preset/card.json,解析出渲染所需的一切,
    但不动手渲染。batch.py / regress.py 需要在遍历多张卡时复用这一步,
    单卡渲染的 run_card() 也走这个函数,两条路径不重复实现。

    返回 (engine_path, layout_path, data, params, out_path)。
    """
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
    return engine_path, layout_path, data, params, out_path


def run_card(args):
    card_dir = Path(args.card_dir).resolve()
    engine_path, layout_path, data, params, out_path = resolve_card(card_dir)
    written = render_page(engine_path, layout_path, data, params, out_path)
    if len(written) == 1:
        print(f"已渲染知识卡片 -> {written[0]}")
    else:
        names = ", ".join(str(p) for p in written)
        print(f"已渲染知识卡片(共 {len(written)} 页) -> {names}")


def main():
    args = parse_args()
    if args.style:
        run_preview(args)
    else:
        run_card(args)


if __name__ == "__main__":
    main()
