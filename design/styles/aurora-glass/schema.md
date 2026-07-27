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

### 3. 章节数会影响版面

`blocks` 的数量直接决定章节导航片(E5)的片数,上限 6 片。
少于 3 个章节时导航片会显得可有可无,多于 6 个时超出部分不显示。
**3–6 个章节是本风格的舒适区**。

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
