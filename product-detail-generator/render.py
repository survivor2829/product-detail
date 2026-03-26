"""
产品详情页自动生成工具
用法: python render.py [config.json] [--scale 1|2]
"""
import json
import sys
import os
from pathlib import Path
from jinja2 import Template
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def normalize_config(cfg: dict) -> dict:
    """
    将新格式 config 标准化为 template.html 所需格式。
    支持新旧两种格式并存，缺失字段给默认值。
    """
    # ── slogan：单字符串 → slogan_line1 + slogan_line2 ──────────
    if "slogan_line1" not in cfg:
        slogan = cfg.get("slogan", "")
        # 按标点切割（逗号或句号），最多拆成两行
        import re
        parts = re.split(r'[，,。]', slogan, maxsplit=1)
        cfg["slogan_line1"] = (parts[0] + "，").strip() if len(parts) > 1 else slogan
        cfg["slogan_line2"] = parts[1].strip() if len(parts) > 1 else ""

    # ── core_params：dict → list of {label, value} ──────────────
    if isinstance(cfg.get("core_params"), dict):
        cfg["core_params"] = [
            {"label": k, "value": v}
            for k, v in list(cfg["core_params"].items())[:4]
        ]

    # ── detail_params：dict → list of [名1,值1,名2,值2] ─────────
    if isinstance(cfg.get("detail_params"), dict):
        items = list(cfg["detail_params"].items())
        rows = []
        for i in range(0, len(items), 2):
            k1, v1 = items[i]
            if i + 1 < len(items):
                k2, v2 = items[i + 1]
            else:
                k2, v2 = "", ""
            rows.append([k1, v1, k2, v2])
        cfg["detail_params"] = rows

    # ── 缺失字段给默认值 ─────────────────────────────────────────
    model = cfg.get("model", "")
    cfg.setdefault("machine_name", cfg.get("product_name", "扫地车"))
    cfg.setdefault("machine_pros", ["省时省钱省心"])
    cfg.setdefault("human_cons",   ["人工效率低", "成本高"])
    cfg.setdefault("params_subtitle", f"{model}全新升级")
    cfg.setdefault("machine_stats", [
        cfg.get("efficiency_claim", ""),
        f"一年劲省{cfg.get('savings_claim', '')}",
    ])

    return cfg


def find_nobg(path_str: str) -> str:
    """
    检查同目录下是否有对应的 _nobg.png（透明底抠图版本）。
    如果存在，优先返回抠图版本路径；否则返回原路径。
    """
    if not path_str:
        return path_str
    p = Path(path_str)
    nobg = p.parent / f"{p.stem}_nobg.png"
    if nobg.exists():
        print(f"[抠图] 使用透明底图片: {nobg.name}")
        return str(nobg)
    return path_str


def path_to_url(path_str: str) -> str:
    """将 Windows 文件路径转换为 file:// URL（处理中文路径）"""
    if not path_str:
        return ""
    p = Path(path_str)
    if not p.exists():
        print(f"[警告] 图片文件不存在: {path_str}")
    return p.as_uri()


def render_page(config_path: str = None, scale: int = 2) -> str:
    """
    读取 JSON 配置，渲染 HTML 模板，截图输出 PNG。

    Args:
        config_path: JSON 配置文件路径（默认使用同目录的 product_config.json）
        scale: 像素密度（1=750px宽, 2=1500px宽高清）

    Returns:
        输出 PNG 文件路径
    """
    # ── 1. 加载配置 ──────────────────────────────────────────────
    config_path = Path(config_path) if config_path else BASE_DIR / "product_config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # ── 2. 标准化配置（兼容新旧格式）───────────────────────────────
    config = normalize_config(config)

    # ── 3. 图片路径 → file:// URL（优先使用透明底抠图版本）────────
    product_img = find_nobg(config.get("product_image", ""))
    config["product_image_url"] = path_to_url(product_img)
    # scene_image 未指定时，降级使用 product_image
    scene_raw = config.get("scene_image") or config.get("product_image", "")
    config["scene_image_url"]   = path_to_url(find_nobg(scene_raw))
    # 第2屏、第4屏固定插图（可选，不填则跳过该屏）
    config["screen2_image_url"] = path_to_url(config.get("screen2_image", ""))
    config["screen4_image_url"] = path_to_url(config.get("screen4_image", ""))

    # ── 4. 渲染 Jinja2 模板 ──────────────────────────────────────
    template_file = BASE_DIR / "template.html"
    with open(template_file, "r", encoding="utf-8") as f:
        tpl = Template(f.read())

    html = tpl.render(**config)

    # 写临时 HTML 文件（放在 output 目录，方便本地浏览器预览）
    temp_html = OUTPUT_DIR / "_temp_preview.html"
    with open(temp_html, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[OK] HTML 已生成: {temp_html}")

    # ── 5. Playwright 截图 ───────────────────────────────────────
    model_slug = config.get("model", "product").replace(" ", "_").replace("/", "-")
    out_png = OUTPUT_DIR / f"{model_slug}_detail.png"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            args=["--disable-web-security", "--allow-file-access-from-files"]
        )
        ctx = browser.new_context(
            viewport={"width": 750, "height": 900},
            device_scale_factor=scale,
        )
        page = ctx.new_page()

        # 加载本地 HTML（file:// 协议支持本地图片）
        page.goto(temp_html.as_uri(), wait_until="networkidle", timeout=30000)

        # 等图片渲染完成
        page.wait_for_timeout(800)

        # 全页截图
        page.screenshot(path=str(out_png), full_page=True)
        browser.close()

    print(f"[完成] 图片已生成: {out_png}")
    print(f"       宽度: {750 * scale}px (高清{scale}x)")
    return str(out_png)


def open_result(path: str):
    """在系统默认程序中打开输出文件（Windows）"""
    os.startfile(path)


if __name__ == "__main__":
    # 解析命令行参数
    cfg = None
    scale = 2

    args = sys.argv[1:]
    skip_next = False
    for i, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg == "--scale" and i + 1 < len(args):
            scale = int(args[i + 1])
            skip_next = True
        elif not arg.startswith("--"):
            cfg = arg

    print("=" * 50)
    print("  产品详情页生成工具 v1.0")
    print("=" * 50)

    out = render_page(cfg, scale=scale)

    # 自动打开预览
    print(f"\n正在打开预览图...")
    open_result(out)
