"""
图片合成器 v2 — 高质量电商详情图合成
AI背景 + 抠图产品 + 中文文字 → 专业详情图PNG
设计风格：深色科技感 + 渐变色彩 + 精致排版
"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pathlib import Path
import math

# ── 字体 ──────────────────────────────────────────────────────────────
FONT_DIR = "C:/Windows/Fonts"
FONT_REGULAR = f"{FONT_DIR}/msyh.ttc"
FONT_BOLD = f"{FONT_DIR}/msyhbd.ttc"
FONT_EMOJI = f"{FONT_DIR}/seguiemj.ttf"  # Segoe UI Emoji (Windows 10+)

# ── 画布尺寸 ──────────────────────────────────────────────────────────
W = 750

# ── 配色 ──────────────────────────────────────────────────────────────
PRIMARY = (232, 35, 26)
ACCENT = (255, 80, 60)
DARK_BG = (10, 12, 24)
DARK_BG2 = (18, 22, 40)
WHITE = (255, 255, 255)
LIGHT_GRAY = (245, 245, 250)
TEXT_DARK = (17, 17, 17)
TEXT_GRAY = (120, 130, 145)
GOLD = (255, 200, 80)
BLUE_ACCENT = (60, 140, 255)


def _font(size, bold=False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size)


def _emoji_font(size):
    """Emoji字体（Segoe UI Emoji），fallback到雅黑"""
    try:
        return ImageFont.truetype(FONT_EMOJI, size)
    except (IOError, OSError):
        return _font(size)


# ── 绘图工具 ──────────────────────────────────────────────────────────

def _vgradient(w, h, top_rgb, bot_rgb):
    """生成垂直渐变图像"""
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(top_rgb[0] + (bot_rgb[0] - top_rgb[0]) * t)
        g = int(top_rgb[1] + (bot_rgb[1] - top_rgb[1]) * t)
        b = int(top_rgb[2] + (bot_rgb[2] - top_rgb[2]) * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    return img.convert("RGBA")


def _dark_gradient_bg(w, h):
    """深色科技渐变背景"""
    return _vgradient(w, h, (8, 10, 28), (20, 26, 52))


def _light_gradient_bg(w, h):
    """浅色高级灰渐变背景"""
    return _vgradient(w, h, (240, 242, 248), (220, 225, 235))


def _draw_glow_line(draw, y, w, color=PRIMARY, alpha=60):
    """绘制发光装饰线"""
    for dy in range(-3, 4):
        a = max(0, alpha - abs(dy) * 18)
        draw.line([(40, y + dy), (w - 40, y + dy)], fill=(*color, a))


def _draw_accent_dot(draw, x, y, r=4, color=PRIMARY):
    """绘制装饰小圆点"""
    draw.ellipse([(x - r, y - r), (x + r, y + r)], fill=color)


def _draw_text_centered(draw, y, text, font, fill=WHITE, w=None):
    """居中绘制文字，返回底部y"""
    if not text:
        return y
    w = w or W
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((w - tw) // 2, y), text, font=font, fill=fill)
    return y + th


def _draw_text_left(draw, x, y, text, font, fill=WHITE):
    if not text:
        return y
    draw.text((x, y), text, font=font, fill=fill)
    bbox = draw.textbbox((0, 0), text, font=font)
    return y + bbox[3] - bbox[1]


def _draw_tag(draw, x, y, text, font, bg_color=PRIMARY, text_color=WHITE, padding=(12, 6)):
    """绘制标签胶囊"""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    px, py = padding
    draw.rounded_rectangle(
        [(x, y), (x + tw + px * 2, y + th + py * 2)],
        radius=th // 2 + py, fill=bg_color
    )
    draw.text((x + px, y + py), text, font=font, fill=text_color)
    return y + th + py * 2


def _load_bg(bg_path, target_w, target_h):
    """加载背景图并裁切到目标尺寸"""
    if bg_path and Path(bg_path).exists():
        bg = Image.open(bg_path).convert("RGB")
        ratio = max(target_w / bg.width, target_h / bg.height)
        bg = bg.resize((int(bg.width * ratio), int(bg.height * ratio)), Image.LANCZOS)
        left = (bg.width - target_w) // 2
        top = (bg.height - target_h) // 2
        bg = bg.crop((left, top, left + target_w, top + target_h))
        return bg.convert("RGBA")
    return None


def _paste_product(canvas, product_path, max_w, max_h, cx, cy):
    """粘贴产品图到画布（居中），返回是否成功"""
    if not product_path or not Path(product_path).exists():
        return False
    prod = Image.open(product_path).convert("RGBA")
    ratio = min(max_w / prod.width, max_h / prod.height)
    new_w, new_h = int(prod.width * ratio), int(prod.height * ratio)
    prod = prod.resize((new_w, new_h), Image.LANCZOS)
    canvas.paste(prod, (cx - new_w // 2, cy - new_h // 2), prod)
    return True


def _add_shadow(canvas, product_path, max_w, max_h, cx, cy):
    """产品图底部椭圆阴影"""
    if not product_path or not Path(product_path).exists():
        return
    prod = Image.open(product_path).convert("RGBA")
    ratio = min(max_w / prod.width, max_h / prod.height)
    new_w, new_h = int(prod.width * ratio), int(prod.height * ratio)
    shadow = Image.new("RGBA", (new_w, int(new_h * 0.12)), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.ellipse([new_w * 0.1, 0, new_w * 0.9, shadow.height], fill=(0, 0, 0, 50))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    canvas.paste(shadow, (cx - new_w // 2, cy + new_h // 2 - 10), shadow)


def _add_glow_circle(canvas, cx, cy, radius=200, color=(232, 35, 26), alpha=25):
    """添加发光圆形装饰"""
    glow = Image.new("RGBA", (radius * 2, radius * 2), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([(0, 0), (radius * 2, radius * 2)], fill=(*color, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(radius // 2))
    canvas.paste(glow, (cx - radius, cy - radius), glow)


def _bottom_gradient(canvas, h, grad_h=300, max_alpha=200):
    """底部加暗渐变"""
    gradient = Image.new("RGBA", (W, grad_h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gradient)
    for y in range(grad_h):
        a = int(max_alpha * (y / grad_h))
        gd.line([(0, y), (W, y)], fill=(0, 0, 0, a))
    canvas.paste(gradient, (0, h - grad_h), gradient)


# ══════════════════════════════════════════════════════════════════════
#  屏1: 英雄屏 — 品牌+型号+产品图+参数
# ══════════════════════════════════════════════════════════════════════

def compose_hero(product_data: dict, product_image: str,
                 bg_path: str = "", save_path: str = "") -> Image.Image:
    h = 1334
    # 背景
    bg = _load_bg(bg_path, W, h)
    if bg:
        canvas = bg.copy()
        overlay = Image.new("RGBA", (W, h), (0, 0, 0, 70))
        canvas = Image.alpha_composite(canvas, overlay)
    else:
        canvas = _dark_gradient_bg(W, h)
        # 装饰光晕
        _add_glow_circle(canvas, W // 2, h // 3, 350, (30, 60, 140), 30)
        _add_glow_circle(canvas, W // 2 - 100, h // 2, 200, PRIMARY, 15)

    draw = ImageDraw.Draw(canvas)

    # 顶部装饰线
    draw.line([(60, 36), (W - 60, 36)], fill=(*WHITE, 15), width=1)

    y = 50
    brand = product_data.get("brand_text", "") or product_data.get("brand", "")
    if brand:
        # 品牌标签
        bf = _font(16)
        bbox = draw.textbbox((0, 0), brand, font=bf)
        bw = bbox[2] - bbox[0]
        bx = (W - bw - 24) // 2
        draw.rounded_rectangle([(bx, y), (bx + bw + 24, y + 30)], radius=15,
                                fill=(*WHITE, 20), outline=(*WHITE, 40))
        draw.text((bx + 12, y + 5), brand, font=bf, fill=(*WHITE, 200))
        y += 48

    cat = product_data.get("category_line", "")
    if cat:
        y = _draw_text_centered(draw, y, cat, _font(20), fill=(*WHITE, 180)) + 12

    model = product_data.get("model_name", "") or product_data.get("model", "")
    if model:
        y = _draw_text_centered(draw, y, model, _font(52, bold=True), fill=WHITE) + 8

    slogan = product_data.get("tagline_line1", "") or product_data.get("slogan", "")
    if slogan:
        y = _draw_text_centered(draw, y, slogan, _font(26, bold=True), fill=WHITE) + 6
    sub = product_data.get("tagline_line2", "") or product_data.get("sub_slogan", "")
    if sub:
        y = _draw_text_centered(draw, y, sub, _font(18), fill=(*WHITE, 160)) + 20

    # 产品图（大尺寸居中）
    prod_cy = max(y + 260, h // 2 + 40)
    _add_shadow(canvas, product_image, 520, 460, W // 2, prod_cy)
    has_prod = _paste_product(canvas, product_image, 520, 460, W // 2, prod_cy)

    if not has_prod:
        # 无产品图时绘制占位圆环
        draw = ImageDraw.Draw(canvas)
        _add_glow_circle(canvas, W // 2, prod_cy, 160, (60, 100, 200), 20)
        draw = ImageDraw.Draw(canvas)
        draw.ellipse([(W // 2 - 100, prod_cy - 100), (W // 2 + 100, prod_cy + 100)],
                     outline=(*WHITE, 40), width=2)
        _draw_text_centered(draw, prod_cy - 10, "产品图", _font(20), fill=(*WHITE, 60))

    # 底部参数条
    params = []
    for key in ["param_1", "param_2", "param_3", "param_4"]:
        label = product_data.get(f"{key}_label", "")
        value = product_data.get(f"{key}_value", "")
        if label and value:
            params.append((label, value))

    draw = ImageDraw.Draw(canvas)
    if params:
        bar_y = h - 130
        bar = Image.new("RGBA", (W, 110), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bar)
        bd.rounded_rectangle([(20, 0), (W - 20, 110)], radius=16, fill=(0, 0, 0, 140))
        canvas.paste(bar, (0, bar_y), bar)
        draw = ImageDraw.Draw(canvas)

        col_w = (W - 40) // len(params)
        for i, (label, value) in enumerate(params):
            cx = 20 + col_w * i + col_w // 2
            # 分隔竖线
            if i > 0:
                draw.line([(cx - col_w // 2, bar_y + 20), (cx - col_w // 2, bar_y + 90)],
                          fill=(*WHITE, 30), width=1)
            vf = _font(26, bold=True)
            vbox = draw.textbbox((0, 0), value, font=vf)
            vw = vbox[2] - vbox[0]
            draw.text((cx - vw // 2, bar_y + 18), value, font=vf, fill=ACCENT)
            lf = _font(13)
            lbox = draw.textbbox((0, 0), label, font=lf)
            lw = lbox[2] - lbox[0]
            draw.text((cx - lw // 2, bar_y + 60), label, font=lf, fill=(*WHITE, 140))

    # 底部免责
    footer = product_data.get("footer_note", "")
    if footer:
        draw.text((30, h - 26), footer, font=_font(10), fill=(*WHITE, 60))

    if save_path:
        canvas.convert("RGB").save(save_path, quality=95)
    return canvas


# ══════════════════════════════════════════════════════════════════════
#  屏2: 核心卖点屏 — 带产品图的卖点展示
# ══════════════════════════════════════════════════════════════════════

def compose_selling_points(product_data: dict, product_image: str,
                           bg_path: str = "", save_path: str = "") -> Image.Image:
    """核心卖点详情屏：产品图 + 卖点列表"""
    advantages = product_data.get("advantages", [])
    if not advantages:
        return None

    n = len(advantages)
    has_prod = product_image and Path(product_image).exists()
    prod_space = 340 if has_prod else 40
    h = max(800, 160 + prod_space + n * 100 + 60)
    bg = _load_bg(bg_path, W, h)
    canvas = bg.copy() if bg else _dark_gradient_bg(W, h)

    # 装饰
    _add_glow_circle(canvas, 100, 200, 250, (30, 60, 180), 20)
    _add_glow_circle(canvas, W - 80, h - 300, 200, PRIMARY, 12)

    draw = ImageDraw.Draw(canvas)

    # 标题区
    y = 50
    _draw_accent_dot(draw, W // 2 - 100, y + 8, 3, ACCENT)
    _draw_accent_dot(draw, W // 2 + 100, y + 8, 3, ACCENT)
    y = _draw_text_centered(draw, y, "核心优势", _font(14), fill=(*WHITE, 120)) + 6

    title = f"{n}大核心卖点"
    y = _draw_text_centered(draw, y, title, _font(36, bold=True), fill=WHITE) + 8

    model = product_data.get("model_name", "") or product_data.get("model", "")
    if model:
        y = _draw_text_centered(draw, y, model, _font(16), fill=(*WHITE, 100)) + 20

    _draw_glow_line(draw, y, W, ACCENT, 40)
    y += 20

    # 产品图区（仅有产品图时显示）
    has_prod = product_image and Path(product_image).exists()
    if has_prod:
        prod_cy = y + 140
        _add_shadow(canvas, product_image, 340, 280, W // 2, prod_cy)
        _paste_product(canvas, product_image, 340, 280, W // 2, prod_cy)
        y = prod_cy + 160
    else:
        y += 20

    # 卖点列表
    draw = ImageDraw.Draw(canvas)
    margin = 40
    for idx, adv in enumerate(advantages):
        if isinstance(adv, dict):
            emoji = adv.get("emoji", "✅")
            text = adv.get("text", "")
        else:
            emoji, text = "✅", str(adv)
        if not text:
            continue

        ry = y + idx * 100
        # 卡片背景
        card = Image.new("RGBA", (W - margin * 2, 84), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle([(0, 0), (W - margin * 2 - 1, 83)], radius=14,
                              fill=(255, 255, 255, 18), outline=(255, 255, 255, 25))
        canvas.paste(card, (margin, ry), card)
        draw = ImageDraw.Draw(canvas)

        # 序号圆形
        num_x = margin + 38
        num_y = ry + 42
        draw.ellipse([(num_x - 18, num_y - 18), (num_x + 18, num_y + 18)], fill=PRIMARY)
        nf = _font(18, bold=True)
        nt = str(idx + 1)
        nb = draw.textbbox((0, 0), nt, font=nf)
        draw.text((num_x - (nb[2] - nb[0]) // 2, num_y - (nb[3] - nb[1]) // 2 - 1),
                  nt, font=nf, fill=WHITE)

        # emoji + 文字
        draw.text((margin + 70, ry + 16), emoji, font=_emoji_font(26), fill=WHITE,
                  embedded_color=True)
        draw.text((margin + 110, ry + 20), text, font=_font(22, bold=True), fill=WHITE)

        # 底部小装饰
        draw.line([(margin + 70, ry + 58), (margin + 110 + len(text) * 22, ry + 58)],
                  fill=(*ACCENT, 40), width=2)

    if save_path:
        canvas.convert("RGB").save(save_path, quality=95)
    return canvas


# ══════════════════════════════════════════════════════════════════════
#  屏3: 场景应用屏
# ══════════════════════════════════════════════════════════════════════

def compose_scene(product_data: dict, product_image: str,
                  scene_name: str = "", bg_path: str = "",
                  save_path: str = "") -> Image.Image:
    h = 1000
    bg = _load_bg(bg_path, W, h)
    if bg:
        canvas = bg.copy()
        _bottom_gradient(canvas, h, 350, 220)
        # 顶部也加一点暗
        top_grad = Image.new("RGBA", (W, 150), (0, 0, 0, 0))
        td = ImageDraw.Draw(top_grad)
        for y in range(150):
            a = int(100 * (1 - y / 150))
            td.line([(0, y), (W, y)], fill=(0, 0, 0, a))
        canvas.paste(top_grad, (0, 0), top_grad)
    else:
        canvas = _vgradient(W, h, (12, 18, 38), (8, 12, 28))
        _add_glow_circle(canvas, W // 2, h // 2, 300, (20, 50, 120), 25)

    # 顶部标签
    draw = ImageDraw.Draw(canvas)
    scene_text = scene_name if scene_name and scene_name != "default" else "商业场景"
    _draw_tag(draw, 30, 30, f"适用场景 · {scene_text}", _font(14), bg_color=(*PRIMARY, 180))

    # 产品图
    _add_shadow(canvas, product_image, 420, 400, W // 2, h // 2 - 30)
    _paste_product(canvas, product_image, 420, 400, W // 2, h // 2 - 30)

    draw = ImageDraw.Draw(canvas)

    # 底部效率文案
    y = h - 180
    efficiency = ""
    dp = product_data.get("detail_params", {})
    if isinstance(dp, dict):
        for k in ["工作效率", "清洁效率", "清扫效率", "洗地效率", "最大清洁效率"]:
            if k in dp:
                efficiency = dp[k]
                _draw_text_centered(draw, y, efficiency, _font(44, bold=True), fill=WHITE)
                y += 56
                _draw_text_centered(draw, y, k, _font(18), fill=(*WHITE, 160))
                y += 30
                break

    cat = product_data.get("category_line", "")
    if cat and not efficiency:
        _draw_text_centered(draw, y, cat, _font(28, bold=True), fill=WHITE)
        y += 40

    slogan = product_data.get("slogan", "") or product_data.get("tagline_line1", "")
    if slogan:
        _draw_text_centered(draw, y, slogan, _font(16), fill=(*WHITE, 140))

    if save_path:
        canvas.convert("RGB").save(save_path, quality=95)
    return canvas


# ══════════════════════════════════════════════════════════════════════
#  屏4: 参数规格屏
# ══════════════════════════════════════════════════════════════════════

def compose_specs(product_data: dict, product_image: str,
                  bg_path: str = "", save_path: str = "") -> Image.Image:
    specs = product_data.get("specs", [])
    if not specs:
        dp = product_data.get("detail_params", {})
        if isinstance(dp, dict):
            specs = [{"name": k, "value": v} for k, v in dp.items() if k and v]
    if not specs:
        return None

    rows_count = math.ceil(len(specs) / 2)
    table_h = rows_count * 50 + 80
    h = max(1200, 340 + 320 + table_h + 80)

    bg = _load_bg(bg_path, W, h)
    if bg:
        canvas = bg.copy()
        # AI背景上叠加半透明白层，确保文字可读
        white_overlay = Image.new("RGBA", (W, h), (255, 255, 255, 190))
        canvas = Image.alpha_composite(canvas, white_overlay)
    else:
        canvas = _light_gradient_bg(W, h)

    draw = ImageDraw.Draw(canvas)

    # 红色顶部条
    draw.rectangle([(0, 0), (W, 70)], fill=PRIMARY)
    model = product_data.get("model_name", "") or product_data.get("model", "")
    bar_text = f"{model} 产品参数" if model else "产品参数"
    draw.text((30, 18), bar_text, font=_font(28, bold=True), fill=WHITE)
    draw.text((W - 150, 28), "规格一览 ▸", font=_font(14), fill=(*WHITE, 180))

    # 产品图区域（浅色卡片背景）
    card_y = 90
    draw.rounded_rectangle([(20, card_y), (W - 20, card_y + 310)], radius=16,
                           fill=(255, 255, 255, 220))
    _paste_product(canvas, product_image, 360, 260, W // 2, card_y + 160)

    # 尺寸标注
    draw = ImageDraw.Draw(canvas)
    dims = product_data.get("dimensions", {})
    dim_parts = []
    for key, prefix in [("length", "长"), ("width", "宽"), ("height", "高")]:
        val = dims.get(key, "") or product_data.get(f"e_dim_{key}", "")
        if val:
            dim_parts.append(f"{prefix} {val}")
    if dim_parts:
        dim_text = "  ×  ".join(dim_parts)
        _draw_text_centered(draw, card_y + 280, dim_text, _font(16, bold=True), fill=TEXT_DARK)

    # 参数表
    table_y = card_y + 330
    margin = 24

    # 表头
    draw.rounded_rectangle([(margin, table_y), (W - margin, table_y + 52)], radius=12,
                           fill=(255, 255, 255, 240))
    draw.rectangle([(margin, table_y), (margin + 5, table_y + 52)], fill=PRIMARY)
    draw.text((margin + 18, table_y + 12), "产品参数", font=_font(20, bold=True), fill=TEXT_DARK)
    draw.text((margin + 140, table_y + 16), f"共{len(specs)}项", font=_font(13), fill=TEXT_GRAY)

    table_y += 58
    draw.line([(margin, table_y), (W - margin, table_y)], fill=(*PRIMARY, 80), width=2)
    table_y += 4

    # 双列参数行
    half = math.ceil(len(specs) / 2)
    col_w = (W - margin * 2) // 2
    label_w = 105
    row_h = 50

    for i in range(half):
        ry = table_y + i * row_h
        bg_fill = (240, 243, 248, 200) if i % 2 == 0 else (255, 255, 255, 180)
        draw.rectangle([(margin, ry), (W - margin, ry + row_h)], fill=bg_fill)

        spec = specs[i]
        draw.text((margin + 14, ry + 15), spec["name"], font=_font(14), fill=TEXT_GRAY)
        draw.text((margin + label_w, ry + 15), str(spec["value"]),
                  font=_font(14, bold=True), fill=TEXT_DARK)

        cx = margin + col_w
        draw.line([(cx, ry + 10), (cx, ry + row_h - 10)], fill=(0, 0, 0, 25), width=1)

        ri = i + half
        if ri < len(specs):
            sr = specs[ri]
            draw.text((cx + 14, ry + 15), sr["name"], font=_font(14), fill=TEXT_GRAY)
            draw.text((cx + label_w, ry + 15), str(sr["value"]),
                      font=_font(14, bold=True), fill=TEXT_DARK)

    footnote_y = table_y + half * row_h + 12
    draw.text((W - margin - 160, footnote_y), "*参数以实物为准", font=_font(12), fill=TEXT_GRAY)

    if save_path:
        canvas.convert("RGB").save(save_path, quality=95)
    return canvas


# ══════════════════════════════════════════════════════════════════════
#  屏5: VS对比屏 — 机器 vs 人工
# ══════════════════════════════════════════════════════════════════════

def compose_vs(product_data: dict, product_image: str,
               save_path: str = "") -> Image.Image:
    """VS对比屏：机器 vs 人工"""
    vs = product_data.get("vs_comparison", {})
    if not isinstance(vs, dict):
        vs = {}

    left_title = vs.get("left_title", "") or product_data.get("category_line", "")
    if not left_title:
        return None

    has_prod = product_image and Path(product_image).exists()
    card_h = 380 if has_prod else 240
    h = 320 + card_h + 60  # title + cards + bottom
    canvas = _dark_gradient_bg(W, h)
    _add_glow_circle(canvas, W // 4, h // 2, 250, BLUE_ACCENT, 15)
    _add_glow_circle(canvas, W * 3 // 4, h // 2, 250, (180, 40, 40), 12)

    draw = ImageDraw.Draw(canvas)

    # 标题
    y = 50
    count = vs.get("replace_count", "")
    if count:
        _draw_text_centered(draw, y, "1台顶", _font(28, bold=True), fill=(*WHITE, 180))
        y += 40
        _draw_text_centered(draw, y, f"{count}人", _font(56, bold=True), fill=ACCENT)
        y += 70
    else:
        _draw_text_centered(draw, y, "效率对比", _font(36, bold=True), fill=WHITE)
        y += 60

    saving = vs.get("annual_saving", "")
    if saving:
        _draw_text_centered(draw, y, f"年省 {saving} 元", _font(22), fill=GOLD)
        y += 40

    _draw_glow_line(draw, y, W, ACCENT, 50)
    y += 30

    # 左右对比
    mid = W // 2
    left_x, right_x = 40, mid + 20

    # 左侧（机器）— 绿色/蓝色调
    draw.rounded_rectangle([(left_x, y), (mid - 10, y + card_h)], radius=16,
                           fill=(20, 60, 100, 60), outline=(60, 140, 255, 60))
    draw.text((left_x + 20, y + 16), "🤖", font=_emoji_font(28), fill=WHITE,
              embedded_color=True)
    draw.text((left_x + 60, y + 20), left_title, font=_font(20, bold=True), fill=WHITE)

    left_sub = vs.get("left_sub", "")
    if left_sub:
        draw.text((left_x + 20, y + 60), left_sub, font=_font(14), fill=(*BLUE_ACCENT, 200))

    left_bottom = vs.get("left_bottom", "")
    if left_bottom:
        lines = left_bottom.replace("<br>", "\n").split("\n")
        ly = y + 100
        for line in lines:
            draw.text((left_x + 20, ly), line, font=_font(16, bold=True), fill=WHITE)
            ly += 28

    # 产品图放在左侧卡片内（仅有图时）
    if has_prod:
        _paste_product(canvas, product_image, 200, 160,
                       left_x + (mid - 10 - left_x) // 2, y + card_h - 110)

    # 右侧（人工）— 红色/暗调
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle([(right_x, y), (W - 40, y + card_h)], radius=16,
                           fill=(80, 20, 20, 60), outline=(180, 50, 50, 60))
    right_title = vs.get("right_title", "传统人工")
    draw.text((right_x + 20, y + 16), "👷", font=_emoji_font(28), fill=WHITE,
              embedded_color=True)
    draw.text((right_x + 60, y + 20), right_title, font=_font(20, bold=True), fill=(*WHITE, 180))

    right_sub = vs.get("right_sub", "")
    if right_sub:
        draw.text((right_x + 20, y + 60), right_sub, font=_font(14), fill=(*ACCENT, 200))

    right_bottom = vs.get("right_bottom", "")
    if right_bottom:
        lines = right_bottom.replace("<br>", "\n").split("\n")
        ly = y + 100
        for line in lines:
            draw.text((right_x + 20, ly), line, font=_font(16), fill=(*WHITE, 160))
            ly += 28

    # VS标记（精确居中）
    vs_y = y + card_h // 2
    draw.ellipse([(mid - 28, vs_y - 28), (mid + 28, vs_y + 28)], fill=PRIMARY)
    vf = _font(22, bold=True)
    vs_bbox = draw.textbbox((0, 0), "VS", font=vf)
    vs_tw = vs_bbox[2] - vs_bbox[0]
    vs_th = vs_bbox[3] - vs_bbox[1]
    draw.text((mid - vs_tw // 2, vs_y - vs_th // 2), "VS", font=vf, fill=WHITE)

    if save_path:
        canvas.convert("RGB").save(save_path, quality=95)
    return canvas


# ══════════════════════════════════════════════════════════════════════
#  屏6: 品牌CTA屏 — 底部收尾
# ══════════════════════════════════════════════════════════════════════

def compose_brand_cta(product_data: dict, product_image: str,
                      save_path: str = "") -> Image.Image:
    h = 600
    canvas = _vgradient(W, h, (15, 18, 38), (8, 10, 22))
    _add_glow_circle(canvas, W // 2, h // 2, 300, PRIMARY, 15)

    draw = ImageDraw.Draw(canvas)

    y = 80
    brand = product_data.get("brand", "") or product_data.get("brand_text", "")
    if brand:
        y = _draw_text_centered(draw, y, brand, _font(32, bold=True), fill=WHITE) + 16

    model = product_data.get("model_name", "") or product_data.get("model", "")
    if model:
        y = _draw_text_centered(draw, y, model, _font(44, bold=True), fill=WHITE) + 12

    slogan = product_data.get("slogan", "") or product_data.get("tagline_line1", "")
    if slogan:
        y = _draw_text_centered(draw, y, slogan, _font(18), fill=(*WHITE, 160)) + 30

    # CTA按钮
    btn_text = "立即咨询"
    bf = _font(22, bold=True)
    bbox = draw.textbbox((0, 0), btn_text, font=bf)
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    bx = (W - bw - 60) // 2
    by = y + 10
    draw.rounded_rectangle([(bx, by), (bx + bw + 60, by + bh + 24)], radius=(bh + 24) // 2,
                           fill=PRIMARY)
    draw.text((bx + 30, by + 12), btn_text, font=bf, fill=WHITE)

    # 底部免责
    draw.text((30, h - 40), "*产品参数以实物为准，图片仅供参考", font=_font(11), fill=(*WHITE, 60))
    draw.text((30, h - 22), "© " + (brand or "品牌"), font=_font(10), fill=(*WHITE, 40))

    if save_path:
        canvas.convert("RGB").save(save_path, quality=95)
    return canvas


# ══════════════════════════════════════════════════════════════════════
#  屏7: 清洁故事屏 — 核心清洁机构展示
# ══════════════════════════════════════════════════════════════════════

def compose_story(product_data: dict, product_image: str,
                  save_path: str = "") -> Image.Image:
    """清洁故事屏：核心清洁机构+效果数据"""
    story_t1 = product_data.get("story_title_1", "")
    story_t2 = product_data.get("story_title_2", "")
    if not story_t1 and not story_t2:
        return None

    has_prod = product_image and Path(product_image).exists()
    h = 1100 if has_prod else 600
    canvas = _dark_gradient_bg(W, h)
    _add_glow_circle(canvas, W // 2, 300, 300, (20, 50, 140), 20)

    draw = ImageDraw.Draw(canvas)

    # 标题区
    y = 50
    y = _draw_text_centered(draw, y, "清洁实力", _font(14), fill=(*WHITE, 100)) + 10
    if story_t1:
        y = _draw_text_centered(draw, y, story_t1, _font(28, bold=True), fill=WHITE) + 8
    if story_t2:
        y = _draw_text_centered(draw, y, story_t2, _font(22), fill=(*WHITE, 180)) + 20

    _draw_glow_line(draw, y, W, ACCENT, 40)
    y += 30

    # 产品图（仅有图时显示）
    if has_prod:
        prod_cy = y + 220
        _add_shadow(canvas, product_image, 500, 380, W // 2, prod_cy)
        _paste_product(canvas, product_image, 500, 380, W // 2, prod_cy)
        y = prod_cy + 220
    else:
        y += 30

    # 底部数据说明
    draw = ImageDraw.Draw(canvas)
    desc1 = product_data.get("story_desc_1", "")
    desc2 = product_data.get("story_desc_2", "")
    if desc1:
        y = _draw_text_centered(draw, y, desc1, _font(16), fill=(*WHITE, 160)) + 8
    if desc2:
        y = _draw_text_centered(draw, y, desc2, _font(16), fill=(*WHITE, 120)) + 16

    # 底部亮点条
    bot1 = product_data.get("story_bottom_1", "")
    bot2 = product_data.get("story_bottom_2", "")
    if bot1 or bot2:
        bar = Image.new("RGBA", (W - 60, 80), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bar)
        bd.rounded_rectangle([(0, 0), (W - 61, 79)], radius=14, fill=(*PRIMARY, 40),
                              outline=(*PRIMARY, 80))
        canvas.paste(bar, (30, y), bar)
        draw = ImageDraw.Draw(canvas)
        if bot1:
            draw.text((60, y + 14), bot1, font=_font(20, bold=True), fill=ACCENT)
        if bot2:
            draw.text((60, y + 46), bot2, font=_font(14), fill=(*WHITE, 160))

    if save_path:
        canvas.convert("RGB").save(save_path, quality=95)
    return canvas


# ══════════════════════════════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════════════════════════════

def compose_all(product_data: dict, product_image: str,
                backgrounds: dict, save_dir: str | Path) -> list[str]:
    """
    生成完整详情图集（6-8张）
    """
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    results = []
    idx = 1

    def _save(name, img):
        nonlocal idx
        if img is None:
            return
        path = str(save_dir / f"{idx:02d}_{name}.png")
        img.convert("RGB").save(path, quality=95)
        results.append(path)
        print(f"[合成] {idx:02d}_{name} 完成")
        idx += 1

    # 1. 英雄屏（必出）
    _save("hero", compose_hero(
        product_data, product_image, bg_path=backgrounds.get("hero", "")))

    # 2. 卖点屏（有advantages时出）
    _save("selling_points", compose_selling_points(
        product_data, product_image))

    # 3. 清洁故事屏（有story数据时出）
    _save("story", compose_story(product_data, product_image))

    # 4. VS对比屏（有vs_comparison时出）
    _save("vs", compose_vs(product_data, product_image))

    # 5. 场景屏（每个场景背景各出一张）
    scene_bgs = {k: v for k, v in backgrounds.items() if k.startswith("scene_")}
    if scene_bgs:
        for name, bg in scene_bgs.items():
            sn = name.replace("scene_", "")
            _save(f"scene_{sn}", compose_scene(
                product_data, product_image, scene_name=sn, bg_path=bg))
    else:
        # 无AI背景也出一张场景屏
        _save("scene", compose_scene(product_data, product_image, scene_name="商业场景"))

    # 6. 参数屏（有参数时出）
    _save("specs", compose_specs(
        product_data, product_image, bg_path=backgrounds.get("specs", "")))

    # 7. 品牌CTA屏（收尾，必出）
    _save("brand_cta", compose_brand_cta(product_data, product_image))

    print(f"[合成] 全部完成，共 {len(results)} 张图")
    return results
