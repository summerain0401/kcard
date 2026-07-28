# aurora-glass 数据契约

> 本文件说明本风格如何消费 `card.json` 的 `data`。字段总集是 kcard 的通用结构,
> 各风格共享;本文件只记**本风格特有的处理与差异**。宪法见 `STYLE.md`,
> 参数取值域见 `space.json`。

## 一句话

本风格**不新增任何字段**,且**刻意忽略 `emoji`**。
任何已有生产组的 `card.json` 不加字段即可切换过来渲染。

## 字段表

| 字段 | 类型 | 必填 | 本风格如何用 |
|---|---|---|---|
| `name` | string | 是 | 头版大标题。无衬线、负字距,是版面唯一的重量级文字 |
| `nameEn` | string | 强烈建议 | 三处用到:副标题尾部、页脚左侧(转大写)、**以及缺主图时的字母印记**(取首字母)。本风格对它的依赖高于另两套 |
| `category` | string | 否 | 副标题首段,与 `nameEn` 同行,中间以大字距分开 |
| `hero` | string | 否 | 主体图。相对文件名由 `render.py` 换成 `file://` 绝对 URI。缺失时走字母印记(见下) |
| `themeColor` | string `#RRGGBB` | 否 | 强调色。**同时是背景色斑的色相来源**——四团色斑的色相都由它按 `orb.hueShifts` 旋转推导 |
| `emoji` | string | — | **被忽略**。宪法 H8 禁 emoji,详见下一节 |
| `blocks[]` | array | 是 | 章节。同时驱动章节导航片(E5)的片数 |

### `blocks[]` 各项

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | string | 章节标题,前面自动配 `01` `02` … 的 accent 编号 |
| `style` | `list` \| `tags` \| `metric` \| `text` | 决定正文渲染形态,见下表 |
| `span` | `"full"` | 可选。占满整行,不受 `layout.columns` 影响 |
| `items` | array | `list`/`tags` 为字符串数组;`metric` 为对象数组 |
| `text` | string | 仅 `style: text` 使用 |

`metric` 的每一项:`{ "label": "赤道直径", "value": "120,536 km", "percent": 82 }`。
`percent` 会被钳制到 0–100,只驱动进度条长度,不参与文字。

## 三处与另两套风格不同的地方

### 1. 无主图时走「字母印记」,不退回 emoji

宪法 H8 禁 emoji。因此本风格的缺图兜底是 `nameEn` 的**首字母**,
渲染成一个巨型的、极淡填充 + 细描边的字(构成要素 E7)。
`nameEn` 也缺失时才退到 `name` 的首字。

后果:**`nameEn` 在本风格下是准必填字段**。缺了它,兜底会退化成一个中文字,
虽然不会出错,但字母印记的版面效果会打折——设计上它是当作拉丁字形来构图的。

### 2. `themeColor` 决定的不只是强调色

在另两套风格里 `themeColor` 只影响点缀。本风格里它还是**背景四团色斑的色相原点**:

```
色斑 i 的色相 = hue(themeColor) + orb.hueShifts[i]
```

所以换一个 `themeColor`,整张卡的背景配色会整体旋转,而不只是编号变色。
生产组若想让全组背景统一,应在 `profile.json` 里设 `params["palette.accent"]`
固定色,而不是逐卡填 `themeColor`。

取色优先级(与另两套一致,由 `render.py` 编排):
`profile.params["palette.accent"]` > 卡自己的 `themeColor` > 从 `hero` 图自动提取。
注意最后一档**只在有 `hero` 图时触发**——走字母印记的卡不会自动取色,
其配色来自 preset 或 profile 的默认值。

### 3. `blocks` 是内容池,不是渲染清单

**写满 6 块,渲染几块由排版决定。** 这是本风格 2026-07-28 起的模型,
也是与另两套风格最大的契约差异。

```
card.json 写 6 块  ──►  骨架按 layout.blockLimit 取前 N 块  ──►  出图
  (内容池,上限 6)          (4~6,逐骨架不同)
```

- **顺序即优先级**。取的是**前 N 块**,所以最重要的写在前面。不提供
  `priority` 之类的字段——那会把版式决策泄漏回内容层,和本项目
  「坐标不交给内容填」是同一条理由。
- **写满不浪费**。同一份内容,`amber`(拼贴)取 4 块、`quartz`(索引)取 6 块,
  换个搭配就能露出更多,不必回头改 `card.json`。
- **超过 6 块才是浪费**:`layout.blockLimit` 的取值域上限就是 6,
  写第 7 块不会被任何骨架取到。
- 章节导航片(E5)的片数跟随**实际渲染的**块数,不是池子总数。

#### 各骨架的取块数与代价

| 搭配 | 骨架 | 取块 | 长宽比 | 缩略图下正文 |
|---|---|---|---|---|
| `amber` | `e-mosaic` | 4 | 1:1.67 | 12.2pt |
| `onyx` | `c-bleed-poster` | 5 | 1:1.81 | 11.2pt |
| `ember` | `a-panel-split` | 4 | 1:1.88 | 11.7pt |
| `verdant` | `d-timeline` | 5 | 1:2.15 | 9.8pt |
| `mist` | `b-panel-center` | 5 | 1:2.19 | 10.0pt |
| `quartz` | `f-index` | 6 | 1:2.33 | 8.7pt |

图越长,手机按"整图适配"显示时(聊天缩略图、九宫格)被缩得越小,正文的
视觉字号跟着掉——所以取块数不是随便调大的旋钮。要装更多内容,优先换到
密度更高的骨架,而不是把当前骨架的 `blockLimit` 往上顶。

单块内部的条目数同样计入预算:`list` 建议 2–3 条,`text` 建议 3 行以内。

完整判据与逐骨架实测见 `STYLE.md` 第四节。

## 最小可渲染示例

```json
{
  "data": {
    "name": "土星",
    "nameEn": "Saturn",
    "category": "行星 · 气态巨行星",
    "themeColor": "#D9A441",
    "blocks": [
      {
        "title": "基本参数",
        "style": "metric",
        "items": [
          { "label": "赤道直径", "value": "120,536 km", "percent": 82 }
        ]
      },
      {
        "title": "结构特征",
        "style": "list",
        "items": ["无固态表面,大气自氢氦渐次过渡为液态金属氢"]
      },
      { "title": "别称", "style": "tags", "items": ["镇星", "填星"] },
      { "title": "志异", "style": "text", "span": "full", "text": "环并非永恒。" }
    ]
  }
}
```

同目录的 `sample.json` 是本风格的自证样例(注意它是**裸 `data` 对象**,
没有外层 `{"data": ...}` 包装——那是 `card.json` 才有的一层)。
