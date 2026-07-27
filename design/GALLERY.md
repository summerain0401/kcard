# 风格选型看板

> 设计部与生产部**唯一的交汇点**。生产部选型只需读这一页;
> 设计部改动风格前先看这里评估影响面。
>
> 本文件由 `scripts/gallery.py` 从各风格的 `STYLE.md` / `space.json` /
> `layouts/` / `presets/` 自动生成,**请勿手改**——改风格自身的文件,
> 重新运行 `python scripts/gallery.py` 即可更新本页。

## 在用一览

| 风格 | 版本 | 骨架 | 搭配 | 被哪些组使用 |
|---|---|---|---|---|
| [almanac](styles/almanac/) | 1.0.0 | 3 | 2 | `english-vocab` |
| [editorial-mono](styles/editorial-mono/) | 1.0.0 | 3 | 3 | `food-encyclopedia` |

「暂无组使用」是正常状态——设计部可以先囤方案,不必等生产需求。风格与生产组的新增彼此独立,详见 `PLAN.md` 第五节。

---

## almanac

十九世纪博物学图鉴 / 百科全书的印刷品质感。米色纸底、深墨横排衬线标题、
学术罗马编号、双线分隔、标本式居中构图,以及本风格的标志性元素——
**从主体引出的细线标签**。

视觉张力来自**印刷工艺的克制与秩序**,不来自对比度或特效。
适用于「一个主体 + 若干信息块」的百科式知识点,与 `editorial-mono`
覆盖同一类内容但气质相反:一个是暗夜画册,一个是纸本图鉴。

| | |
|---|---|
| 版本 | 1.0.0 |
| 可调维度 | 34 个(完整取值域见 `space.json`)|
| 硬约束 | 8 条(完整规则见 [STYLE.md](styles/almanac/STYLE.md))|
| 被哪些组使用 | `english-vocab` |

**骨架**

| 名称 | 简介 |
|---|---|
| `a-plate-center` | 经典图版:标题居上,标本居中,引线标签左右分列 |
| `b-plate-left` | 书籍插页:标本在左作插图,标题与说明在右 |
| `c-field-note` | 田野笔记:标题压顶偏左,标本偏置右下,留白在左上 |

**搭配**

| 名称 | 说明 | 预览 |
|---|---|---|
| `field` · 田野 · 手记 | 对角构图的速写本气质:纸色更黄更旧、纸纹加重、暗角加深,版面收紧,标本推到右下角。适合松弛的手记感选题,或主体形态不规整、不宜端正陈列的素材。 | [field.png](styles/almanac/preview/field.png) |
| `plate` · 图版 · 正统 | almanac 的基准搭配。米色纸、暖褐墨、居中标本、左右引线,最接近十九世纪图鉴正版的样子。参数全部取 space.json 的 default,是其余搭配的起点。 | [plate.png](styles/almanac/preview/plate.png) |

---

## editorial-mono

深色编辑排版(画册 / 杂志风)。视觉张力来自**排版层次**与**克制用色**,
不来自特效——竖排宋体大标题、Didot 衬线巨字、细线分章、衬线编号,
主体色只作点缀。适用于「一个主体 + 若干信息块」的百科式知识点。

| | |
|---|---|
| 版本 | 1.0.0 |
| 可调维度 | 31 个(完整取值域见 `space.json`)|
| 硬约束 | 9 条(完整规则见 [STYLE.md](styles/editorial-mono/STYLE.md))|
| 被哪些组使用 | `food-encyclopedia` |

**骨架**

| 名称 | 简介 |
|---|---|
| `a-title-left` | 标题竖排在左,主体居中偏右,巨字压右上角 |
| `b-type-dominant` | 巨字为主视觉,主体缩小退居右下角 |
| `c-hero-bleed` | 主体放大出血到右上,文字轴退到左侧,巨字沉底 |

**搭配**

| 名称 | 说明 | 预览 |
|---|---|---|
| `airy` · 疏朗 · 单栏长卷 | 单栏竖排,字号放大、行距拉开、留白加厚,噪点压到几乎不可见。适合内容条目少但每条较长、希望从容阅读的选题。卡片会明显变高,适配长图分享场景。 | [airy.png](styles/editorial-mono/preview/airy.png) |
| `classic` · 经典 · 标题主导 | editorial-mono 的基准搭配,等同 2026-07-27 引擎化之前的原始视觉。竖排宋体标题占主导,主体居中偏右,巨字压右上角。参数全部取 space.json 的 default,是其余搭配的起点与像素基准。 | [classic.png](styles/editorial-mono/preview/classic.png) |
| `stark` · 冷峻 · 主体出血 | 主体放大出血到右上角,底色压得更深更中性,噪点关闭,accent 微染收到最低,行距收紧。对比最强、最锋利的一版。适合质感精良的主图素材,以及希望画面压过文字的选题。 | [stark.png](styles/editorial-mono/preview/stark.png) |

