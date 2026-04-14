"""
AI 合成管线 · 阶段二 CLI:7 屏编排 + 长图拼接(调用 ai_compose_pipeline)

本脚本只负责:
  1) 构造 DZ50X 驾驶式洗地机的 7 屏 ctx(测试/演示用)
  2) 调用 `ai_compose_pipeline.compose_detail_page()`
  3) 打印渲染 + 拼接统计

真正的渲染/拼接逻辑在 `ai_compose_pipeline.py` — 同一模块被 Flask 端点
`/api/generate-ai-detail-html` 复用,保证 CLI 和 HTTP 链路产出完全一致。

运行:
  python build_long_image.py

输出:
  output/ai_compose_test/{hero,advantages,...}.png — 各屏独立输出(覆盖)
  output/ai_compose_test/long.png                 — 无损长图(档案)
  output/ai_compose_test/long.jpg                 — 交付级 JPEG(q=90)
"""
from pathlib import Path

from ai_compose_pipeline import DEFAULT_ORDER, compose_detail_page


# ── 路径常量 ─────────────────────────────────────────
BASE = Path(__file__).parent
OUT_DIR = BASE / "output" / "ai_compose_test"

SEGMENTS_DIR = BASE / "output" / "prompt_test_v2" / "segments"
PRODUCT_PATH = BASE / "output" / "dz10_product_nobg.png"
SCENE_BANK   = BASE / "static" / "scene_bank"

# ── 屏顺序(未来前端拖拽输出此列表) ───────────────
SCREEN_ORDER = DEFAULT_ORDER  # hero → advantages → specs → vs → scene → brand → cta

# ── 通用主题(所有屏共用) ───────────────────────────
THEME = {
    "theme_primary":      "#E8231A",
    "theme_primary_dark": "#B51A13",
    "theme_accent":       "#FFD166",
}


# ── 素材兜底辅助 ────────────────────────────────────
def opt_bg(name: str) -> str | None:
    """AI 生成的分段背景,存在返回 URI,否则 None — 让模板走无背景兜底"""
    p = SEGMENTS_DIR / f"{name}.png"
    return p.as_uri() if p.exists() else None


def opt_uri(p: Path) -> str | None:
    return p.as_uri() if p.exists() else None


# ── 各屏 ctx 构造器(DZ50X 驾驶式洗地机的测试数据) ──
def ctx_hero():
    return {
        **THEME,
        "bg_url":        opt_bg("hero"),
        "product_url":   opt_uri(PRODUCT_PATH),
        "main_title":    "DZ50X",
        "subtitle":      "驾驶式洗地机 · 商用清洁智能驾驶",
        "taglines":      ["一台顶八人", "效率 3600㎡/h"],
        "kpi_list": [
            {"value": "3600㎡/h", "label": "清扫效率"},
            {"value": "850mm",    "label": "清扫宽度"},
            {"value": "4小时",    "label": "续航时间"},
            {"value": "≤68dB",    "label": "运行噪音"},
        ],
    }


def ctx_advantages():
    return {
        **THEME,
        "bg_url":        opt_bg("advantages"),
        "section_label": "CORE ADVANTAGES",
        "title_prefix":  "六大",
        "title_main":    "核心优势",
        "subtitle":      "DZ50X · 为效率而生",
        "advantages": [
            {"icon": "⚡",  "title": "高效清扫",      "stat_num": "3600", "stat_unit": "㎡/h",   "desc_main": "相当于 8 名保洁同时作业",           "desc_sub": "商用大场景一次清洁到位"},
            {"icon": "💧",  "title": "大水箱长续航", "stat_num": "90L",  "stat_unit": "/ 100L", "desc_main": "清水 + 污水双箱设计",                "desc_sub": "连续作业不必频繁加水"},
            {"icon": "🔋",  "title": "锂电续航",     "stat_num": "4",    "stat_unit": "小时",   "desc_main": "一次充电覆盖全天班次",              "desc_sub": "2 小时快充即可满电复工"},
            {"icon": "🔇",  "title": "静音运行",     "stat_num": "≤68",  "stat_unit": "dB",     "desc_main": "商场酒店办公楼全时段可用",         "desc_sub": "夜间作业不扰客不投诉"},
            {"icon": "📐",  "title": "精准转弯",     "stat_num": "1.2",  "stat_unit": "m",      "desc_main": "行业领先的最小转弯半径",            "desc_sub": "狭窄货架通道轻松穿行"},
            {"icon": "🛡️", "title": "安全防护",     "stat_num": "5",    "stat_unit": "重",     "desc_main": "激光 + 红外 + 碰撞 + 边界 + 急停", "desc_sub": "全方位主动避障与防护"},
        ],
    }


def ctx_specs():
    return {
        **THEME,
        "bg_url":        opt_bg("specs"),
        "product_url":   opt_uri(PRODUCT_PATH),
        "section_label": "TECHNICAL SPECS",
        "title_main":    "专业参数",
        "subtitle":      "DZ50X · 驾驶式洗地机",
        "product_badge": "MODEL DZ50X",
        "specs": [
            {"label": "清扫效率", "value": "3600",     "unit": "㎡/h"},
            {"label": "清扫宽度", "value": "850",      "unit": "mm"},
            {"label": "水箱容量", "value": "90L/100L", "unit": ""},
            {"label": "整机重量", "value": "380",      "unit": "kg"},
            {"label": "续航时间", "value": "4",        "unit": "小时"},
            {"label": "最小转弯", "value": "1.2",      "unit": "m"},
            {"label": "运行噪音", "value": "≤68",      "unit": "dB"},
            {"label": "充电时间", "value": "2",        "unit": "小时"},
        ],
    }


def ctx_vs():
    return {
        **THEME,
        "bg_url":         opt_bg("vs"),
        "section_label":  "EFFICIENCY COMPARISON",
        "title_prefix":   "1 台顶 ",
        "title_main":     "8 人",
        "subtitle":       "DZ50X · 以一当八的效率革命",
        "left_label":     "传统人工保洁",
        "left_sublabel":  "Traditional Cleaning",
        "left_icon":      "👷",
        "right_label":    "DZ50X 驾驶式",
        "right_sublabel": "Smart Equipment",
        "right_icon":     "🤖",
        "compare_items": [
            {"label": "人力投入", "left_value": "8 人",      "left_desc": "多人协同作业",   "right_value": "1 人",       "right_desc": "驾驶即可完成"},
            {"label": "清扫效率", "left_value": "300 ㎡/h",  "left_desc": "人工拖地速度",   "right_value": "3600 ㎡/h",  "right_desc": "12 倍提效"},
            {"label": "作业时间", "left_value": "8 小时/天", "left_desc": "白天为主",       "right_value": "24 小时",    "right_desc": "全时段可用"},
            {"label": "月度成本", "left_value": "¥ 8000+",   "left_desc": "单人月薪起",     "right_value": "¥ 0",        "right_desc": "设备摊销后"},
            {"label": "清洁标准", "left_value": "参差不齐",  "left_desc": "依赖人员状态",   "right_value": "恒定一致",   "right_desc": "每次完全一致"},
        ],
        "summary_points": [
            {"num": "¥ 96,000+", "label": "年人力成本节省"},
            {"num": "≤ 3 个月",  "label": "设备投资回收"},
        ],
    }


def ctx_scene():
    scene_raw = [
        ("商场.jpg",     "商场超市",   "千级㎡大卖场地面清洁", "HOT"),
        ("机场.jpg",     "机场航站楼", "夜间深度清洁 0 扰客",  "HOT"),
        ("仓库.jpg",     "物流仓储",   "大面积地面油污清除",   None),
        ("地下车库.jpg", "地下车库",   "油污尘垢一次去除",     None),
        ("工厂车间.jpg", "工厂车间",   "生产线间快速穿行",     None),
        ("酒店大堂.jpg", "酒店大堂",   "≤68dB 静音不扰客",     None),
    ]
    items = []
    for fname, name, desc, tag in scene_raw:
        p = SCENE_BANK / fname
        if not p.exists():
            print(f"  [WARN] 场景图缺失,跳过: {p}")
            continue
        it = {"name": name, "image_url": p.as_uri(), "desc": desc}
        if tag:
            it["tag"] = tag
        items.append(it)
    return {
        **THEME,
        "section_label": "APPLICATION SCENARIOS",
        "title_main":    "多场景适用",
        "subtitle":      "DZ50X · 大空间商用硬地全覆盖",
        "grid_columns":  "1fr 1fr",
        "scene_items":   items,
    }


def ctx_brand():
    return {
        **THEME,
        "bg_url":         opt_bg("brand"),
        "section_label":  "ABOUT US",
        "brand_name":     "CLEAN INDUSTRY",
        "brand_name_sub": "清洁工业 · 智能清洁解决方案",
        "brand_story": (
            "深耕商用清洁领域 15 年,服务全球 3000+ 商业客户。"
            "专注为大空间场景提供高效、静音、耐用的智能清洁解决方案,"
            "让每一次清洁都更省力、更专业、更值得信赖。"
        ),
        "credentials": [
            {"icon": "🏆", "main": "15+",    "label": "深耕年限"},
            {"icon": "🌍", "main": "3000+",  "label": "商用客户"},
            {"icon": "🔬", "main": "12 项",  "label": "发明专利"},
            {"icon": "📜", "main": "ISO",    "label": "质量认证"},
        ],
        "credentials_cols": 4,
    }


def ctx_cta():
    return {
        **THEME,
        "section_label":  "CONTACT US",
        "cta_main":       "立即开启智能清洁新时代",
        "cta_sub":        "获取 DZ50X 专属清洁方案",
        "contacts": [
            {"icon": "📞", "value": "400-888-6666"},
            {"icon": "✉️", "value": "biz@cleanindustry.cn"},
        ],
    }


CTX_BUILDERS = {
    "hero":       ctx_hero,
    "advantages": ctx_advantages,
    "specs":      ctx_specs,
    "vs":         ctx_vs,
    "scene":      ctx_scene,
    "brand":      ctx_brand,
    "cta":        ctx_cta,
}


# ── 主流程 ───────────────────────────────────────────
def main():
    print(f"[order] 本次拼接顺序: {' → '.join(SCREEN_ORDER)}\n")

    ctxs = {k: builder() for k, builder in CTX_BUILDERS.items()}

    result = compose_detail_page(
        ctxs=ctxs,
        order=SCREEN_ORDER,
        out_dir=OUT_DIR,
        out_jpg_name="long.jpg",
        out_png_name="long.png",  # CLI 同时输出档案 PNG(Flask 端点会跳过)
        jpg_quality=90,
        verbose=True,
    )

    # ── 打印统计 ────────────────────────────────
    segs = result["segments"]
    logical_w = max(s["w"] for s in segs)
    logical_h = sum(s["h"] for s in segs)
    png_mb = result.get("png_bytes", 0) / (1024 * 1024)
    jpg_mb = result["jpg_bytes"] / (1024 * 1024)

    print(f"\n[render] {len(segs)} 屏共耗时 {result['render_elapsed']:.2f}s "
          f"(平均 {result['render_elapsed'] / len(segs):.2f}s/屏)")
    print("\n" + "=" * 72)
    print(f"✅ 长图拼接完成  "
          f"(拼接 {result['stitch_elapsed']:.2f}s · 总 {result['total_elapsed']:.2f}s)")
    print(f"   逻辑尺寸: {logical_w} × {logical_h}  (CSS 像素)")
    print(f"   物理尺寸: {result['width']} × {result['height']}  (2x retina)")
    if "png" in result:
        print(f"   PNG 档案: {Path(result['png']).name}  {png_mb:.2f} MB")
    print(f"   JPEG 交付: {Path(result['jpg']).name}  {jpg_mb:.2f} MB  "
          f"{'✅ < 5 MB' if jpg_mb < 5 else '⚠️ > 5 MB,需降 quality'}")


if __name__ == "__main__":
    main()
