"""
详情页覆盖生成工具 v2
原理：在原版模板图片上，精准覆盖需要变化的区域（文字/图片），其余设计元素保持原图不动。

用法：
  python overlay.py                        # 使用默认配置 product_config.json
  python overlay.py H650Plus_config.json   # 指定其他产品配置
  python overlay.py --debug               # 显示红色标记框（调试坐标用）
"""

import json, sys, os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ─── 路径 ───────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# 从 file_paths.json 取模板图片的真实路径（处理中文路径问题）
with open(BASE_DIR / "file_paths.json", encoding="utf-8") as _f:
    _PATHS = json.load(_f)

# 语义图片映射（img_hires / img_scene 等 -> 实际 OS 路径）
with open(BASE_DIR / "image_map.json", encoding="utf-8") as _f:
    IMAGE_MAP = json.load(_f)

def _find(keyword):
    for k, v in _PATHS.items():
        if keyword in k:
            return v
    raise KeyError(f"找不到含 '{keyword}' 的文件")

def resolve_image(cfg, key_field):
    """从 cfg 中解析图片路径：支持 image_key（语义映射）或直接路径"""
    key = cfg.get(key_field)
    if not key:
        return None
    series = cfg.get("product_series", "sweeper")
    # 如果是语义键（如 "img_hires"），从 IMAGE_MAP 查找
    if series in IMAGE_MAP and key in IMAGE_MAP[series]:
        return IMAGE_MAP[series][key]
    # 否则当做直接文件路径使用
    if Path(key).exists():
        return key
    print(f"  [警告] 图片路径未找到: {key}")
    return None

TPLS = {
    "sw01": _find("260312_01"),
    "sw03": _find("260312_03"),
    "sw07": _find("260312_07"),
    "sw02": _find("260312_02"),   # 固定屏：适用场所
    "sw04": _find("260312_04"),   # 固定屏：垃圾对比
    "sw_icons": _find("3"),       # 固定屏：6大硬核优势
}

# ─── 字体 ───────────────────────────────────────────────────────────────
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
FONT_REG  = "C:/Windows/Fonts/msyh.ttc"

def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()

# ─── 坐标配置（基于模板原图 790px 宽，坐标已精确标定）─────────────────
#
# box = (left, top, right, bottom)  覆盖矩形（原内容将被背景色遮住）
# xy  = (x, y)                      新文字绘制起点（左上角）
# bg  = (R,G,B)                     覆盖矩形填充色（取自原图背景）
# fg  = (R,G,B)                     新文字颜色
#
COORD = {

    # ════════════════════════════════════════════════════════════════
    # 第1屏 _01.jpg (790×2330)
    # ════════════════════════════════════════════════════════════════
    "sw01": {

        # 右上角产品型号
        "model": {
            "box": (218, 148, 668, 180),
            "xy":  (220, 150),
            "bg":  (255, 255, 255),
            "fg":  (70,  70,  70),
            "font": FONT_REG,
            "size": 20,
            "align": "left",
        },

        # 大标语第1行（如"封闭大驾，"）
        "slogan1": {
            "box": (24, 205, 730, 290),
            "xy":  (26, 207),
            "bg":  (255, 255, 255),
            "fg":  (12,  12,  12),
            "font": FONT_BOLD,
            "size": 76,
            "align": "left",
        },

        # 大标语第2行（如"背街小巷用。"）
        "slogan2": {
            "box": (24, 295, 750, 383),
            "xy":  (26, 297),
            "bg":  (255, 255, 255),
            "fg":  (12,  12,  12),
            "font": FONT_BOLD,
            "size": 76,
            "align": "left",
        },

        # 副标语（如"专业解决道路清扫难题"）
        "sub_slogan": {
            "box": (72, 388, 510, 420),
            "xy":  (74, 390),
            "bg":  (255, 255, 255),
            "fg":  (90,  90,  90),
            "font": FONT_REG,
            "size": 24,
            "align": "left",
        },

        # 产品主图区域（整块替换）
        "product_img": {
            "box": (0, 428, 790, 1140),   # paste 区域
        },

        # 4个核心参数值（大数字，白色底）
        # 每格宽约 197px，center_x 为各格中心
        # 实测原图参数值位于 y≈1270~1315（比初始估算低127px）
        "param_values": [
            {"center_x": 98,  "box": (4,   1265, 192,  1315), "bg": (255,255,255), "fg": (12,12,12), "font": FONT_BOLD, "size": 34},
            {"center_x": 295, "box": (197, 1265, 393,  1315), "bg": (255,255,255), "fg": (12,12,12), "font": FONT_BOLD, "size": 34},
            {"center_x": 493, "box": (394, 1265, 590,  1315), "bg": (255,255,255), "fg": (12,12,12), "font": FONT_BOLD, "size": 34},
            {"center_x": 691, "box": (591, 1265, 786,  1315), "bg": (255,255,255), "fg": (12,12,12), "font": FONT_BOLD, "size": 34},
        ],

        # 4个核心参数标签（小字，白色底）
        "param_labels": [
            {"center_x": 98,  "box": (4,   1318, 192,  1352), "bg": (255,255,255), "fg": (130,130,130), "font": FONT_REG, "size": 20},
            {"center_x": 295, "box": (197, 1318, 393,  1352), "bg": (255,255,255), "fg": (130,130,130), "font": FONT_REG, "size": 20},
            {"center_x": 493, "box": (394, 1318, 590,  1352), "bg": (255,255,255), "fg": (130,130,130), "font": FONT_REG, "size": 20},
            {"center_x": 691, "box": (591, 1318, 786,  1352), "bg": (255,255,255), "fg": (130,130,130), "font": FONT_REG, "size": 20},
        ],
    },

    # ════════════════════════════════════════════════════════════════
    # 第3屏 _03.jpg (790×1280)
    # ════════════════════════════════════════════════════════════════
    "sw03": {

        # 大标题中的人数（如"12-15"，红色大字）
        # 实测：原图红色"12-15" x=244~434，背景(233,236,241)，"人"从x=435开始
        "people_count": {
            "box": (241, 53, 436, 143),
            "xy":  (244, 55),
            "bg":  (233, 236, 241),
            "fg":  (204, 26,  26),
            "font": FONT_BOLD,
            "size": 82,
            "align": "left",
        },

        # 大标题中的效率数字（如"14600m²/h"，红色）
        # "效率高达" 为原图静态文字（实测红色数字从 x=303 开始）
        "efficiency": {
            "box": (300, 148, 660, 222),
            "xy":  (303, 150),
            "bg":  (233, 236, 241),  # 模板背景色（实测）
            "fg":  (204, 26,  26),
            "font": FONT_BOLD,
            "size": 68,
            "align": "left",
        },

        # 产品实景图（整块替换）
        "scene_img": {
            "box": (0, 228, 790, 860),
        },

        # 左侧机器对比框 - 第1行统计（"1台顶12-15人"）白字红底
        # 原图是一个红色圆角框包含两行，用一个大框同时覆盖两行
        "vs_stat1": {
            "box": (18, 1096, 380, 1150),
            "xy":  (20, 1100),
            "bg":  (204, 26,  26),
            "fg":  (255, 255, 255),
            "font": FONT_BOLD,
            "size": 28,
            "align": "left",
        },

        # 第2行统计（用同色背景无缝接续第1行）
        "vs_stat2": {
            "box": (18, 1150, 380, 1204),
            "xy":  (20, 1154),
            "bg":  (204, 26,  26),
            "fg":  (255, 255, 255),
            "font": FONT_BOLD,
            "size": 28,
            "align": "left",
        },
    },

    # ════════════════════════════════════════════════════════════════
    # 第7屏 _07.jpg (790×1766)
    # ════════════════════════════════════════════════════════════════
    "sw07": {

        # 产品尺寸图区域（整块替换）
        "dim_img": {
            "box": (0, 110, 790, 1080),
        },

        # 尺寸标注：宽度（如"1900mm"）
        "dim_width": {
            "box": (44, 993, 228, 1020),
            "xy":  (46, 995),
            "bg":  (235, 237, 240),   # 浅灰背景
            "fg":  (40,  40,  40),
            "font": FONT_BOLD,
            "size": 22,
            "align": "left",
        },

        # 尺寸标注：长度（如"2210mm"）
        "dim_length": {
            "box": (380, 993, 565, 1020),
            "xy":  (382, 995),
            "bg":  (235, 237, 240),
            "fg":  (40,  40,  40),
            "font": FONT_BOLD,
            "size": 22,
            "align": "left",
        },

        # 尺寸标注：高度（如"1980mm"，右侧竖向）
        "dim_height": {
            "box": (634, 568, 782, 595),
            "xy":  (636, 570),
            "bg":  (235, 237, 240),
            "fg":  (40,  40,  40),
            "font": FONT_BOLD,
            "size": 22,
            "align": "left",
        },

        # 参数表格（8行，每行约65px，从 y=1183 开始）
        # 实测：第0行文字 y≈1199，第1行文字 y≈1265，行高=(1265-1199)=65
        # 每行格式: [名1, 值1, 名2, 值2]
        # 值1 列: x=185~395  值2 列: x=563~775
        # 名列不替换，只替换值列
        "table_rows": {
            "start_y": 1183,
            "row_height": 65,
            "col1_val": {"x": 187, "w": 205, "fg": (30, 30, 30), "font": FONT_BOLD, "size": 26},
            "col2_val": {"x": 565, "w": 210, "fg": (30, 30, 30), "font": FONT_BOLD, "size": 26},
            # 奇偶行背景色（0-indexed）
            "bg_odd":  (255, 255, 255),
            "bg_even": (245, 245, 245),
        },
    },
}


# ─── 工具函数 ────────────────────────────────────────────────────────────

def sample_bg(img, box):
    """从 box 左上角偏移3px处采样背景色"""
    x = min(box[0] + 3, img.width - 1)
    y = min(box[1] + 3, img.height - 1)
    return img.getpixel((x, y))[:3]

def cover_and_text(img, draw, cfg, text, debug=False):
    """覆盖原文字区域，写入新文字（支持居中/左对齐）"""
    box = cfg["box"]
    bg  = cfg.get("bg") or sample_bg(img, box)

    if debug:
        draw.rectangle(box, outline=(255, 0, 0), width=3)
    else:
        draw.rectangle(box, fill=bg)

    if not text:
        return

    fnt = font(cfg["font"], cfg["size"])
    fg  = cfg["fg"]
    align = cfg.get("align", "left")

    if align == "center":
        box_w = box[2] - box[0]
        box_h = box[3] - box[1]
        bbox = draw.textbbox((0, 0), text, font=fnt)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = box[0] + (box_w - tw) // 2
        ty = box[1] + (box_h - th) // 2
        draw.text((tx, ty), text, font=fnt, fill=fg)
    else:
        draw.text(cfg["xy"], text, font=fnt, fill=fg)

def cover_centered(img, draw, cfg, text, debug=False):
    """按 center_x 水平居中，在 box 区域内绘制文字"""
    box = cfg["box"]
    bg  = cfg.get("bg") or sample_bg(img, box)

    if debug:
        draw.rectangle(box, outline=(0, 0, 255), width=2)
    else:
        draw.rectangle(box, fill=bg)

    if not text:
        return

    fnt = font(cfg["font"], cfg["size"])
    fg  = cfg["fg"]
    cx  = cfg["center_x"]
    top_y = box[1] + 2  # 从 box 顶部开始（留2px间隔）

    bbox = draw.textbbox((0, 0), text, font=fnt)
    tw = bbox[2] - bbox[0]
    tx = cx - tw // 2
    draw.text((tx, top_y), text, font=fnt, fill=fg)

def paste_image(base_img, new_img_path, box, debug=False):
    """将新图片缩放并粘贴到 box 区域"""
    if not new_img_path or not Path(new_img_path).exists():
        print(f"  [跳过] 图片不存在: {new_img_path}")
        return base_img

    bx, by, bw, bh = box[0], box[1], box[2] - box[0], box[3] - box[1]
    new_img = Image.open(new_img_path).convert("RGB")

    # 等比缩放，短边对齐，居中裁切
    src_w, src_h = new_img.size
    scale = max(bw / src_w, bh / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    new_img = new_img.resize((new_w, new_h), Image.LANCZOS)

    # 居中裁切
    left = (new_w - bw) // 2
    top  = (new_h - bh) // 2
    new_img = new_img.crop((left, top, left + bw, top + bh))

    base_img.paste(new_img, (bx, by))

    if debug:
        d = ImageDraw.Draw(base_img)
        d.rectangle((bx, by, bx+bw, by+bh), outline=(0, 200, 0), width=4)

    return base_img


# ─── 各屏生成函数 ───────────────────────────────────────────────────────

def generate_screen01(cfg, debug=False):
    c = COORD["sw01"]
    img = Image.open(TPLS["sw01"]).convert("RGB")
    draw = ImageDraw.Draw(img)

    # 型号
    cover_and_text(img, draw, c["model"], cfg.get("model", ""), debug)

    # 标语
    cover_and_text(img, draw, c["slogan1"],   cfg.get("slogan_line1", ""), debug)
    cover_and_text(img, draw, c["slogan2"],   cfg.get("slogan_line2", ""), debug)
    cover_and_text(img, draw, c["sub_slogan"],cfg.get("sub_slogan", ""),   debug)

    # 产品主图（优先用语义键，降级用直接路径）
    img = paste_image(img, resolve_image(cfg, "product_image_key") or cfg.get("product_image"),
                      c["product_img"]["box"], debug)

    # 4个核心参数
    params = cfg.get("core_params", [])
    for i, p_cfg in enumerate(c["param_values"]):
        val = params[i]["value"] if i < len(params) else ""
        cover_centered(img, draw, p_cfg, val, debug)
    for i, p_cfg in enumerate(c["param_labels"]):
        lbl = params[i]["label"] if i < len(params) else ""
        cover_centered(img, draw, p_cfg, lbl, debug)

    out = OUTPUT_DIR / "gen_screen01.jpg"
    img.save(str(out), quality=95)
    print(f"  [完成] 第1屏 -> {out.name}")
    return img


def generate_screen03(cfg, debug=False):
    c = COORD["sw03"]
    img = Image.open(TPLS["sw03"]).convert("RGB")
    draw = ImageDraw.Draw(img)

    # 大标题数字
    cover_and_text(img, draw, c["people_count"], cfg.get("people_count", ""), debug)
    cover_and_text(img, draw, c["efficiency"],   cfg.get("efficiency_value", ""), debug)

    # 实景图
    img = paste_image(img, resolve_image(cfg, "scene_image_key") or cfg.get("scene_image"),
                      c["scene_img"]["box"], debug)

    # VS 对比框内容
    cover_and_text(img, draw, c["vs_stat1"],
                   cfg.get("efficiency_claim", ""), debug)
    cover_and_text(img, draw, c["vs_stat2"],
                   f"一年劲省{cfg.get('savings_claim', '')}", debug)

    out = OUTPUT_DIR / "gen_screen03.jpg"
    img.save(str(out), quality=95)
    print(f"  [完成] 第3屏 -> {out.name}")
    return img


def generate_screen07(cfg, debug=False):
    c   = COORD["sw07"]
    tc  = c["table_rows"]
    img = Image.open(TPLS["sw07"]).convert("RGB")
    draw = ImageDraw.Draw(img)

    # 尺寸图：仅当配置了 dim_image_key 时才替换（否则保留模板原图）
    dim_img_path = resolve_image(cfg, "dim_image_key") or cfg.get("dim_image")
    if dim_img_path:
        img = paste_image(img, dim_img_path, c["dim_img"]["box"], debug)
    else:
        print("  [跳过] 未配置 dim_image_key，保留模板原图")

    # 尺寸标注（先采样再覆盖）
    dims = cfg.get("dimensions", {})
    cover_and_text(img, draw, c["dim_width"],  dims.get("width", ""),  debug)
    cover_and_text(img, draw, c["dim_length"], dims.get("length", ""), debug)
    cover_and_text(img, draw, c["dim_height"], dims.get("height", ""), debug)

    # 参数表格
    rows = cfg.get("detail_params", [])
    fnt1 = font(tc["col1_val"]["font"], tc["col1_val"]["size"])
    fnt2 = font(tc["col2_val"]["font"], tc["col2_val"]["size"])
    fg1  = tc["col1_val"]["fg"]
    fg2  = tc["col2_val"]["fg"]
    x1   = tc["col1_val"]["x"]
    x2   = tc["col2_val"]["x"]
    w1   = tc["col1_val"]["w"]
    w2   = tc["col2_val"]["w"]

    # 读取原始模板，用于采样每行真实背景色
    orig_img = Image.open(TPLS["sw07"]).convert("RGB")

    for i, row in enumerate(rows):
        y_top = tc["start_y"] + i * tc["row_height"]
        y_bot = y_top + tc["row_height"]
        # 从原图采样该行中央位置背景色（避开文字，取行右侧空白区）
        sample_y = min(y_top + tc["row_height"] // 2, orig_img.height - 1)
        sample_x = min(x1 + w1 - 10, orig_img.width - 1)
        bg = orig_img.getpixel((sample_x, sample_y))[:3]

        # 覆盖值1列（col 1 value）
        v1_box = (x1, y_top + 4, x1 + w1, y_bot - 4)
        if debug:
            draw.rectangle(v1_box, outline=(255, 128, 0), width=2)
        else:
            draw.rectangle(v1_box, fill=bg)

        # 覆盖值2列（col 2 value），跨列单元格（如产品尺寸）放整行
        if len(row) >= 4 and row[2] == "":
            # 全行值（如"产品尺寸 2210×1900×1980mm"）
            v_full_box = (x1, y_top + 4, x2 + w2, y_bot - 4)
            if not debug:
                draw.rectangle(v_full_box, fill=bg)
            draw.text((x1, y_top + 16), row[1], font=fnt1, fill=fg1)
            continue
        else:
            v2_box = (x2, y_top + 4, x2 + w2, y_bot - 4)
            if debug:
                draw.rectangle(v2_box, outline=(255, 128, 0), width=2)
            else:
                draw.rectangle(v2_box, fill=bg)

        # 写新值
        if len(row) > 1 and row[1]:
            draw.text((x1, y_top + 16), row[1], font=fnt1, fill=fg1)
        if len(row) > 3 and row[3]:
            draw.text((x2, y_top + 16), row[3], font=fnt2, fill=fg2)

    out = OUTPUT_DIR / "gen_screen07.jpg"
    img.save(str(out), quality=95)
    print(f"  [完成] 第7屏 -> {out.name}")
    return img


def copy_fixed_screens():
    """固定屏直接复制原图"""
    import shutil
    for key, label in [("sw02", "gen_screen02"), ("sw04", "gen_screen04"), ("sw_icons", "gen_screen_icons")]:
        src = TPLS[key]
        dst = OUTPUT_DIR / f"{label}.jpg"
        shutil.copy2(src, dst)
        print(f"  [复制] 固定屏 -> {dst.name}")


def merge_all():
    """把所有屏垂直拼接成一张长图"""
    order = [
        OUTPUT_DIR / "gen_screen01.jpg",
        OUTPUT_DIR / "gen_screen_icons.jpg",
        OUTPUT_DIR / "gen_screen02.jpg",
        OUTPUT_DIR / "gen_screen03.jpg",
        OUTPUT_DIR / "gen_screen04.jpg",
        OUTPUT_DIR / "gen_screen07.jpg",
    ]
    imgs = [Image.open(p) for p in order if p.exists()]
    total_h = sum(i.height for i in imgs)
    W = imgs[0].width
    result = Image.new("RGB", (W, total_h), (255, 255, 255))
    y = 0
    for im in imgs:
        result.paste(im, (0, y))
        y += im.height
    out = OUTPUT_DIR / "merged_detail_page.jpg"
    result.save(str(out), quality=92)
    print(f"\n  [合并] 完整长图 -> {out.name}  ({W}x{total_h}px)")
    return str(out)


# ─── 主入口 ─────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    debug = "--debug" in args
    args  = [a for a in args if not a.startswith("--")]

    cfg_path = Path(args[0]) if args else BASE_DIR / "product_config.json"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)

    print("=" * 52)
    print(f"  产品详情页覆盖生成  {'[调试模式]' if debug else ''}")
    print(f"  配置: {cfg_path.name}")
    print("=" * 52)

    generate_screen01(cfg, debug)
    generate_screen03(cfg, debug)
    generate_screen07(cfg, debug)
    copy_fixed_screens()
    out = merge_all()

    print("\n  生成完成！")
    os.startfile(out)


if __name__ == "__main__":
    main()
