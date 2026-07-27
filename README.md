# kcard

结构化 JSON → HTML 渲染 → Playwright 无头截图,产出适合社交平台传播的知识卡片图。

项目分「设计部 / 生产部」两层:设计部产出风格系统(视觉规范 + 参数空间),
生产部按业务分组,各组选定一套风格后自由搭配、批量产卡。详见 `PLAN.md`。

排版与文字全部由 HTML 渲染,不用 AI 逐张生图,因此**文字零错误、风格一致、可批量**;
同一份数据重复渲染像素级一致。AI 只负责两件事:填卡片数据、生成无文字的主图素材。

## 快速开始

```bash
# 环境:Python 3.13 + playwright(chromium)+ Pillow + numpy + scipy
python scripts/cutout.py production/food-encyclopedia/cards/tomato/hero.png   # 主图去底 → hero-cut.png
python scripts/render.py production/food-encyclopedia/cards/tomato            # 取色 + 渲染 → output.png
```

> ⚠️ **字体依赖**:风格使用 macOS 系统字体(Songti SC / Didot / PingFang SC)。
> 本项目按 macOS 单机渲染设计,不追求跨平台一致;在 Linux/Windows 上会
> fallback 到其他字体,版式效果与设计稿不一致。

## 目录结构

```
design/styles/<name>/    # 一个目录 = 一套风格(设计部所有)
  STYLE.md               #   风格宪法:构成要素、禁则、高级感判据
  space.json             #   参数空间:可调维度的取值域 + 跨维不变式
  engine.html            #   参数化渲染引擎(通用外观 + renderCard)
  layouts/<layout>.css   #   版式骨架,只管头版定位,渲染时注入
  presets/<preset>.json  #   示范搭配:选定骨架 + 一整套参数
  preview/<preset>.png   #   各搭配的预览图
  schema.md sample.json  #   数据字段说明与示例数据
production/<group>/      # 一个目录 = 一个生产组(生产部所有)
  profile.json           #   选 style + preset,可覆写 layout 与 params
  cards/<topic>/
    card.json            #   {"data": {...}},纯内容,不含风格声明
    hero.png             #   AI 生成的主图素材(需透明底)
    hero-cut.png         #   去底后的素材
    output.png           #   渲染产物
scripts/
  render.py              # 渲染脚本,读 profile 定位风格与搭配
  cutout.py              # 主图去底(中性背景键出为 alpha)
  batch.py               # 按生产组批量产卡,共享单浏览器实例
  style-check.py         # 组上线闸门:参数取值域 + 跨维不变式校验
  regress.py             # 改风格后,对在用该风格的组重渲染做像素 diff
  gallery.py             # 从各风格的 STYLE.md/space.json/presets 生成 design/GALLERY.md
```

```bash
# 生产渲染(单卡)
python scripts/render.py production/food-encyclopedia/cards/tomato
# 按组批量产卡
python scripts/batch.py production/food-encyclopedia
# 组上线前的闸门校验
python scripts/style-check.py production/food-encyclopedia
# 风格自证预览(不碰 production/)
python scripts/render.py --style editorial-mono --preset airy
# 改动某套风格后,确认不破坏所有在用该风格的组(默认只检查不写)
python scripts/regress.py editorial-mono
# 更新选型看板
python scripts/gallery.py
```

生产组的卡片本身不声明使用哪套风格,由同组 `profile.json` 的 `style` / `preset`
决定。参数优先级 `profile.params > preset.params`,`space.json` 未声明的参数键
一律报错——未声明即不可调,需向设计部提案扩展。
风格之间完全隔离,新增风格不影响既有风格。字段详见对应风格的 `schema.md`。

## 风格与生产组

每套风格有自己的设计原则、构成要素与禁则,不再有"全项目统一"的规则——
两套风格甚至气质相反(一深色一浅色)。选型与现状看 `design/GALLERY.md`,
某套风格的具体规则看它自己的 `styles/<name>/STYLE.md`。

现有生产组见 `production/` 目录,各组的选题范围与口吻规范见其 `brief.md`。
