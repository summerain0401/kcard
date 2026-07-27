#!/usr/bin/env python3
"""
style-check.py - 生产组 profile 的风格宪法校验(组上线闸门)

用法:
    .venv/bin/python scripts/style-check.py production/<group>

读取 <group>/profile.json,解析其 style/preset,合并出最终参数,校验:
  1. 每个参数是否落在 space.json 声明的取值域内(range/values/length/type)
     —— 未声明的参数键在 resolve_params() 阶段已报错,此处只查"声明了但越界"
  2. space.json 的 invariants 段(跨维不变式)是否全部满足

这是"参数空间自由 = 可能配出合法但难看甚至违宪的组合"里,机器能拦的那一半;
高级感这种软约束仍需设计部在组上线时人工过目 output.png。

退出码:0 = 全部通过;1 = 存在违规或加载失败。
"""

import argparse
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import render  # 复用 load_space / load_preset / resolve_params,不重复实现

PROJECT_ROOT = SCRIPT_DIR.parent


def parse_args():
    parser = argparse.ArgumentParser(
        description="校验生产组 profile 是否符合所选风格的参数空间与不变式")
    parser.add_argument("group_dir", type=str,
                        help="生产组目录 production/<group>,或直接指向其 profile.json")
    return parser.parse_args()


def load_profile(group_arg):
    path = Path(group_arg).resolve()
    profile_path = path if path.name == "profile.json" else path / "profile.json"
    if not profile_path.exists():
        print(f"错误: 找不到 {profile_path}", file=sys.stderr)
        sys.exit(1)
    import json
    with profile_path.open("r", encoding="utf-8") as f:
        return json.load(f), profile_path


# ---------------------------------------------------------------------------
# 第一部分:参数取值域校验(range / values / length / type)
# ---------------------------------------------------------------------------

def check_param_bounds(space, params):
    """检查每个已声明参数的值是否落在 space.json 规定的域内。

    未声明的参数键不在此处处理——resolve_params() 已经在合并阶段拦截过,
    走到这里的 params 只可能包含 space["params"] 里已声明的键。
    """
    declared = space.get("params", {})
    violations = []

    for key, value in params.items():
        spec = declared.get(key)
        if spec is None:
            continue  # 理论上不会发生(resolve_params 已挡),稳妥起见跳过

        if value is None:
            if spec.get("free") or "type" in spec:
                continue  # 显式允许留空(如 palette.accent)
            violations.append((key, value, f"不可为空(space.json 未标记 free/type)"))
            continue

        if "values" in spec and value not in spec["values"]:
            violations.append((key, value, f"须为 {spec['values']} 之一"))
            continue

        if spec.get("type") == "hex":
            if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(value)):
                violations.append((key, value, "须为 #RRGGBB 形式的十六进制色值"))
            continue

        if "range" in spec:
            lo, hi = spec["range"]
            length = spec.get("length")
            items = value if isinstance(value, list) else [value]

            if length is not None and len(items) != length:
                violations.append((key, value, f"须为长度 {length} 的数组"))
                continue

            for item in items:
                if not (lo <= item <= hi):
                    violations.append(
                        (key, value, f"元素 {item} 超出声明域 [{lo}, {hi}]"))

    return violations


# ---------------------------------------------------------------------------
# 第二部分:跨维不变式(invariants)—— 小型安全表达式求值器
#
# 只支持 space.json 里实际出现的语法:数字、点号标识符(直接查 params)、
# 四则运算、比较运算、"=>"蕴含、min()/max()/isAscending() 三个函数。
# 不是通用 eval——没有变量赋值、没有属性/下标访问、不执行任意代码,
# 白名单之外的 token 直接报语法错误。
# ---------------------------------------------------------------------------

TOKEN_RE = re.compile(r"""
    \s*(?:
        (?P<num>\d+\.\d+|\d+)
      | (?P<ident>[A-Za-z_][A-Za-z0-9_.]*)
      | (?P<op>=>|>=|<=|==|[()+\-*/,><])
    )
""", re.VERBOSE)


def tokenize(expr):
    tokens, pos = [], 0
    while pos < len(expr):
        m = TOKEN_RE.match(expr, pos)
        if not m or m.end() == pos:
            if expr[pos:].strip() == "":
                break
            raise ValueError(f"无法解析的字符: {expr[pos:pos+10]!r}")
        pos = m.end()
        if m.lastgroup == "num":
            tokens.append(("num", float(m.group("num"))))
        elif m.lastgroup == "ident":
            tokens.append(("ident", m.group("ident")))
        elif m.lastgroup == "op":
            tokens.append(("op", m.group("op")))
    return tokens


class ExprParser:
    """递归下降,优先级从低到高: 蕴含 => 比较 => 加减 => 乘除 => 一元 => 函数/括号/字面量"""

    # contrastHSL 让任何"前景色与背景色都能直接表达成 HSL 参数"的风格
    # 自行声明可读性约束,不必为每套配色模型在 Python 里加特例。
    # (editorial-mono 的 contrast() 是例外:accent 常为 null,需色相环采样)
    FUNCS = {"min", "max", "isAscending", "contrastHSL"}

    def __init__(self, tokens, params):
        self.tokens = tokens
        self.pos = 0
        self.params = params

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else (None, None)

    def take(self):
        tok = self.peek()
        self.pos += 1
        return tok

    def expect_op(self, op):
        kind, val = self.take()
        if kind != "op" or val != op:
            raise ValueError(f"期望 '{op}',实际得到 {val!r}")

    def parse(self):
        result = self.implication()
        if self.pos != len(self.tokens):
            raise ValueError(f"表达式末尾有多余内容: {self.tokens[self.pos:]}")
        return result

    def implication(self):
        left = self.comparison()
        if self.peek() == ("op", "=>"):
            self.take()
            right = self.implication()
            return (not left) or bool(right)
        return left

    def comparison(self):
        left = self.arith()
        kind, val = self.peek()
        if kind == "op" and val in (">=", "<=", "==", ">", "<"):
            self.take()
            right = self.arith()
            return {
                ">=": left >= right, "<=": left <= right, "==": left == right,
                ">": left > right, "<": left < right,
            }[val]
        return left

    def arith(self):
        left = self.term()
        while self.peek()[0] == "op" and self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            right = self.term()
            left = left + right if op == "+" else left - right
        return left

    def term(self):
        left = self.factor()
        while self.peek()[0] == "op" and self.peek()[1] in ("*", "/"):
            op = self.take()[1]
            right = self.factor()
            left = left * right if op == "*" else left / right
        return left

    def factor(self):
        kind, val = self.peek()
        if kind == "op" and val == "-":
            self.take()
            return -self.factor()
        if kind == "op" and val == "(":
            self.take()
            result = self.implication()
            self.expect_op(")")
            return result
        if kind == "num":
            self.take()
            return val
        if kind == "ident":
            self.take()
            if self.peek() == ("op", "("):
                return self.call(val)
            if val not in self.params:
                raise ValueError(f"invariant 引用了未声明的参数 {val}")
            return self.params[val]
        raise ValueError(f"意外的 token: {kind} {val!r}")

    def call(self, name):
        if name not in self.FUNCS:
            raise ValueError(f"未知函数 {name}(),白名单仅 {sorted(self.FUNCS)}")
        self.expect_op("(")
        args = [self.implication()]
        while self.peek() == ("op", ","):
            self.take()
            args.append(self.implication())
        self.expect_op(")")

        if name in ("min", "max"):
            flat = args[0] if len(args) == 1 and isinstance(args[0], list) else args
            return min(flat) if name == "min" else max(flat)
        if name == "isAscending":
            arr = args[0]
            if not isinstance(arr, list):
                raise ValueError("isAscending() 需要数组参数")
            return all(arr[i] <= arr[i + 1] for i in range(len(arr) - 1))
        if name == "contrastHSL":
            if len(args) != 6:
                raise ValueError(
                    "contrastHSL() 需要 6 个参数: h1,s1,l1,h2,s2,l2")
            fg = _hsl_to_rgb(args[0], args[1], args[2])
            bg = _hsl_to_rgb(args[3], args[4], args[5])
            return _contrast_ratio(fg, bg)


def eval_expr(rule, params):
    return ExprParser(tokenize(rule), params).parse()


# ---------------------------------------------------------------------------
# 第三部分:contrast() 不变式 —— 真实 WCAG 色彩数学,单独实现
#
# accent 常为 null(每卡自动取色),静态校验 profile 时并不知道最终色相。
# 正确语义是:不论 render.py 将来从哪张 hero 图取出什么色相,组的参数
# 都必须保证可读性——因此对整个色相环采样,取最差值校验,而非校验单一定色。
# 若 profile 显式定了 palette.accent,则只需校验那一个确定的色相。
# ---------------------------------------------------------------------------

import colorsys

BASE_INK = (247, 244, 239)  # #F7F4EF,ink0 的混色基底
# 与 render.py 的 accentExtraction 默认输出域取中点,作为"典型自动取色"的代表值。
# 只影响 ink0 的亮度贡献(占比很小),真正决定对比度的是 bg 的饱和度/明度(直接参数)。
REPRESENTATIVE_ACCENT_SAT = 0.75
REPRESENTATIVE_ACCENT_VAL = 0.91


def _srgb_to_linear(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(rgb):
    r, g, b = (_srgb_to_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(rgb1, rgb2):
    l1, l2 = _relative_luminance(rgb1), _relative_luminance(rgb2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _hsl_to_rgb(h, s, l):
    """与 engine.html 的 hslHex() 同一算法,逐行对照移植,保证数值口径一致。"""
    def f(n):
        k = (n + h / 30) % 12
        a = s * min(l, 1 - l)
        c = l - a * max(-1, min(k - 3, 9 - k, 1))
        return round(c * 255)
    return (f(0), f(8), f(4))


def check_contrast_invariant(space, params, min_ratio=4.5):
    ink_tint = params["palette.inkTint"]
    bg_hue_shift = params["palette.bgHueShift"]
    bg_sat0 = params["palette.bgSaturation"][0]
    bg_light0 = params["palette.bgLightness"][0]

    fixed_accent = params.get("palette.accent")
    if fixed_accent:
        m = re.fullmatch(r"#([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})", fixed_accent)
        rf, gf, bf = (int(m.group(i), 16) / 255 for i in (1, 2, 3))
        mx, mn = max(rf, gf, bf), min(rf, gf, bf)
        d = mx - mn
        if d == 0:
            hue = 0.0
        elif mx == rf:
            hue = ((gf - bf) / d) % 6 * 60
        elif mx == gf:
            hue = ((bf - rf) / d + 2) * 60
        else:
            hue = ((rf - gf) / d + 4) * 60
        # accent 已知,直接用其真实 RGB 混色,不再借用代表性 sat/val 近似
        samples = [(hue % 360, (rf * 255, gf * 255, bf * 255))]
    else:
        samples = [
            (hue, tuple(c * 255 for c in colorsys.hsv_to_rgb(
                hue / 360, REPRESENTATIVE_ACCENT_SAT, REPRESENTATIVE_ACCENT_VAL)))
            for hue in range(0, 360, 30)  # 全色相环采样,取最差值
        ]

    worst_ratio = None
    worst_hue = None
    for hue, accent_rgb in samples:
        ink0_rgb = tuple(
            accent_rgb[i] * ink_tint + BASE_INK[i] * (1 - ink_tint) for i in range(3))
        bg_hue = (hue + bg_hue_shift) % 360
        bg_rgb = _hsl_to_rgb(bg_hue, bg_sat0, bg_light0)

        ratio = _contrast_ratio(ink0_rgb, bg_rgb)
        if worst_ratio is None or ratio < worst_ratio:
            worst_ratio, worst_hue = ratio, hue

    passed = worst_ratio >= min_ratio
    detail = (f"最差色相 {worst_hue:.0f}° 时对比度 {worst_ratio:.2f}:1"
              f"(要求 >= {min_ratio})" + ("" if fixed_accent else "  [已按全色相环采样]"))
    return passed, detail


# ---------------------------------------------------------------------------

def check_invariants(space, params):
    """跑 space.json 的 invariants 段,contrast() 走专用色彩数学,其余走通用求值器。"""
    results = []
    for inv in space.get("invariants", []):
        rule, why = inv["rule"], inv["why"]
        if "contrast(" in rule:
            passed, detail = check_contrast_invariant(space, params)
            results.append((rule, why, passed, detail))
            continue
        try:
            passed = bool(eval_expr(rule, params))
            results.append((rule, why, passed, None))
        except (ValueError, KeyError, ZeroDivisionError) as exc:
            results.append((rule, why, False, f"求值出错: {exc}"))
    return results


def main():
    args = parse_args()
    profile, profile_path = load_profile(args.group_dir)

    style_name = profile.get("style")
    preset_name = profile.get("preset")
    if not style_name or not preset_name:
        print(f"错误: {profile_path} 缺少 style 或 preset 字段", file=sys.stderr)
        sys.exit(1)

    space, space_path = render.load_space(style_name)
    preset = render.load_preset(style_name, preset_name)
    # resolve_params 内部已校验"未声明参数键"，越界即在此处 sys.exit(1)
    params = render.resolve_params(space, preset, profile, profile_path)

    print(f"校验 {profile_path}")
    print(f"  风格={style_name}  搭配={preset_name}\n")

    bound_violations = check_param_bounds(space, params)
    print("[ 参数取值域 ]")
    if bound_violations:
        for key, value, msg in bound_violations:
            print(f"  ✗ {key} = {value!r}: {msg}")
    else:
        print("  ✓ 全部参数落在声明域内")

    print("\n[ 跨维不变式 ]")
    invariant_results = check_invariants(space, params)
    invariant_failed = False
    for rule, why, passed, detail in invariant_results:
        mark = "✓" if passed else "✗"
        line = f"  {mark} {rule}"
        if detail:
            line += f"  ({detail})"
        print(line)
        if not passed:
            print(f"      why: {why}")
            invariant_failed = True

    ok = not bound_violations and not invariant_failed
    print(f"\n{'PASS' if ok else 'FAIL'}: {profile_path}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
