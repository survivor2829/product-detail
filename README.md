# 物保云产品详情页生成器

输入产品图 + 参数，自动生成电商详情页长图（PNG）。

---

## 文件结构

```
├── app.py                 # Flask 后端（Web UI 入口，python app.py 启动）
├── render.py              # 核心渲染逻辑：normalize → Playwright 截图
├── generate.py            # 命令行入口（调用 render.py）
├── template.html          # 详情页 HTML 模板（Jinja2，750px 宽，五屏）
├── requirements.txt       # Python 依赖
├── product_config.json    # 当前产品配置（命令行模式用）
├── web_ui/
│   └── index.html         # 前端单页应用（四步骤 UI）
├── uploads/               # 上传图片临时目录（自动创建）
├── output/                # 生成结果目录
│   ├── *_detail.png        # 生成的详情页图片
│   └── _temp_preview.html  # 上次渲染的 HTML 预览
└── templates/             # 固定屏图片模板（按产品类型）
    └── 扫地车/
        ├── screen2.jpg
        └── screen4.jpg
```

---

## 快速运行

### 方式一：Web UI（推荐）

```powershell
cd C:\Users\28293\clean-industry-ai-assistant
pip install -r requirements.txt
playwright install chromium
python app.py
```

浏览器打开 **http://localhost:5000**，按步骤填写信息即可生成。

### 方式二：命令行

```powershell
cd C:\Users\28293\clean-industry-ai-assistant
python render.py                        # 使用 product_config.json
python render.py DZ10_config.json       # 指定配置文件
python render.py --scale 1             # 1x 普通分辨率（文件更小）
```

输出文件自动保存到 `output/<型号>_detail.png`，生成后自动打开预览。

### 依赖安装（首次运行）

```powershell
pip install -r requirements.txt
playwright install chromium
```

---

## 换产品：怎么改 product_config.json

### 最简配置（必填字段）

```json
{
  "brand": "德威莱克",
  "brand_en": "DWEILK",
  "product_name": "驾驶式扫地车",
  "model": "DW1250 PLUS",

  "slogan": "主标语，逗号前是第一行",
  "sub_slogan": "副标语，显示在主标语下方",

  "product_image": "C:/绝对路径/产品图.jpg",

  "efficiency_claim": "1台顶8-10人",
  "efficiency_value": "9800m²/h",
  "savings_claim": "26W+元",

  "core_params": {
    "工作效率": "9800m²/h",
    "清扫宽度": "1300mm",
    "尘箱容量": "120L",
    "工作时间": "2-3h"
  },

  "detail_params": {
    "工作效率": "9800m²/h",
    "工作时间": "2-3h",
    "清扫宽度": "1300mm",
    "水箱容量": "30L"
  },

  "advantages": ["电瓶续航久", "多场所适用", "多垃圾一机搞定", "效率高驾驶平稳", "大容量尘箱", "易上手操作简单"],

  "dimensions": {
    "length": "1550mm",
    "width": "1300mm",
    "height": "1160mm"
  }
}
```

### 字段说明

| 字段 | 说明 | 示例 |
|------|------|------|
| `model` | 型号，也作为输出文件名 | `"DW1250 PLUS"` → `DW1250_PLUS_detail.png` |
| `slogan` | 主标语，按第一个逗号/句号自动拆成两行 | `"电泳处理工艺，杜绝生锈"` |
| `sub_slogan` | 副标语，显示在主标语下方 | `"适用学校，景区，厂区"` |
| `product_image` | 产品主图绝对路径（用于第1屏和参数屏尺寸图） | Windows 路径用正斜杠 `/` |
| `scene_image` | 实景图路径（可选，不填则复用 product_image） | 同上 |
| `core_params` | 第1屏底部4个核心参数，取前4个 | dict，顺序即显示顺序 |
| `detail_params` | 参数表格，两两一行，奇数条目末行留空 | dict，顺序即显示顺序 |
| `advantages` | 6大硬核优势，恰好6条 | list，固定6个 |
| `efficiency_claim` | VS对比框机器一侧第1行 | `"1台顶8-10人"` |
| `savings_claim` | VS对比框机器一侧第2行（自动拼"一年劲省"前缀） | `"26W+元"` |
| `dimensions` | 参数屏下方尺寸标注 | `{length, width, height}` |

### 多产品并行

为每个产品建一个独立配置文件：

```
DW1250Plus_config.json
H650Plus_config.json
DW2000B_config.json
```

分别运行：

```powershell
python render.py DW1250Plus_config.json
python render.py H650Plus_config.json
```

---

## 模板结构（五屏）

```
第1屏  品牌头部 + 主标语 + 产品主图 + 4个核心参数 + 6大硬核优势
第2屏  固定图片（按产品类型自动匹配）
第3屏  效率对比标题 + 实景图 + 机器 VS 人工对比框
第4屏  固定图片（按产品类型自动匹配）
第5屏  产品参数标题 + 尺寸图 + 参数表格
```

---

## 产品类型模板：如何新增固定屏图片

第2屏和第4屏是固定图片，按 `product_type` 字段自动匹配。

### 文件夹结构

```
templates/
├── 扫地车/
│   ├── screen2.jpg   ← 第2屏固定图（适用场所等宣传图）
│   └── screen4.jpg   ← 第4屏固定图（垃圾对比等宣传图）
├── 洗地机/
│   ├── screen2.jpg
│   └── screen4.jpg
└── 洗扫机器人/
    ├── screen2.jpg
    └── screen4.jpg
```

### 新增产品类型步骤

1. 在 `templates/` 下创建以产品类型命名的文件夹，名称与 config 中 `product_type` 字段完全一致
2. 将两张图命名为 `screen2.jpg` 和 `screen4.jpg` 放入该文件夹（也支持 `.png` / `.jpeg`）
3. 在对应 config 文件中填写 `"product_type": "你的产品类型"`

### 图片优先级

| 优先级 | 来源 | 说明 |
|--------|------|------|
| 1（最高）| `templates/{product_type}/screen2.jpg` | 按类型自动匹配，无需在 config 中写路径 |
| 2 | config 中 `screen2_image` 字段 | 显式指定具体产品的图片（跨类型复用时使用） |
| 3（兜底）| `DEFAULT_SCREEN2`（render.py 中硬编码） | 模板和 config 都没有时使用，会打印警告 |

---

## 已知待解决问题

### 1. 产品图背景未抠图
- **现象**：产品图带白色或杂色背景，放在模板里与底色不融合
- **影响**：第1屏主图、第3屏尺寸图区域
- **解决方向**：上传图片前用 remove.bg、Photoshop 或 AI 工具抠图，保存为 PNG 透明背景

### 2. 无实景/使用场景图
- **现象**：`scene_image` 未单独提供时，第2屏实景图区域与第1屏主图相同
- **影响**：第2屏效果较单调
- **解决方向**：为每个产品单独提供一张实景使用图，在 config 中填 `scene_image` 字段

### 3. 图片区域固定高度，不同比例图留白
- **现象**：宽矮图在高容器里上下有白边，高瘦图在宽容器里左右有白边
- **已处理**：已改为 `object-fit: contain`，图片完整显示不裁剪，留白用白色背景填充
- **后续优化方向**：根据图片实际比例动态调整容器高度（需 JS 配合）

### 4. overlay.py 方案（贴图覆盖方案）未完成
- **背景**：曾探索用 Pillow 直接在原版模板图上覆盖文字/图片的方案（`overlay.py`）
- **现状**：DW2000B Plus 自测大部分区域对齐，但参数表格行高校准未完成
- **结论**：HTML 模板方案（当前方案）更灵活、更易维护，overlay 方案暂搁置

---

## render.py 格式兼容说明

`render.py` 内置 `normalize_config()` 函数，自动处理新旧格式差异：

- `slogan`（单字符串）→ 按标点拆分为 `slogan_line1` + `slogan_line2`
- `core_params` / `detail_params`（dict）→ 转换为模板需要的 list 格式
- `scene_image` 未填 → 自动降级使用 `product_image`
- `machine_name`、`human_cons` 等辅助字段未填 → 给合理默认值
