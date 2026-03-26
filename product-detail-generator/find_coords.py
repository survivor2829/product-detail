"""
坐标定位工具 - 在模板图上叠加坐标网格
"""
import json
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

FONT_PATH = "C:/Windows/Fonts/msyh.ttc"
OUT_DIR = Path("C:/Users/28293/clean-industry-ai-assistant/product-detail-generator/output")

with open(OUT_DIR.parent / "file_paths.json", encoding="utf-8") as f:
    PATHS = json.load(f)

def get_path(keyword):
    for k, v in PATHS.items():
        if keyword in k:
            return v
    raise KeyError(keyword)

def make_grid(img_path, out_name, step=100):
    img = Image.open(img_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = img.size

    try:
        fnt = ImageFont.truetype(FONT_PATH, 18)
    except Exception:
        fnt = ImageFont.load_default()

    # 每50px浅线
    for x in range(0, w, 50):
        draw.line([(x, 0), (x, h)], fill=(255, 50, 50, 50), width=1)
    for y in range(0, h, 50):
        draw.line([(0, y), (w, y)], fill=(255, 50, 50, 50), width=1)

    # 每100px粗线+坐标标注
    for x in range(0, w, step):
        draw.line([(x, 0), (x, h)], fill=(255, 50, 50, 160), width=2)
    for y in range(0, h, step):
        draw.line([(0, y), (w, y)], fill=(255, 50, 50, 160), width=2)
        for x in range(0, w, step):
            label = f"{x},{y}"
            bbox = draw.textbbox((0, 0), label, font=fnt)
            tw = bbox[2] - bbox[0]
            draw.rectangle([x+1, y+1, x+tw+4, y+20], fill=(0, 0, 0, 200))
            draw.text((x+2, y+1), label, font=fnt, fill=(255, 255, 0, 255))

    result = Image.alpha_composite(img, overlay).convert("RGB")
    out_path = OUT_DIR / f"grid_{out_name}.jpg"
    result.save(out_path, quality=92)
    print(f"  {out_name}: {w}x{h} -> {out_path.name}")

if __name__ == "__main__":
    print("生成坐标网格图...")
    make_grid(get_path("260312_01"), "sw01")
    make_grid(get_path("260312_03"), "sw03")
    make_grid(get_path("260312_07"), "sw07")
    print("完成")
