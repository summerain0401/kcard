# kcard — 知识卡片生成器 规划文档

> 2026-07-25 立项。从 videoPic(手绘课件视频产线)讨论中分出的独立项目。

## 一、定位

**通用知识卡片图片生成器**:结构化 JSON 数据 → HTML 模板 → Playwright 无头截图,产出适合社交平台传播的单张知识卡片图。

关键前提:**卡片形态不止一种**。"西红柿食物百科卡"(毛玻璃风、功效/营养/嘌呤/冷知识布局)只是第一种示例形式,后续会有其他主题、其他版式、其他视觉风格的卡片。因此架构自第一天起就按"多模板注册制"设计,而不是围绕单一版式硬编码。

沿用 videoPic 验证过的核心方法论:
- **排版与文字全部由 HTML 模板渲染,不用 AI 逐张生图** → 文字零错误、风格一致、可批量
- **确定性渲染**:同一份数据重复渲染像素级一致,一切随机(若有)用内容做种子
- **AI 只负责两件事**:① 填写卡片数据 JSON(内容环节);② 生成无文字的主图素材(可选,如 3D 玻璃质感西红柿)

## 二、目录结构

```
kcard/
  PLAN.md                     # 本文档
  templates/
    food-glass/               # 模板 = 一种卡片形态,一个目录一个模板
      card.html               # 版式 + 样式 + renderCard(data) 函数
      schema.md               # 该模板的数据字段说明(给 AI 填数据时看)
      sample.json             # 示例数据(即西红柿卡)
    <next-form>/              # 后续新形态照此增加,互不干扰
  scripts/
    render.py                 # 唯一渲染脚本,模板无关
  assets/
    fonts/                    # 本地字体,按模板需要添加
  cards/
    tomato/
      card.json               # {"template": "food-glass", "data": {...}}
      hero.png                # 主图素材(如需要)
      output.png              # 渲染产物
```

### 多模板机制

- 每张卡的 `card.json` 顶层声明 `template` 字段,render.py 据此加载 `templates/<name>/card.html`
- 模板之间**完全隔离**:各自的 HTML/CSS/JS、schema、字体栈、画布尺寸自行定义,新增模板不改动既有模板
- render.py 保持模板无关:加载模板 → 注入 data → 等 `document.fonts.ready` → 截图。约 100 行,骨架抄自 videoPic 的 summary.py

## 三、首个模板:food-glass(西红柿卡风格)

视觉要素(对照参考图):
- 毛玻璃卡片(backdrop-filter blur + 半透明白)浮在柔和渐变/主图虚化背景上
- 模块化网格:主图区 + 核心功效 / 食用方法 / 营养价值 / 食用注意 / 含量指标 / 冷知识 / 适合人群 等信息块
- 信息块数量与种类由数据驱动,缺哪块就不渲染哪块(不同食物侧重不同)
- 图标用系统 emoji(参考图即 Apple 3D emoji 风格),零素材成本
- 字体:现代无衬线中文字体(候选 MiSans / HarmonyOS Sans / 思源黑体,本地加载)
- 输出:1080 宽 @2x(社交平台竖图/方图,具体比例定模板时敲定)

主图素材:AI 生图(玻璃质感 3D 渲染风,画面内**不含任何文字**,故不违背文字零错误原则)或实拍抠图,存放在卡片目录内,模板以 `<img>` 引入。

## 四、与 videoPic 的关系

| 项目 | videoPic | kcard |
|---|---|---|
| 产出 | 课件视频 + 长图 + 笔记 | 单张知识卡片图 |
| 视觉 | 暖米白手绘风 | 每模板自定义(首个为毛玻璃现代风) |
| 数据单元 | episode(多卡时间轴) | 单卡 |
| 复用 | — | 渲染方法论、render 脚本骨架、`.venv` |

- **venv 直接共用** videoPic 的 `/Volumes/Samsung/videoPic/.venv`(Python 3.13,playwright + chromium 已装,依赖完全覆盖 kcard 所需),不重装环境;若日后两项目依赖分叉再各自独立
- 两项目守则互不适用:videoPic 的 CLAUDE.md / split.md / run.sh 不管辖本项目

## 五、工作流(单卡)

1. 确定主题与模板 → AI 按 `templates/<t>/schema.md` 产出 `cards/<topic>/card.json`
2. 准备主图素材(如模板需要)→ `cards/<topic>/hero.png`
3. `python scripts/render.py cards/<topic>` → `output.png`
4. 人工抽查文字与版式

## 六、路线图

- **P1 基建 + 首模板**:render.py、food-glass 模板设计定稿、西红柿样卡跑通全流程 ← 当前阶段
- **P2 第二形态**:接入下一种卡片形式(主题待定),验证多模板机制的隔离性,沉淀"新增模板 checklist"
- **P3 批量化**:同模板批量产卡(一批 JSON 一次渲染)、建立本项目 CLAUDE.md 固化守则

## 七、模型分配(沿用既有策略)

- 模板视觉设计、render.py 基建、schema 制定 → 高档模型(Fable/Opus),一次成型
- 日常填卡数据、批量产卡 → 中档模型(Sonnet)
