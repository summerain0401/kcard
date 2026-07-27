# almanac 风格数据字段说明

博物图鉴风(米色纸底 + 横排衬线 + 罗马编号 + 引线标签)。视觉规范见同目录
`STYLE.md`,可调参数见 `space.json`。

**与 editorial-mono 共用同一套通用字段**——已有生产组的 `card.json` 不加任何
字段即可切到本风格渲染,只是不会出现引线标签。

`production/<group>/cards/<topic>/card.json` 顶层结构(纯内容,不含风格声明):

```json
{
  "data": { ... 见下 }
}
```

使用哪套风格由同组 `production/<group>/profile.json` 的 `style` / `preset` 决定。

## 通用字段(data)

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | string | 是 | 主体名称,渲染为横排衬线大标题 |
| `nameEn` | string | 否 | 拉丁名/英文名,与分类同行显示,并出现在页脚学名行 |
| `category` | string | 否 | 分类信息(如"银杏科 · 银杏属") |
| `emoji` | string | 否 | 无 `hero` 时的兜底主视觉 |
| `hero` | string | 否 | 标本图文件名,相对本卡片目录。素材要求见下 |
| `themeColor` | string | 否 | 点缀色(hex)。留空则由 `render.py` 从 hero 图自动提取 |
| `blocks` | array | 是 | 信息块列表,数量与顺序完全由数据决定 |

## 本风格特有字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `specimenLabels` | array | 否 | 引线标签,**最多 4 条**,超出部分丢弃。每项 `{"text": "叶脉", "side": "left"}` |

`side` 取 `"left"` 或 `"right"`,表达的是**该部位在主体的哪一侧**这一语义,
而非版面位置——具体摆到画面何处由版式骨架决定(如 `c-field-note` 会把两侧
标签统一收到标本左方)。**数据不提供坐标**:坐标交给 AI 填写不可靠,且会把
版式决策泄漏到内容层。

无此字段时不渲染引线,其余部分正常显示。

## blocks[] 每项字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `title` | string | 是 | 信息块标题,前面自动配罗马编号 `I. II. III.` |
| `style` | string | 是 | 内容呈现方式,见下表 |
| `span` | string | 否 | 值为 `"full"` 时占满整行 |
| `items` | array | 视 style | `list`/`tags`/`metric` 需要 |
| `text` | string | 视 style | `text` 需要 |

### style 取值

- **`list`**:要点列表,每条以破折号起首(非圆点)
- **`tags`**:中点分隔的一行,不做胶囊(宪法 H4 禁圆角)
- **`metric`**:目录页式量表。`items` 为 `{"label", "value", "percent"}`,
  `percent` 驱动点线上的实线填充长度。一行读完「项目——比例——数值」
- **`text`**:整段文字,左侧配竖线。通常搭配 `"span": "full"`

## 标本(hero)素材要求

本风格是**浅色纸底**,与 editorial-mono 的深色底要求相反:

- **背景必须透明(PNG 抠图)**。白底素材在米色纸上会露出明显的白色方块
- **画面内不得含任何文字/水印/logo**
- 正方形构图,建议 ≥1000×1000px,主体居中
- 宪法 H5 禁投影——素材自带的投影会与"平面印刷品"的气质冲突,应选无影素材

参考 prompt(英文):

> A botanical illustration of {主体}, vintage scientific engraving style,
> muted natural colors, fine line work, centered composition,
> **transparent background, cutout, no background, no shadow**,
> no text, no watermark, no logo, square 1:1, high detail

负面提示词:`text, watermark, logo, shadow, background, gradient, glossy, 3d render, neon`

> 注:`scripts/cutout.py` 可键出中性色背景,用法见 README。

## 点缀色的自动取色

`themeColor` 不填时,`render.py` 按 `space.json` 的 `accentExtraction` 从 hero 图
提取,**输出域被刻意压低**(饱和 ≤0.60、明度 ≤0.65)以满足宪法 H2——图鉴用赭石、
朱砂、墨绿这类沉稳色。引擎侧另有一道兜底钳制,即使直接传入明快色也会被压回。

这与 editorial-mono 的高饱和高明度输出形成对照,是"不同风格对什么算主体色、
提亮到什么水平的判断不同"的体现。

## 尺寸与产出

- 画布宽 1080px,高度随内容自适应(`render.py` 用 full_page 截图)
- 2x 设备缩放,输出实际像素为 2160px 宽

## 示例

见同目录 `sample.json`(银杏)。
