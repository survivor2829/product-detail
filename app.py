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

ALLOWED_IMG = {"jpg", "jpeg", "png", "webp"}

# ── DeepSeek API 配置 ─────────────────────────────────────────────────
DEEPSEEK_API_KEY = "***REMOVED***"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL   = "deepseek-reasoner"
PROXY = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB


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


def _build_spec_rows(detail_params: dict, max_rows: int = 12) -> list:
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
        if len(rows) >= max_rows:
            return rows

    for key, value in detail_params.items():
        k = _to_str(key)
        v = _to_str(value)
        if not k or not v or k in used:
            continue
        rows.append({"name": k, "value": v})
        if len(rows) >= max_rows:
            break

    return rows


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

    specs = _build_spec_rows(detail_params, max_rows=12)

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
    _cat = _to_str(parsed.get("category_line", ""))

    return {
        "brand_text": brand_text,
        "model_name": model,
        "tagline_line1": tagline_line1,
        "tagline_line2": tagline_line2,
        "tagline_sub": sub_slogan,
        "category_line": _cat,
        "main_title": _main,
        "param_1_label": "工作效率", "param_1_value": param_efficiency,
        "param_2_label": "清洗宽度", "param_2_value": param_width,
        "param_3_label": "清水箱", "param_3_value": param_capacity,
        "param_4_label": "续航时间", "param_4_value": param_runtime,
        "e_specs": specs,
        "e_dim_length": dim_length,
        "e_dim_width": dim_width,
        "e_dim_height": dim_height,
    }


# ── 配置加载 ─────────────────────────────────────────────────────────

_build_config_cache = {}


def _load_build_config(product_type: str) -> dict:
    if product_type in _build_config_cache:
        return _build_config_cache[product_type]
    cfg_path = TEMPLATES_DIR / product_type / "build_config.json"
    if not cfg_path.exists():
        return {}
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    _build_config_cache[product_type] = cfg
    return cfg


# ── 图片上传工具 ──────────────────────────────────────────────────────

STATIC_UPLOADS = BASE_DIR / "static" / "uploads"
STATIC_UPLOADS.mkdir(parents=True, exist_ok=True)
STATIC_OUTPUTS = BASE_DIR / "static" / "outputs"
STATIC_OUTPUTS.mkdir(parents=True, exist_ok=True)


def _save_upload(file_field_name) -> str:
    """保存上传图片到 static/uploads/，返回 /static/uploads/xxx.ext URL"""
    f = request.files.get(file_field_name)
    if not f or not f.filename:
        return ""
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else "png"
    filename = f"{uuid.uuid4().hex}.{ext}"
    f.save(str(STATIC_UPLOADS / filename))
    return f"/static/uploads/{filename}"


# ── 基础路由 ─────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("build_form_generic", product_type=PRODUCT_TYPE))


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


@app.route("/api/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(str(UPLOAD_DIR), filename)


@app.route("/api/output/<path:filename>")
def serve_output(filename):
    return send_from_directory(str(OUTPUT_DIR), filename)


# ── 文本解析（DeepSeek API）──────────────────────────────────────────

@app.route("/api/parse-text", methods=["POST"])
def parse_text():
    data = request.get_json(silent=True)
    if not data or not data.get("text"):
        return jsonify({"error": "缺少 text 字段"}), 400
    raw_text = data["text"].strip()
    if not raw_text:
        return jsonify({"error": "文本内容为空"}), 400
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            return jsonify(parsed)
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        result = _call_deepseek_parse(raw_text)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"AI 解析失败: {e}"}), 500


def _call_deepseek_parse(raw_text: str) -> dict:
    import requests as req
    resp = req.post(
        DEEPSEEK_API_URL,
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
        json={
            "model": DEEPSEEK_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "你是产品数据解析助手，把用户提供的产品信息提取为标准JSON格式"
                },
                {
                    "role": "user",
                    "content": (
                        "请把以下产品数据解析为JSON，字段包括：brand, brand_en, product_name, model, "
                        "product_type（清洁设备类型）, slogan, sub_slogan, "
                        "detail_params（所有技术参数的完整键值对dict，如清洗宽度/清扫作业宽度/清水容量/"
                        "工作效率/续航时间/电池容量/整机重量/产品尺寸等）, "
                        "advantages(数组,最多6个), dimensions(length/width/height)。"
                        "只返回JSON，不要其他文字：\n\n" + raw_text
                    )
                }
            ],
            "temperature": 0.1,
        },
        proxies=PROXY,
        timeout=120,
    )
    resp.raise_for_status()
    msg = resp.json()["choices"][0]["message"]
    raw = (msg.get("content") or "").strip()

    if "```" in raw:
        m = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
        if m:
            raw = m.group(1).strip()

    if not raw.startswith("{"):
        start = raw.find("{")
        if start != -1:
            raw = raw[start:]

    return json.loads(raw.strip())


@app.route("/api/build/<product_type>/parse-text", methods=["POST"])
def parse_text_for_build(product_type):
    data = request.get_json(silent=True)
    if not data or not data.get("text"):
        return jsonify({"error": "缺少 text 字段"}), 400

    raw_text = _to_str(data.get("text"))
    if not raw_text:
        return jsonify({"error": "文本内容为空"}), 400

    parsed = _extract_json_object(raw_text)
    if not isinstance(parsed, dict):
        parsed = _parse_text_by_template(raw_text)
    if not isinstance(parsed, dict) or not parsed:
        try:
            parsed = _call_deepseek_parse(raw_text)
        except Exception as e:
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
    product_image    = _save_upload('product_image')
    scene_image      = _save_upload('scene_image')
    product_side_image = _save_upload('product_side_image')
    logo_image       = _save_upload('logo_image')

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
    for i in range(1, 13):
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

    # ── blocks_hardcoded（从配置读）──
    blocks_hc = cfg.get("blocks_hardcoded", {})

    # ── Block B3（清洁故事）— 产品图注入 ──
    block_b3 = dict(blocks_hc.get("block_b3", {}))
    if not (block_b3.get("hero_image") or "").strip():
        block_b3["hero_image"] = product_image

    # ── Block F（1台顶8人）— 图片注入 ──
    block_f = dict(blocks_hc.get("block_f", {}))
    block_f["bg_image"] = scene_image
    block_f["product_image"] = product_image

    # ── 固定卖点图 ──
    fixed_selling_images = [
        f"/static/{product_type}/{fname}"
        for fname in cfg.get("fixed_selling_images", [])
    ]

    data = {
        "product_type": product_type,
        "block_a": block_a,
        "block_b2": blocks_hc.get("block_b2", {}),
        "block_b3": block_b3,
        "block_f": block_f,
        "block_e": block_e,
        "fixed_selling_images": fixed_selling_images,
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
            "cover_image": f"/static/{PRODUCT_TYPE}/ref_dz50x_cover.png",
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
    }
    return render_template(f"{PRODUCT_TYPE}/assembled.html", **data)


# ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  物保云产品详情页生成器 - Web UI")
    print("=" * 50)
    print(f"  入口: http://localhost:5000/build/{PRODUCT_TYPE}")
    print(f"  预览: http://localhost:5000/preview/{PRODUCT_TYPE}")
    print("=" * 50)
    app.run(debug=True, port=5000, use_reloader=False)
