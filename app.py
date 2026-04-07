"""
物保云产品详情页生成器 - Web 后端（设备类专用）
启动: python app.py
访问: http://localhost:5000
"""
import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import uuid
import json
import re
from pathlib import Path
from flask import Flask, request, jsonify, send_file, send_from_directory, render_template, redirect, url_for
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
TEMPLATES_DIR = BASE_DIR / "templates"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

PRODUCT_TYPE = "设备类"
_EXTRA_BLOCK_KEYS = ["block_g", "block_h", "block_i", "block_j", "block_k",
                     "block_l", "block_m", "block_n", "block_o",
                     "block_p", "block_q", "block_r",
                     "block_s", "block_t", "block_u", "block_v",
                     "block_w", "block_x", "block_y"]

ALLOWED_IMG = {"jpg", "jpeg", "png", "webp"}

# ── DeepSeek API 配置 ─────────────────────────────────────────────────
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "***REMOVED***")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL   = "deepseek-chat"
PROXY = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


@app.after_request
def _no_cache(response):
    """禁止浏览器缓存 HTML/JSON，静态资源允许缓存"""
    ct = response.content_type or ""
    if "text/html" in ct or "application/json" in ct:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# ── rembg 可用性检测 ──
REMBG_SESSION = None
try:
    import rembg as _rembg_check
    from rembg import new_session as _rembg_new_session
    REMBG_AVAILABLE = True
    REMBG_SESSION = _rembg_new_session("isnet-general-use")
    print("[启动] rembg 已安装（isnet-general-use 模型），产品图将自动抠图")
except ImportError:
    REMBG_AVAILABLE = False
    print("[启动] ⚠ rembg 未安装，产品图将保留原背景。运行: pip install rembg onnxruntime")


# ── 工具函数 ─────────────────────────────────────────────────────────

def allowed_img(fn): return "." in fn and fn.rsplit(".", 1)[1].lower() in ALLOWED_IMG


def _to_str(value):
    if value is None:
        return ""
    return str(value).strip()


def _fallback_text(value, default=""):
    s = _to_str(value)
    return s if s else default


def _first_nonempty(*values):
    for value in values:
        s = _to_str(value)
        if s:
            return s
    return ""


# ── 极限词过滤（电商合规）────────────────────────────────────────────

_EXTREME_WORD_MAP = {
    "最强": "超强", "最大": "超大", "最小": "超小", "最好": "优质",
    "最高": "超高", "最低": "超低", "最快": "高速", "最优": "优质",
    "最先进": "先进", "最专业": "专业", "最安全": "安全",
    "最耐用": "耐用", "最便捷": "便捷", "最智能": "智能",
    "最环保": "环保", "最轻": "轻量", "最省": "节能",
    "第一": "领先", "唯一": "专属", "极致": "卓越",
    "顶级": "高级", "顶尖": "优质",
    "行业领先": "行业前列", "业界领先": "行业认可",
    "全球领先": "全球认可", "国内领先": "行业前列",
    "世界领先": "行业前列", "国际领先": "国际认可",
    "无与伦比": "卓越出色",
}


def _strip_extreme_words(text: str) -> str:
    """替换电商违禁极限词，避免平台合规风险"""
    if not isinstance(text, str):
        return text
    for word, repl in _EXTREME_WORD_MAP.items():
        text = text.replace(word, repl)
    return text


def _get_detail_value(detail_params: dict, keys: list) -> str:
    if not isinstance(detail_params, dict):
        return ""
    for key in keys:
        value = _to_str(detail_params.get(key, ""))
        if value:
            return value
    return ""


def _split_slogan(slogan: str) -> tuple:
    text = _to_str(slogan)
    if not text:
        return "", ""
    for sep in ("，", ",", "。", "；", ";", "、"):
        if sep in text:
            parts = [p.strip() for p in text.split(sep) if p.strip()]
            if len(parts) >= 2:
                return parts[0] + (sep if sep in ("，", ",") else ""), parts[1]
    if len(text) <= 12:
        return text, ""
    mid = max(4, len(text) // 2)
    return text[:mid], text[mid:]


def _parse_dimensions_from_text(size_text: str) -> tuple:
    text = _to_str(size_text).lower().replace(" ", "")
    text = text.replace("长", "").replace("宽", "").replace("高", "")
    text = text.replace("l", "").replace("w", "").replace("h", "")
    if not text:
        return "", "", ""
    m = re.search(
        r"(\d+(?:\.\d+)?(?:mm|cm|m)?)\s*[x×*]\s*(\d+(?:\.\d+)?(?:mm|cm|m)?)\s*[x×*]\s*(\d+(?:\.\d+)?(?:mm|cm|m)?)",
        text,
    )
    if not m:
        return "", "", ""
    return m.group(1), m.group(2), m.group(3)


def _extract_json_object(raw_text: str):
    text = _to_str(raw_text)
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text, flags=re.IGNORECASE)
    if m:
        text = m.group(1).strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None


def _parse_advantages_text(value: str) -> list:
    text = _to_str(value)
    if not text:
        return []
    parts = re.split(r"[，,；;、/|\n]+", text)
    return [p.strip(" -·.。;；,，") for p in parts if p.strip(" -·.。;；,，")]


def _parse_text_by_template(raw_text: str) -> dict:
    """按固定字段模板快速解析（不调用AI）"""
    lines = [ln.strip() for ln in _to_str(raw_text).replace("\r\n", "\n").split("\n")]
    lines = [ln for ln in lines if ln]
    if not lines:
        return {}

    field_alias = {
        "品牌": "brand", "brand": "brand",
        "英文品牌": "brand_en", "brand_en": "brand_en", "品牌英文": "brand_en",
        "产品名称": "product_name", "名称": "product_name", "product_name": "product_name",
        "型号": "model", "机型": "model", "model": "model",
        "主标语": "slogan", "标语": "slogan", "slogan": "slogan",
        "副标语": "sub_slogan", "sub_slogan": "sub_slogan",
        "产品类型": "product_type", "类型": "product_type", "product_type": "product_type",
    }

    detail_key_alias = {
        "工作效率": "工作效率", "清洁效率": "工作效率",
        "最大清洁效率": "工作效率", "最大清洁效率m²/h": "工作效率",
        "清洗宽度": "清洗宽度", "清扫宽度": "清扫宽度", "吸水宽度": "吸水宽度",
        "清水容量": "清水容量", "污水容量": "污水容量",
        "清/污水箱容量": "污水容量", "水箱容量": "水箱容量",
        "尘箱容量": "尘箱容量", "工作时间": "工作时间",
        "续航": "工作时间", "续航时间": "工作时间",
        "刷盘电机": "刷盘电机", "吸水电机": "吸水电机",
        "刷盘压力": "刷盘压力", "工作噪音": "工作噪音",
        "电瓶容量": "电瓶容量", "锂电容量": "锂电容量",
        "整机重量": "整机重量", "设备尺寸": "产品尺寸",
        "产品尺寸": "产品尺寸", "尺寸": "产品尺寸",
        "边刷电机": "边刷电机", "电池规格": "电池规格",
        "垃圾箱容量": "垃圾箱容量", "清水箱容量": "清水箱容量",
        "驱动功率": "驱动功率", "驱动电机": "驱动电机",
        "刷盘功率": "刷盘功率", "吸水功率": "吸水功率",
        "充电时间": "充电时间", "电池容量": "电池容量",
        "产品净重": "产品净重",
    }

    result = {
        "brand": "", "brand_en": "", "product_name": "", "model": "",
        "slogan": "", "sub_slogan": "", "product_type": "",
        "core_params": {}, "detail_params": {},
        "advantages": [],
        "dimensions": {"length": "", "width": "", "height": ""},
    }

    kv_pattern = re.compile(r"^([^:：]{1,40})\s*[:：]\s*(.+)$")
    for ln in lines:
        m = kv_pattern.match(ln)
        if not m:
            continue
        raw_key = m.group(1).strip()
        raw_val = m.group(2).strip()
        if not raw_val:
            continue

        key_low = raw_key.lower()
        normalized_field = field_alias.get(raw_key) or field_alias.get(key_low)
        if normalized_field:
            result[normalized_field] = raw_val
            continue

        if any(token in raw_key for token in ("优势", "卖点", "亮点")):
            result["advantages"].extend(_parse_advantages_text(raw_val))
            continue

        d_key = detail_key_alias.get(raw_key) or detail_key_alias.get(raw_key.replace("：", "").strip())
        if d_key:
            result["detail_params"][d_key] = raw_val
            continue

        if len(raw_key) <= 20:
            result["detail_params"][raw_key] = raw_val

    size_text = _first_nonempty(
        result["detail_params"].get("产品尺寸", ""),
        result["detail_params"].get("设备尺寸", ""),
    )
    l, w, h = _parse_dimensions_from_text(size_text)
    if l and w and h:
        result["dimensions"] = {"length": l, "width": w, "height": h}

    detail = result["detail_params"]
    core_map = [
        ("工作效率", _first_nonempty(detail.get("工作效率", ""))),
        ("清洗宽度", _first_nonempty(detail.get("清洗宽度", ""), detail.get("清扫宽度", ""))),
        ("污水容量", _first_nonempty(detail.get("污水容量", ""), detail.get("水箱容量", ""), detail.get("尘箱容量", ""))),
        ("工作时间", _first_nonempty(detail.get("工作时间", ""), detail.get("续航时间", ""))),
    ]
    for k, v in core_map:
        if _to_str(v):
            result["core_params"][k] = _to_str(v)

    dedup = []
    seen = set()
    for item in result["advantages"]:
        val = _to_str(item)
        if not val or val in seen:
            continue
        dedup.append(val)
        seen.add(val)
    result["advantages"] = dedup[:6]

    useful_count = sum(1 for key in ("brand", "model", "product_name", "slogan", "sub_slogan", "product_type") if _to_str(result.get(key, "")))
    useful_count += len(result["detail_params"])
    if useful_count < 2:
        return {}
    return result


def _build_spec_rows(detail_params: dict) -> list:
    """将 detail_params 转为参数行列表，优先列显示重要参数，其余全量追加。不限行数。"""
    if not isinstance(detail_params, dict):
        return []

    priority = [
        "洗地效率", "清扫效率", "吸尘效率", "清洗宽度", "清扫作业宽度",
        "清水容量", "污水容量", "水箱容量", "尘箱容量",
        "工作效率", "工作时间", "续航时间", "充电时间",
        "刷盘功率", "吸水功率", "驱动功率",
        "刷盘电机", "吸水电机", "刷盘压力", "工作噪音",
        "电瓶容量", "锂电容量", "电池容量",
        "整机重量", "产品净重", "产品尺寸", "设备尺寸",
    ]

    rows = []
    used = set()
    for key in priority:
        value = _to_str(detail_params.get(key, ""))
        if value:
            rows.append({"name": key, "value": value})
            used.add(key)

    for key, value in detail_params.items():
        k = _to_str(key)
        v = _to_str(value)
        if not k or not v or k in used:
            continue
        rows.append({"name": k, "value": v})
        if len(rows) >= 20:
            break

    return rows[:20]


def _map_parsed_to_form_fields(parsed: dict) -> dict:
    """将解析结果映射为表单字段（供前端 AI 填表使用）"""
    parsed = parsed if isinstance(parsed, dict) else {}
    detail_params = parsed.get("detail_params", {})
    dimensions = parsed.get("dimensions", {})
    if not isinstance(dimensions, dict):
        dimensions = {}

    brand = _to_str(parsed.get("brand", ""))
    model = _first_nonempty(parsed.get("model"), parsed.get("product_name"))
    product_type_str = _to_str(parsed.get("product_type", ""))
    slogan = _to_str(parsed.get("slogan", ""))
    sub_slogan = _to_str(parsed.get("sub_slogan", ""))

    tagline_line1, tagline_line2 = _split_slogan(slogan)

    brand_text = ""
    if brand and product_type_str:
        brand_text = f"{brand}{product_type_str}"
    elif brand:
        brand_text = brand

    param_efficiency = _first_nonempty(
        parsed.get("param_efficiency"),
        _get_detail_value(detail_params, ["工作效率", "清洁效率", "最大清洁效率"]),
    )
    param_width = _first_nonempty(
        parsed.get("param_width"),
        _get_detail_value(detail_params, ["清洗宽度", "清扫宽度", "清扫作业宽度", "吸水宽度"]),
    )
    param_capacity = _first_nonempty(
        parsed.get("param_capacity"),
        _get_detail_value(detail_params, ["清水容量", "污水容量", "水箱容量", "尘箱容量"]),
    )
    param_runtime = _first_nonempty(
        parsed.get("param_runtime"),
        _get_detail_value(detail_params, ["工作时间", "续航时间", "续航"]),
    )

    specs = _build_spec_rows(detail_params)

    dim_length = _to_str(dimensions.get("length", ""))
    dim_width = _to_str(dimensions.get("width", ""))
    dim_height = _to_str(dimensions.get("height", ""))

    if not (dim_length and dim_width and dim_height):
        size_text = _first_nonempty(
            _get_detail_value(detail_params, ["产品尺寸", "设备尺寸", "尺寸"]),
        )
        l, w, h = _parse_dimensions_from_text(size_text)
        dim_length = dim_length or l
        dim_width = dim_width or w
        dim_height = dim_height or h

    _pn = _to_str(parsed.get("product_name", ""))
    _main = _first_nonempty(_to_str(parsed.get("main_title", "")), _pn)
    _cat = _first_nonempty(
        _to_str(parsed.get("category_line", "")),
        _to_str(parsed.get("product_type", "")),
    )
    _hero_sub = _to_str(parsed.get("hero_subtitle", ""))

    result = {
        "brand_text": brand_text,
        "model_name": model,
        "tagline_line1": tagline_line1,
        "tagline_line2": tagline_line2,
        "tagline_sub": sub_slogan,
        "category_line": _cat,
        "main_title": _main,
        "hero_subtitle_pre": _hero_sub,
        "hero_subtitle_em": "",
        "hero_subtitle_post": "",
        "param_1_label": "工作效率", "param_1_value": param_efficiency,
        "param_2_label": "清洗宽度", "param_2_value": param_width,
        "param_3_label": "清水箱", "param_3_value": param_capacity,
        "param_4_label": "续航时间", "param_4_value": param_runtime,
        "e_specs": specs,
        "e_dim_length": dim_length,
        "e_dim_width": dim_width,
        "e_dim_height": dim_height,
    }

    # ── 产品优势（AI生成 或 兜底推导）──
    advantages = parsed.get("advantages", [])
    if not advantages:
        advantages = _derive_advantages_from_specs(detail_params)
    for i, item in enumerate(advantages[:9]):
        if isinstance(item, dict):
            result[f"b2_icon_{i+1}"] = _to_str(item.get("emoji", "✅"))
            result[f"b2_label_{i+1}"] = _to_str(item.get("text", ""))
        elif isinstance(item, str):
            result[f"b2_icon_{i+1}"] = "✅"
            result[f"b2_label_{i+1}"] = item
    n = len(advantages[:9])
    result["b2_title_num"] = str(n)
    result["b2_title_text"] = "大核心优势"
    result["b2_subtitle"] = _to_str(parsed.get("product_type", "")) + "创新升级"

    # ── 清洁故事文案（AI生成）──
    result["b3_header_line1"] = _to_str(parsed.get("story_title_1", ""))
    result["b3_header_line2"] = _to_str(parsed.get("story_title_2", ""))
    result["b3_caption_line1"] = _to_str(parsed.get("story_desc_1", ""))
    result["b3_caption_line2"] = _to_str(parsed.get("story_desc_2", ""))
    result["b3_footer_line1"] = _to_str(parsed.get("story_bottom_1", ""))
    result["b3_footer_line2"] = _to_str(parsed.get("story_bottom_2", ""))

    # ── VS对比文案（AI生成）──
    vs = parsed.get("vs_comparison", {})
    if isinstance(vs, dict):
        count_num = _to_str(vs.get("replace_count", ""))
        left_title = _to_str(vs.get("left_title", ""))
        result["f_title_line1"] = "1台顶"
        result["f_title_line1_red"] = count_num or "多"
        result["f_title_line1_end"] = "人"
        result["f_title_line2"] = left_title + "与人工" if left_title else ""
        result["f_title_line2_red"] = "的区别。"
        result["f_vs_left_title"] = left_title
        result["f_vs_left_sub"] = _to_str(vs.get("left_sub", ""))
        result["f_vs_right_title"] = "传统人工"
        result["f_vs_right_sub"] = _to_str(vs.get("right_sub", ""))
        result["f_vs_left_bottom"] = _to_str(vs.get("left_bottom", ""))
        result["f_vs_right_bottom"] = _to_str(vs.get("right_bottom", ""))

    # ── 适用地面材质（AI生成）──
    floor_items = parsed.get("floor_items", [])
    if isinstance(floor_items, list) and floor_items:
        result["b3_floor_items_json"] = json.dumps(floor_items, ensure_ascii=False)

    # ── 品类扩展字段（列表类 → JSON）──
    _list_field_map = {
        "compat_models": "block_p_json",
        "package_items": "block_r_json",
        "kpis":          "block_i_json",
        "scenes":        "block_h_json",
        "before_after":  "block_q_json",
    }
    for src_key, dest_key in _list_field_map.items():
        val = parsed.get(src_key)
        if isinstance(val, list) and val:
            result[dest_key] = json.dumps(val, ensure_ascii=False)
    # install_steps / usage_steps 合并为 block_m_json
    steps = parsed.get("install_steps") or parsed.get("usage_steps")
    if isinstance(steps, list) and steps:
        result["block_m_json"] = json.dumps(steps, ensure_ascii=False)

    print(f"[映射] b2_label_1={result.get('b2_label_1','(空)')}, b3_header_line1={result.get('b3_header_line1','(空)')}")

    return result


# ── 配置加载 ─────────────────────────────────────────────────────────

_build_config_cache = {}   # {product_type: (mtime, cfg)}


def _load_build_config(product_type: str) -> dict:
    cfg_path = TEMPLATES_DIR / product_type / "build_config.json"
    if not cfg_path.exists():
        return {}
    mtime = cfg_path.stat().st_mtime
    cached = _build_config_cache.get(product_type)
    if cached and cached[0] == mtime:
        return cached[1]
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    _build_config_cache[product_type] = (mtime, cfg)
    return cfg


# ── 图片上传工具 ──────────────────────────────────────────────────────

STATIC_UPLOADS = BASE_DIR / "static" / "uploads"
STATIC_UPLOADS.mkdir(parents=True, exist_ok=True)
STATIC_OUTPUTS = BASE_DIR / "static" / "outputs"
STATIC_OUTPUTS.mkdir(parents=True, exist_ok=True)


def _save_upload(file_field_name, auto_rembg: bool = False) -> str:
    """保存上传图片到 static/uploads/，返回 /static/uploads/xxx.ext URL
    auto_rembg=True 时对白底产品图自动抠图（只处理 product_image）
    """
    f = request.files.get(file_field_name)
    if not f or not f.filename:
        return ""
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else "png"
    uid = uuid.uuid4().hex
    filename = f"{uid}.{ext}"
    save_path = STATIC_UPLOADS / filename
    f.save(str(save_path))

    if auto_rembg and REMBG_AVAILABLE:
        try:
            from PIL import Image as _Img
            import numpy as np
            import rembg
            # 如果已有真实透明区域则跳过
            needs_rembg = True
            im = _Img.open(save_path)
            if im.mode == "RGBA":
                alpha = np.array(im)[:, :, 3]
                if alpha.min() < 250:
                    needs_rembg = False
                    print(f"[抠图] {filename} 已有透明底，跳过", flush=True)
            if needs_rembg:
                from PIL import ImageFilter
                import io as _io
                print(f"[抠图] 开始处理 {filename}（AI+色值混合）…", flush=True)

                # 复用已打开的图片，转 RGB
                orig = im.convert("RGB")
                arr = np.array(orig)
                h, w = arr.shape[:2]

                # 1) AI 抠图
                with open(save_path, "rb") as inp:
                    ai_bytes = rembg.remove(inp.read(), session=REMBG_SESSION)
                ai_img = _Img.open(_io.BytesIO(ai_bytes)).convert("RGBA")
                ai_alpha = np.array(ai_img)[:, :, 3]

                # 2) 用色值清理 AI 遗漏的纯白背景残留
                corners = [arr[:15, :15], arr[:15, -15:], arr[-15:, :15], arr[-15:, -15:]]
                bg_min = np.concatenate([c.reshape(-1, 3) for c in corners]).min(axis=0)
                threshold = max(int(bg_min.min()) - 2, 248)
                pure_bg = np.all(arr >= threshold, axis=2)
                # AI 认为半透明 + 色值是纯白 → 设为全透明
                ai_alpha[pure_bg & (ai_alpha < 200)] = 0

                # 3) 保存
                result_arr = np.dstack([arr, ai_alpha])
                result_img = _Img.fromarray(result_arr.astype(np.uint8), "RGBA")
                nobg_filename = f"{uid}_nobg.png"
                nobg_path = STATIC_UPLOADS / nobg_filename
                result_img.save(str(nobg_path))
                print(f"[抠图] 完成 → {nobg_filename}", flush=True)
                return f"/static/uploads/{nobg_filename}"
        except Exception as e:
            import traceback
            print(f"[抠图] 失败，使用原图: {e}", flush=True)
            traceback.print_exc()
    elif auto_rembg and not REMBG_AVAILABLE:
        print(f"[抠图] rembg 未安装，跳过 {filename}。运行: pip install rembg onnxruntime", flush=True)

    return f"/static/uploads/{filename}"


# ── 基础路由 ─────────────────────────────────────────────────────────

_CATEGORIES = [
    {"type": "设备类", "desc": "商用清洁机器人、洗地机、扫地车等大型设备", "color": "#E8231A", "icon": "🤖"},
    {"type": "配耗类", "desc": "刷盘、滤芯、吸水胶条等设备配件", "color": "#1E6FBF", "icon": "🔧"},
    {"type": "耗材类", "desc": "清洁剂、除垢液、清洁垫等消耗品", "color": "#2E8B57", "icon": "🧪"},
    {"type": "工具类", "desc": "拖把、刮水器、清洁桶等手动工具", "color": "#E87C1A", "icon": "🧹"},
]

@app.route("/")
def index():
    return render_template("index.html", categories=_CATEGORIES)


@app.route("/api/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "请求中没有文件字段"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "文件名为空"}), 400
    if not allowed_img(file.filename):
        return jsonify({"error": f"不支持的格式，请上传 {', '.join(ALLOWED_IMG)}"}), 400
    ext = file.filename.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    save_path = STATIC_UPLOADS / filename
    file.save(str(save_path))
    return jsonify({"path": str(save_path), "filename": filename, "url": f"/static/uploads/{filename}"})
# ── 文本解析（DeepSeek API）──────────────────────────────────────────
_EXTREME_WORDS_RULE = (
    "【合规要求】文案中严禁出现以下极限词（电商平台违禁词）：\n"
    "最强、最大、最好、最高、最低、最快、最优、最先进、最专业、最安全、最耐用、最便捷、最智能、\n"
    "第一、唯一、极致、顶级、顶尖、行业领先、业界领先、全球领先、世界领先、无与伦比。\n"
    "请用具体数据或中性词替代，如【超强】【高效】【优质】【行业前列】等。\n\n"
)


def _build_category_prompt(product_type: str, raw_text: str) -> str:
    """根据产品类型构建对应的 DeepSeek 解析提示词"""

    if product_type == "配耗类":
        return (
            "你是一个清洁配件营销文案专家。请根据以下产品参数，完成两件事：\n\n"
            "第一，提取所有技术参数（型号、规格、材质等）填入对应字段。\n"
            "第二，根据这些参数生成营销文案（严格基于真实数据，不得编造产品没有的功能）。\n\n"
            + _EXTREME_WORDS_RULE +
            "返回以下JSON格式（所有字段必须返回，不要遗漏）：\n"
            "```json\n"
            "{\n"
            '  "brand": "品牌中文名",\n'
            '  "product_name": "产品全称",\n'
            '  "model": "型号/规格",\n'
            '  "product_type": "配件类型（如刷盘、吸水胶条、滤芯）",\n'
            '  "detail_params": {"参数名":"参数值", ...},\n'
            '  "dimensions": {"length":"mm值","width":"mm值","height":"mm值"},\n'
            '  "category_line": "产品品类短语（不超过10字）",\n'
            '  "hero_subtitle": "副标题（适配XX系列，原厂品质，不超过15字）",\n'
            '  "slogan": "主标语（一句话概括产品最大卖点）",\n'
            '  "sub_slogan": "副标语（补充说明）",\n'
            '  "advantages": [\n'
            '    {"emoji":"🔧","text":"原厂适配"},\n'
            '    ...\n'
            '  ],\n'
            '  "compat_models": [\n'
            '    {"model":"DZ50X","series":"清洁机器人系列"},\n'
            '    ...\n'
            '  ],\n'
            '  "install_steps": [\n'
            '    {"title":"拆卸旧件","desc":"关闭电源，取下旧配件"},\n'
            '    ...\n'
            '  ],\n'
            '  "package_items": [\n'
            '    {"name":"主刷","qty":"1","note":""},\n'
            '    ...\n'
            '  ]\n'
            "}\n"
            "```\n\n"
            "【重要提示】\n"
            "- 识别文案中提到的所有兼容机型，填入 compat_models（多列出，不要遗漏）\n"
            "- install_steps 提供清晰的安装步骤（3-6步）\n"
            "- package_items 列出包装内所有配件清单\n"
            "- advantages 6-9项，每项附带贴切的emoji，严禁编造\n\n"
            "只返回JSON，不要其他解释文字：\n\n" + raw_text
        )

    elif product_type == "耗材类":
        return (
            "你是一个清洁耗材营销文案专家。请根据以下产品参数，完成两件事：\n\n"
            "第一，提取所有技术参数（型号、规格、成分、稀释比等）填入对应字段。\n"
            "第二，根据这些参数生成营销文案（严格基于真实数据，不得编造产品没有的功能）。\n\n"
            + _EXTREME_WORDS_RULE +
            "返回以下JSON格式（所有字段必须返回，不要遗漏）：\n"
            "```json\n"
            "{\n"
            '  "brand": "品牌中文名",\n'
            '  "product_name": "产品全称",\n'
            '  "model": "型号/规格",\n'
            '  "product_type": "耗材类型（如清洁剂、除垢液）",\n'
            '  "detail_params": {"参数名":"参数值", ...},\n'
            '  "dimensions": {"length":"mm值","width":"mm值","height":"mm值"},\n'
            '  "category_line": "产品品类短语（不超过10字）",\n'
            '  "hero_subtitle": "副标题（不超过15字）",\n'
            '  "slogan": "主标语（突出稀释比或覆盖面积）",\n'
            '  "sub_slogan": "副标语（补充说明）",\n'
            '  "advantages": [\n'
            '    {"emoji":"🧪","text":"专业配方"},\n'
            '    ...\n'
            '  ],\n'
            '  "usage_steps": [\n'
            '    {"title":"稀释","desc":"按1:200比例加水稀释"},\n'
            '    ...\n'
            '  ],\n'
            '  "kpis": [\n'
            '    {"label":"稀释比","value":"1:200","unit":"","note":""},\n'
            '    ...\n'
            '  ],\n'
            '  "before_after": [\n'
            '    {"before_label":"使用前","after_label":"使用后","desc":"顽固油污一喷即净"}\n'
            '  ]\n'
            "}\n"
            "```\n\n"
            "【重要提示】\n"
            "- 强调安全性（是否食品级、是否需要防护）\n"
            "- kpis 列出稀释比、覆盖面积、每升成本等关键指标\n"
            "- usage_steps 提供清晰的使用步骤（3-5步）\n"
            "- before_after 描述使用前后的清洁效果对比\n"
            "- advantages 6-9项，每项附带贴切的emoji，严禁编造\n\n"
            "只返回JSON，不要其他解释文字：\n\n" + raw_text
        )

    elif product_type == "工具类":
        return (
            "你是一个清洁工具营销文案专家。请根据以下产品参数，完成两件事：\n\n"
            "第一，提取所有技术参数（型号、材质、规格等）填入对应字段。\n"
            "第二，根据这些参数生成营销文案（严格基于真实数据，不得编造产品没有的功能）。\n\n"
            + _EXTREME_WORDS_RULE +
            "返回以下JSON格式（所有字段必须返回，不要遗漏）：\n"
            "```json\n"
            "{\n"
            '  "brand": "品牌中文名",\n'
            '  "product_name": "产品全称",\n'
            '  "model": "型号/规格",\n'
            '  "product_type": "工具类型（如拖把、刮水器）",\n'
            '  "detail_params": {"参数名":"参数值", ...},\n'
            '  "dimensions": {"length":"mm值","width":"mm值","height":"mm值"},\n'
            '  "category_line": "产品品类短语（不超过10字）",\n'
            '  "hero_subtitle": "副标题（不超过15字）",\n'
            '  "slogan": "主标语（突出材质或耐用性）",\n'
            '  "sub_slogan": "副标语（补充说明）",\n'
            '  "advantages": [\n'
            '    {"emoji":"🔩","text":"坚固耐用"},\n'
            '    ...\n'
            '  ],\n'
            '  "scenes": [\n'
            '    {"name":"商场","desc":"大面积地面清洁"},\n'
            '    ...\n'
            '  ],\n'
            '  "package_items": [\n'
            '    {"name":"拖把杆","qty":"1","note":""},\n'
            '    ...\n'
            '  ],\n'
            '  "before_after": [\n'
            '    {"before_label":"使用前","after_label":"使用后","desc":"效果说明"}\n'
            '  ]\n'
            "}\n"
            "```\n\n"
            "【重要提示】\n"
            "- 强调材质品质和耐用寿命\n"
            "- scenes 列出适用场景（3-6个），如商场、医院、学校、工厂等\n"
            "- package_items 列出包装内所有配件清单\n"
            "- before_after 描述使用前后的清洁效果对比\n"
            "- advantages 6-9项，每项附带贴切的emoji，严禁编造\n\n"
            "只返回JSON，不要其他解释文字：\n\n" + raw_text
        )

    else:
        # 设备类（默认）
        return (
            "你是一个清洁设备营销文案专家。请根据以下产品参数，完成两件事：\n\n"
            "第一，提取所有技术参数（型号、尺寸、功率等）填入对应字段。\n"
            "第二，根据这些参数生成营销文案（严格基于真实数据，不得编造产品没有的功能）。\n\n"
            + _EXTREME_WORDS_RULE +
            "返回以下JSON格式（所有字段必须返回，不要遗漏）：\n"
            "```json\n"
            "{\n"
            '  "brand": "品牌中文名",\n'
            '  "brand_en": "品牌英文名",\n'
            '  "product_name": "产品全称",\n'
            '  "model": "型号",\n'
            '  "product_type": "设备中文类型（如驾驶式扫地车）",\n'
            '  "detail_params": {"参数名":"参数值（完整展示，商用产品参数要详细全面）", ...},\n'
            '  "dimensions": {"length":"mm值","width":"mm值","height":"mm值"},\n'
            '  "category_line": "产品品类短语（如 驾驶式洗地机 / 商用清洁机器人，不超过10字）",\n'
            '  "hero_subtitle": "首屏副标题（描述适用场景+核心能力，如 大型商场高效清洁专家，不超过15字）",\n'
            '  "floor_items": [{"icon_text":"单字","label":"地面材质名"},...] （根据产品适用场景列出4-8种适用地面材质，如大理石、环氧地坪、瓷砖、水磨石、PVC地板等，没有相关信息则返回空数组）,\n'
            '  "slogan": "主标语（一句话概括产品最大卖点，用真实数据）",\n'
            '  "sub_slogan": "副标语（补充说明）",\n'
            '  "advantages": [\n'
            '    {"emoji":"🧹","text":"超宽清扫"},\n'
            '    {"emoji":"⚡","text":"高效清扫"},\n'
            '    ...\n'
            '  ],\n'
            '  "story_title_1": "清洁故事大标题1（突出核心清洁机构，如 660mm大直径主刷+4边刷设计）",\n'
            '  "story_title_2": "清洁故事大标题2（效果声明，如 高效清扫14600m²/h大面积场所。）",\n'
            '  "story_desc_1": "图片说明行1（关键参数短语，如 主刷660mm、4组边刷500mm、清扫宽度1800mm）",\n'
            '  "story_desc_2": "图片说明行2（总结短句，如 宽幅清扫，一步到位）",\n'
            '  "story_bottom_1": "底部卖点1（最亮眼的数字宣称，如 14600m²/h超大清扫效率，没有突出数据就留空字符串）",\n'
            '  "story_bottom_2": "底部卖点2（效果短句，如 大场所清扫首选）",\n'
            '  "vs_comparison": {\n'
            '    "replace_count": "只填数字，如 8-10 或 3-5（估算可替代人数，没依据填 多）",\n'
            '    "annual_saving": "只填金额，如 26W+ 或 15W+（估算年省人力成本，没依据留空）",\n'
            '    "left_title": "产品类型简称，不超过8字（如 智能洗扫机器人）",\n'
            '    "left_sub": "机械优势3-6字（如 省时省钱省心）",\n'
            '    "right_sub": "人工劣势3-6字（如 费时费钱费心）",\n'
            '    "left_bottom": "机械结论两行用<br>隔开（如 1台可顶8-10人<br>一年劲省26W+元）",\n'
            '    "right_bottom": "人工结论两行用<br>隔开（如 人工效率低<br>成本高）"\n'
            '  }\n'
            "}\n"
            "```\n\n"
            "【advantages规则】\n"
            "- 6-9项，根据产品实际功能特点决定数量，不强制凑满9个，每项2-6个字（如 超强续航、一机多用、电泳防锈）\n"
            "- 每项附带一个贴切的emoji\n"
            "- 从产品参数推导，覆盖效率/容量/工艺/安全/动力/续航等维度\n"
            "- 严禁出现产品没有的功能（没有AI导航就不能写智能避障）\n\n"
            "只返回JSON，不要其他解释文字：\n\n" + raw_text
        )


def _call_deepseek_parse(raw_text: str, product_type: str = "设备类") -> dict:
    """调用 DeepSeek API，一次完成：解析产品参数 + 生成营销文案"""
    import requests as req
    prompt = _build_category_prompt(product_type, raw_text)
    print(f"[DeepSeek] 发送请求，文本长度={len(raw_text)}...")
    resp = req.post(
        DEEPSEEK_API_URL,
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
        json={
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": "你是清洁设备营销文案专家。解析产品参数并生成营销文案。只返回JSON。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
        },
        proxies=PROXY,
        timeout=120,
    )
    resp.raise_for_status()
    msg = resp.json()["choices"][0]["message"]
    raw = (msg.get("content") or "").strip()

    print(f"[DeepSeek] 原始响应长度={len(raw)}")
    print(f"[DeepSeek] 响应前200字: {raw[:200]}")

    if "```" in raw:
        m = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
        if m:
            raw = m.group(1).strip()

    if not raw.startswith("{"):
        start = raw.find("{")
        if start != -1:
            raw = raw[start:]

    parsed = json.loads(raw.strip())
    print(f"[DeepSeek] 解析成功，字段: {list(parsed.keys())}")
    adv = parsed.get("advantages", [])
    print(f"[DeepSeek] advantages数量={len(adv)}，前3项={adv[:3]}")
    print(f"[DeepSeek] story_title_1={parsed.get('story_title_1','(无)')}")

    # ── 极限词过滤 ──
    for _field in ["slogan", "sub_slogan", "category_line", "hero_subtitle",
                   "story_title_1", "story_title_2",
                   "story_desc_1", "story_desc_2", "story_bottom_1", "story_bottom_2"]:
        if _field in parsed:
            parsed[_field] = _strip_extreme_words(_to_str(parsed[_field]))
    for _adv in parsed.get("advantages", []):
        if isinstance(_adv, dict) and "text" in _adv:
            _adv["text"] = _strip_extreme_words(_to_str(_adv["text"]))
    # VS对比字段极限词过滤
    vs = parsed.get("vs_comparison", {})
    if isinstance(vs, dict):
        for _vf in ["replace_count", "annual_saving", "left_title", "left_sub",
                     "right_sub", "left_bottom", "right_bottom"]:
            if _vf in vs:
                vs[_vf] = _strip_extreme_words(_to_str(vs[_vf]))

    return parsed


def _derive_advantages_from_specs(detail_params: dict) -> list:
    """兜底：当 AI 不返回 advantages 时，从参数规格自动推导"""
    if not isinstance(detail_params, dict):
        return []
    mapping = [
        (["清扫宽度", "清扫作业宽度"], "🧹", "超宽清扫"),
        (["工作效率", "清洁效率", "最大清洁效率"], "⚡", "高效清扫"),
        (["垃圾箱容量"], "🗑️", "超大垃圾箱"),
        (["水箱容量", "清水容量"], "💧", "大容量水箱"),
        (["爬坡能力"], "⛰️", "强力爬坡"),
        (["制动方式"], "🛑", "安全制动"),
        (["电池容量", "电瓶容量", "锂电容量"], "🔋", "持久续航"),
        (["连续工作时间", "工作时间", "续航时间"], "⏱️", "持续作业"),
        (["最大行驶速度", "最大工作速度"], "🏎️", "高速作业"),
        (["外壳材质"], "🛡️", "防腐耐用"),
        (["驱动功率"], "💪", "强劲动力"),
        (["主刷"], "🔄", "大直径主刷"),
        (["边刷"], "🌀", "多组边刷"),
        (["清洗宽度", "吸水宽度"], "🧽", "高效洗地"),
    ]
    items = []
    used = set()
    for keys, emoji, text in mapping:
        for k in keys:
            if detail_params.get(k) and k not in used:
                items.append({"emoji": emoji, "text": text})
                used.add(k)
                break
        if len(items) >= 9:
            break
    return items
@app.route("/api/build/<product_type>/parse-text", methods=["POST"])
def parse_text_for_build(product_type):
    data = request.get_json(silent=True)
    if not data or not data.get("text"):
        return jsonify({"error": "缺少 text 字段"}), 400

    raw_text = _to_str(data.get("text"))
    if not raw_text:
        return jsonify({"error": "文本内容为空"}), 400

    # 直接调 DeepSeek —— 必须用 AI 才能生成 advantage_labels 和 clean_story
    try:
        parsed = _call_deepseek_parse(raw_text, product_type)
    except Exception as e:
        # DeepSeek 失败时降级到模板解析（不含卖点生成）
        parsed = _extract_json_object(raw_text)
        if not isinstance(parsed, dict):
            parsed = _parse_text_by_template(raw_text)
        if not isinstance(parsed, dict) or not parsed:
            return jsonify({"error": f"AI 解析失败: {e}"}), 500

    mapped = _map_parsed_to_form_fields(parsed)
    return jsonify(mapped)


# ══════════════════════════════════════════════════════════════════════
# ── 构建系统（设备类，blocks 引擎）──────────────────────────────────
# ══════════════════════════════════════════════════════════════════════

@app.route('/build/<product_type>', methods=['GET'])
def build_form_generic(product_type):
    cfg = _load_build_config(product_type)
    if not cfg:
        return f"未找到产品类型 [{product_type}] 的配置", 404
    return render_template('build_form.html', config=cfg, product_type=product_type)


@app.route('/build/<product_type>', methods=['POST'])
def build_submit_generic(product_type):
    cfg = _load_build_config(product_type)
    if not cfg:
        return f"未找到产品类型 [{product_type}] 的配置", 404

    F = request.form

    def form_text(name, default=""):
        return _fallback_text(F.get(name, ""), default)

    # ── 图片上传 ──
    product_image      = _save_upload('product_image',      auto_rembg=True)  # 产品主图自动抠白底
    scene_image        = _save_upload('scene_image')                          # 场景底图保留背景
    product_side_image = _save_upload('product_side_image', auto_rembg=True)  # 侧面图自动抠白底
    effect_image       = _save_upload('effect_image')                         # 效果图保留背景
    logo_image         = _save_upload('logo_image')

    # ── 英雄屏参数条（跳过空值、占位符、过长值）──
    hero_params = []
    for i in range(1, 5):
        v = form_text(f'param_{i}_value', '').strip()
        l = form_text(f'param_{i}_label', '').strip()
        if v and v not in ('--', '-', '无', 'N/A') and len(v) <= 16:
            hero_params.append({"value": v, "label": l})
    if not hero_params:
        hero_params = [
            {"value": hp.get("default_value", ""), "label": hp.get("label", "")}
            for hp in cfg.get("hero_params", [])
            if hp.get("default_value", "").strip()
        ]

    # ── Block A（英雄屏）──
    _hcov = cfg.get("hero_cover_defaults") or {}
    _def = cfg.get("defaults") or {}
    block_a = {
        "brand_text": form_text('brand_text', _def.get("brand_text", "")),
        "model_name": form_text('model_name', _def.get("model_name", "")),
        "tagline_line1": form_text('tagline_line1', _def.get("tagline_line1", "")),
        "tagline_line2": form_text('tagline_line2', _def.get("tagline_line2", "")),
        "tagline_sub": form_text('tagline_sub', _def.get("tagline_sub", "")),
        "bg_image": scene_image,
        "product_image": product_image,
        "logo_image": logo_image,
        "category_line": form_text('category_line', _hcov.get("category_line", "")),
        "main_title": form_text('main_title', _hcov.get("main_title", "")),
        "hero_subtitle_pre": form_text('hero_subtitle_pre', _hcov.get("hero_subtitle_pre", "")),
        "hero_subtitle_em": form_text('hero_subtitle_em', _hcov.get("hero_subtitle_em", "")),
        "hero_subtitle_post": form_text('hero_subtitle_post', _hcov.get("hero_subtitle_post", "")),
        "footer_note": form_text('footer_note', _hcov.get("footer_note", "")),
        "cover_image": "",
        "floor_bg_image": scene_image,
        "bg_focal": form_text('bg_focal', _hcov.get("bg_focal", "center bottom")) or "center bottom",
        "show_hero_params": True,
        "params": hero_params,
    }

    # ── Block E（参数表）──
    e_specs = []
    for i in range(1, 21):
        name = form_text(f'e_spec_name_{i}', '')
        value = form_text(f'e_spec_value_{i}', '')
        if name and value:
            e_specs.append({"name": name, "value": value})

    model_name = form_text('model_name', _def.get("model_name", ""))
    _e_red = form_text("e_red_bar_text", "").strip()
    _dims = cfg.get("default_dims", {})
    block_e = {
        "title": "产品参数",
        "subtitle": form_text("e_table_subtitle", "规格一览"),
        "red_bar_text": _e_red or f"{model_name}创新升级",
        "product_image": product_side_image or product_image,
        "dim_height": form_text('e_dim_height', _dims.get("height", "")),
        "dim_width":  form_text('e_dim_width',  _dims.get("width", "")),
        "dim_length": form_text('e_dim_length', _dims.get("length", "")),
        "specs": e_specs,
        "footnote": "*人工测量有误差",
    }

    # ── blocks_hardcoded（从配置读，表单值可覆盖）──
    blocks_hc = cfg.get("blocks_hardcoded", {})

    # ── Block B2（优势网格）— 完全从表单构建 ──
    block_b2_cfg = blocks_hc.get("block_b2", {})
    b2_items = []
    for i in range(1, 10):
        label = form_text(f"b2_label_{i}", "")
        icon = form_text(f"b2_icon_{i}", "")
        if label:
            b2_items.append({"icon_image": "", "icon_text": icon or "✅", "label": label})
    # 兜底：没有表单数据时用配置默认
    if not b2_items:
        b2_items = block_b2_cfg.get("items", [])
    block_b2 = {
        "title_num": form_text("b2_title_num", "") or block_b2_cfg.get("title_num", str(len(b2_items))),
        "title_text": form_text("b2_title_text", "") or block_b2_cfg.get("title_text", "大核心优势"),
        "subtitle": form_text("b2_subtitle", "") or block_b2_cfg.get("subtitle", ""),
        "grid_columns": block_b2_cfg.get("grid_columns", 3),
        "items": b2_items,
    }

    # ── Block B3（清洁故事）— 表单文案覆盖 ──
    block_b3 = dict(blocks_hc.get("block_b3", {}))
    for _field in ["header_line1", "header_line2", "caption_line1", "caption_line2", "footer_line1", "footer_line2"]:
        _v = form_text(f"b3_{_field}", "")
        if _v:
            block_b3[_field] = _v
    if not (block_b3.get("hero_image") or "").strip():
        block_b3["hero_image"] = product_image
    # AI 生成的地面材质覆盖硬编码
    _floor_json = form_text("b3_floor_items_json", "")
    if _floor_json:
        try:
            _floor_list = json.loads(_floor_json)
            if isinstance(_floor_list, list) and _floor_list:
                block_b3["floor_items"] = _floor_list
        except (json.JSONDecodeError, ValueError):
            pass

    # ── Block F（VS对比）— 表单文案覆盖 + 图片注入 ──
    block_f = dict(blocks_hc.get("block_f", {}))
    for _field in ["title_line1", "title_line1_red", "title_line1_end",
                    "title_line2", "title_line2_red",
                    "vs_left_title", "vs_left_sub", "vs_right_title", "vs_right_sub",
                    "vs_left_bottom", "vs_right_bottom"]:
        _v = form_text(f"f_{_field}", "")
        if _v:
            block_f[_field] = _v
    block_f["product_image"] = product_image

    # ── 固定卖点图 ──
    fixed_selling_images = [
        f"/static/{product_type}/{fname}"
        for fname in cfg.get("fixed_selling_images", [])
    ]

    # ── 扩展积木（从配置读取默认值 + 表单覆盖）──
    extra_blocks = {k: dict(cfg.get(k, {})) for k in _EXTRA_BLOCK_KEYS}

    # 品牌背书 (block_g) — 表单文本覆盖
    _g_title = form_text("g_brand_title", "")
    _g_sub = form_text("g_brand_subtitle", "")
    if _g_title:
        extra_blocks["block_g"]["brand_title"] = _g_title
    if _g_sub:
        extra_blocks["block_g"]["brand_subtitle"] = _g_sub

    # 表单 JSON 字段覆盖（AI 识别填入 → 用户可编辑 → 提交覆盖配置默认）
    _json_field_map = {
        "block_h_json": ("block_h", "scenes"),
        "block_i_json": ("block_i", "kpis"),
        "block_m_json": ("block_m", "steps"),
        "block_p_json": ("block_p", "compat_models"),
        "block_q_json": ("block_q", "comparisons"),
        "block_r_json": ("block_r", "package_items"),
    }
    for form_field, (block_key, data_key) in _json_field_map.items():
        _raw = form_text(form_field, "")
        if _raw:
            try:
                _parsed = json.loads(_raw)
                if isinstance(_parsed, list) and _parsed:
                    extra_blocks[block_key][data_key] = _parsed
            except (json.JSONDecodeError, ValueError):
                pass

    data = {
        "product_type": product_type,
        "block_a": block_a,
        "block_b2": block_b2,
        "block_b3": block_b3,
        "block_f": block_f,
        "block_e": block_e,
        **extra_blocks,
        "fixed_selling_images": fixed_selling_images,
        "effect_image": effect_image,
        "hero_block_template": cfg.get("hero_block_template", "blocks/block_a_hero_robot_cover.html"),
        "spec_block_template": cfg.get("spec_block_template", "blocks/block_e_glass_dimension.html"),
    }

    # 保存预览数据供导出使用
    _save_data = dict(data)
    _last_preview = OUTPUT_DIR / f"_last_{product_type}_preview.json"
    with open(_last_preview, "w", encoding="utf-8") as fp:
        json.dump(_save_data, fp, ensure_ascii=False)

    return render_template(f"{product_type}/assembled.html", **data)


# ── 导出PNG（Playwright截图）────────────────────────────────────────

@app.route('/export/<product_type>', methods=['POST'])
def export_generic(product_type):
    preview_json = OUTPUT_DIR / f"_last_{product_type}_preview.json"
    if not preview_json.exists():
        return jsonify({"error": "没有预览数据，请先生成预览"}), 400

    with open(preview_json, "r", encoding="utf-8") as fp:
        data = json.load(fp)

    data["export_mode"] = True

    tpl = f"{product_type}/assembled.html"
    html_content = render_template(tpl, **data)

    base_url_str = str(BASE_DIR).replace("\\", "/")
    html_content = html_content.replace('src="/static/', f'src="file:///{base_url_str}/static/')
    html_content = html_content.replace("src='/static/", f"src='file:///{base_url_str}/static/")

    temp_html = OUTPUT_DIR / f"_export_{product_type}.html"
    with open(temp_html, "w", encoding="utf-8") as f:
        f.write(html_content)

    from datetime import datetime
    model_name = data.get("block_a", {}).get("model_name", product_type)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_filename = f"{product_type}_{model_name}_{timestamp}.png"
    out_path = STATIC_OUTPUTS / out_filename

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                args=["--disable-web-security", "--allow-file-access-from-files"]
            )
            ctx = browser.new_context(
                viewport={"width": 750, "height": 900},
                device_scale_factor=2,
            )
            page = ctx.new_page()
            page.goto(temp_html.as_uri(), wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)
            page.screenshot(path=str(out_path), full_page=True)
            browser.close()
    except Exception as exc:
        import traceback; traceback.print_exc()
        return jsonify({"error": f"Playwright截图失败: {exc}"}), 500

    return send_file(str(out_path), mimetype="image/png",
                     as_attachment=True, download_name=out_filename)


# ── 设备类静态预览（调试用）──────────────────────────────────────────

@app.route("/preview/设备类")
def preview_equipment():
    cfg = _load_build_config(PRODUCT_TYPE) or {}
    _bhc = cfg.get("blocks_hardcoded") or {}
    _defs = cfg.get("defaults") or {}
    _hcov = cfg.get("hero_cover_defaults") or {}
    _dims = cfg.get("default_dims") or {}

    fixed_selling_images = [
        f"/static/{PRODUCT_TYPE}/{fname}"
        for fname in cfg.get("fixed_selling_images", [])
    ]

    data = {
        "product_type": PRODUCT_TYPE,
        "hero_block_template": cfg.get("hero_block_template", "blocks/block_a_hero_robot_cover.html"),
        "spec_block_template": cfg.get("spec_block_template", "blocks/block_e_glass_dimension.html"),
        "fixed_selling_images": fixed_selling_images,
        "block_a": {
            "brand_text": _defs.get("brand_text", ""),
            "model_name": _defs.get("model_name", ""),
            "bg_image": "",
            "product_image": "",
            "tagline_line1": _defs.get("tagline_line1", ""),
            "tagline_line2": _defs.get("tagline_line2", ""),
            "tagline_sub": _defs.get("tagline_sub", ""),
            "logo_image": "",
            "category_line": _hcov.get("category_line", ""),
            "main_title": _hcov.get("main_title", ""),
            "hero_subtitle_pre": _hcov.get("hero_subtitle_pre", ""),
            "hero_subtitle_em": _hcov.get("hero_subtitle_em", ""),
            "hero_subtitle_post": _hcov.get("hero_subtitle_post", ""),
            "footer_note": _hcov.get("footer_note", ""),
            "cover_image": f"/static/{PRODUCT_TYPE}/{cfg.get('default_cover_image', '')}",
            "floor_bg_image": "",
            "bg_focal": _hcov.get("bg_focal", "center bottom"),
            "show_hero_params": False,
            "params": [
                {"value": hp.get("default_value", ""), "label": hp.get("label", "")}
                for hp in cfg.get("hero_params", [])
            ],
        },
        "block_b2": _bhc.get("block_b2", {}),
        "block_b3": dict(_bhc.get("block_b3", {})),
        "block_f": dict(_bhc.get("block_f", {})),
        "block_e": {
            "title": "产品参数",
            "subtitle": "规格一览",
            "red_bar_text": f"{_defs.get('model_name', '')}创新升级",
            "product_image": "",
            "dim_height": _dims.get("height", ""),
            "dim_width": _dims.get("width", ""),
            "dim_length": _dims.get("length", ""),
            "specs": [
                {"name": x.get("name", ""), "value": x.get("value", "")}
                for x in cfg.get("default_specs", [])
            ],
            "footnote": "*人工测量有误差",
        },
        **{k: cfg.get(k, {}) for k in _EXTRA_BLOCK_KEYS},
    }
    return render_template(f"{PRODUCT_TYPE}/assembled.html", **data)


# ────────────────────────────────────────────────────────────────────

def _kill_old_flask(port=5000):
    """启动前自动清理占用端口的旧 Flask 进程（Windows）"""
    import subprocess
    try:
        result = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=5
        )
        pids = set()
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                if parts:
                    pids.add(parts[-1])
        my_pid = str(os.getpid())
        pids.discard(my_pid)
        pids.discard("0")
        for pid in pids:
            print(f"[启动] 杀掉旧进程 PID={pid} (占用端口 {port})")
            subprocess.run(["taskkill", "/F", "/PID", pid],
                           capture_output=True, timeout=5)
    except Exception as e:
        print(f"[启动] 清理旧进程时出错(可忽略): {e}")


if __name__ == "__main__":
    _kill_old_flask(5000)
    print("=" * 50)
    print("  物保云产品详情页生成器 - Web UI")
    print("=" * 50)
    print(f"  入口: http://localhost:5000/build/{PRODUCT_TYPE}")
    print(f"  预览: http://localhost:5000/preview/{PRODUCT_TYPE}")
    print("=" * 50)
    app.run(debug=True, port=5000, use_reloader=False)
