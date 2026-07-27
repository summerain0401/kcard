# kcard

结构化 JSON → HTML 模板 → Playwright 无头截图,产出适合社交平台传播的知识卡片图。

排版与文字全部由 HTML 模板渲染,不用 AI 逐张生图,因此**文字零错误、风格一致、可批量**;
同一份数据重复渲染像素级一致。AI 只负责两件事:填卡片数据、生成无文字的主图素材。

## 快速开始

```bash
# 环境:Python 3.13 + playwright(chromium)+ Pillow + numpy + scipy
python scripts/cutout.py cards/tomato/hero.png   # 主图去底 → hero-cut.png
python scripts/render.py cards/tomato            # 取色 + 渲染 → output.png
```

> ⚠️ **字体依赖**:模板使用 macOS 系统字体(Songti SC / Didot / PingFang SC)。
> 在 Linux/Windows 上渲染会 fallback 到其他字体,版式效果与设计稿不一致。

## 目录结构

```
templates/<name>/     # 一个目录 = 一种卡片形态
  card.html           #   版式 + 样式 + renderCard(data)
  schema.md           #   数据字段说明(填卡前先读)
  sample.json         #   示例数据
scripts/
  render.py           # 渲染脚本,模板无关
  cutout.py           # 主图去底(中性背景键出为 alpha)
cards/<topic>/
  card.json           # {"template": "...", "data": {...}}
  hero.png            # AI 生成的主图素材(需透明底)
  hero-cut.png        # 去底后的素材
  output.png          # 渲染产物
```

`card.json` 顶层用 `template` 字段声明使用哪个模板,模板之间完全隔离,
新增模板不影响既有模板。字段详见对应模板的 `schema.md`。

## 设计原则

**配色**:底色不用主体色,用与主体色相配的色。主体色和底色同色系时主体会淹没在
背景里;黑配红之所以高级,是因为对比让主体色达到最强视觉冲击。所以取主体色的
**互补色相**压成极深近黑作底(番茄红→青黑、香蕉金→蓝黑、葡萄紫→橄榄黑),
主体色只保留在章节编号、指标线等细节上做呼应。整套配色由 `themeColor` 自动推导,
`themeColor` 留空时由 `render.py` 从 hero 图提取。

**版式**:编辑排版风(竖排宋体大标题 + Didot 衬线巨字 + 细线章节 + 衬线编号),
不用 emoji 图标、不用玻璃拟态与发光效果。

## 现有卡片

西红柿 · 香蕉 · 苹果 · 橙子 · 葡萄

其中苹果/橙子/葡萄暂用 emoji 作主视觉,待补真实主图素材
(生图 prompt 模板见 `templates/food-glass/schema.md`)。
