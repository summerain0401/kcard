#!/usr/bin/env python3
"""
cutout.py - 主图去底工具

用法:
    .venv/bin/python scripts/cutout.py <图片路径> [-o 输出路径]

把中性色背景(纯白/浅灰/AI 工具烤进像素的透明网格)键出为 alpha 通道,
供深色风格(如 editorial-mono)使用。默认输出到 <同目录>/<原名>-cut.png。

适用前提:主体是彩色的,背景是中性色(R≈G≈B)且明亮。
不适用:背景带明显色相(如暖色渐变背景),此时主体与背景彩度接近,键不干净,
       应重新生成透明底素材——详见 design/styles/editorial-mono/schema.md。

输入若已带有效 alpha 通道,直接跳过,不重复处理。
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

# 背景判定:彩度低于 CHROMA_MAX 且最暗通道高于 LIGHT_MIN,即"中性且明亮"
CHROMA_MAX = 22
LIGHT_MIN = 188
# 保留的连通块面积下限(占全图比例),滤掉网格接缝之类的碎点
MIN_BLOB_RATIO = 0.002


def parse_args():
    parser = argparse.ArgumentParser(description="主图去底,中性背景键出为 alpha")
    parser.add_argument("image", type=str, help="输入图片路径")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="输出路径,默认 <原名>-cut.png")
    parser.add_argument("--chroma", type=int, default=CHROMA_MAX,
                        help=f"背景彩度上限,默认 {CHROMA_MAX};背景偏灰时可调高")
    parser.add_argument("--light", type=int, default=LIGHT_MIN,
                        help=f"背景亮度下限,默认 {LIGHT_MIN};背景偏暗时可调低")
    return parser.parse_args()


def build_alpha(rgb, chroma_max, light_min):
    """返回 0..1 的 alpha,主体不透明、中性亮背景透明。"""
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)

    background = ((mx - mn) < chroma_max) & (mn > light_min)
    fg = ~background

    # 主体上的镜面高光同样是中性亮色,会被误判成背景而打出空洞,填掉
    fg = ndimage.binary_fill_holes(fg)

    # 只保留够大的连通块,滤掉背景网格接缝产生的碎点
    labels, count = ndimage.label(fg)
    if count:
        sizes = ndimage.sum(fg, labels, range(1, count + 1))
        floor = fg.size * MIN_BLOB_RATIO
        keep = [i + 1 for i, s in enumerate(sizes) if s >= floor]
        fg = np.isin(labels, keep) if keep else (labels == int(np.argmax(sizes)) + 1)

    # 边缘按图幅缩放地收一圈再羽化,吃掉主体轮廓上残留的背景像素
    scale = max(rgb.shape[0], rgb.shape[1]) / 2048
    erode = max(1, round(2 * scale))
    sigma = max(1.0, 1.8 * scale)

    fg = ndimage.binary_erosion(fg, iterations=erode)
    alpha = ndimage.gaussian_filter(fg.astype(np.float32), sigma=sigma)
    return np.clip((alpha - 0.4) / 0.35, 0, 1)


def main():
    args = parse_args()
    src = Path(args.image).resolve()

    if not src.exists():
        print(f"错误: 找不到 {src}", file=sys.stderr)
        sys.exit(1)

    img = Image.open(src)
    if img.mode == "RGBA":
        existing = np.asarray(img)[..., 3]
        if existing.min() < 250:
            print(f"输入已带 alpha 通道(最小值 {existing.min()}),无需去底")
            return

    rgb = np.asarray(img.convert("RGB")).astype(np.float32)
    alpha = build_alpha(rgb, args.chroma, args.light)

    kept = float((alpha > 0.5).mean())
    if kept < 0.02:
        print(f"警告: 主体只占 {kept:.1%},可能把主体一起键掉了 —— "
              f"试试调低 --light 或调高 --chroma", file=sys.stderr)
    elif kept > 0.9:
        print(f"警告: 保留了 {kept:.1%} 的画面,背景可能带色相没被键出 —— "
              f"该素材建议重新生成透明底版本", file=sys.stderr)

    out = Path(args.output).resolve() if args.output else src.with_name(f"{src.stem}-cut.png")
    rgba = np.dstack([rgb, alpha * 255]).astype(np.uint8)

    # 紧裁到主体包围盒(留少量边距):模板按"底对齐"摆放主体,
    # 透明边不裁掉的话,横长形主体会悬浮在展台上方
    ys, xs = np.where(alpha > 0.02)
    if ys.size:
        pad = max(8, round(12 * max(rgb.shape[0], rgb.shape[1]) / 2048))
        y0, y1 = max(0, ys.min() - pad), min(rgb.shape[0], ys.max() + pad)
        x0, x1 = max(0, xs.min() - pad), min(rgb.shape[1], xs.max() + pad)
        rgba = rgba[y0:y1, x0:x1]

    Image.fromarray(rgba, "RGBA").save(out)

    print(f"已去底 -> {out}")
    print(f"主体占比 {kept:.1%}")


if __name__ == "__main__":
    main()
