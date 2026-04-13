"""
小玺AI产品详情页生成器 - Web 后端（设备类专用）
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
from dotenv import load_dotenv

# 加载 .env 文件（本地开发用，生产环境靠系统环境变量）
load_dotenv(Path(__file__).parent / ".env")

import threading
from flask import Flask, request, jsonify, send_file, render_template, redirect, url_for, abort, flash
from flask_login import login_required, current_user
from flask_wtf.csrf import CSRFProtect

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
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL   = "deepseek-chat"
_proxy_url = os.environ.get("HTTP_PROXY", "").strip()
PROXY = {"http": _proxy_url, "https": _proxy_url} if _proxy_url else {}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
_secret_key = os.environ.get("SECRET_KEY", "")
if not _secret_key and os.environ.get("FLASK_ENV") != "development":
    print("[警告] 未设置 SECRET_KEY 环境变量，使用开发默认值（生产环境请务必设置）")
app.config["SECRET_KEY"] = _secret_key or "dev-change-me-in-production"
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///wubaoyun.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# ── 初始化扩展 ──
from extensions import db, login_manager, migrate
from models import User, GenerationLog

csrf = CSRFProtect(app)
db.init_app(app)
login_manager.init_app(app)
migrate.init_app(app, db)

@login_manager.user_loader
def _load_user(user_id):
    return db.session.get(User, int(user_id))

# ── product_type 白名单校验（防止路径遍历）──
ALLOWED_PRODUCT_TYPES = {"设备类", "耗材类", "配耗类", "工具类"}

def _validate_product_type(product_type):
    if product_type not in ALLOWED_PRODUCT_TYPES:
        abort(404, f"不支持的产品类型: {product_type}")

# ── 全局请求钩子：更新活跃时间 + 拦截未审核用户 ──
from datetime import datetime as _dt

@app.before_request
def _before_request():
    if current_user.is_authenticated:
        # 更新最后活跃时间（每次请求写一次太频繁，改为5分钟更新一次）
        now = _dt.utcnow()
        if not current_user.last_active or (now - current_user.last_active).total_seconds() > 300:
            current_user.last_active = now
            db.session.commit()
        # 未审核用户只能访问 auth 相关页面
        if not current_user.is_approved and request.endpoint and not request.endpoint.startswith("auth.") and request.endpoint != "static":
            from flask import render_template_string
            return render_template_string("""
<!DOCTYPE html><html><head><meta charset="UTF-8"><title>等待审核</title>
<style>body{font-family:"Microsoft YaHei",sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#f5f5f5;}
.card{background:#fff;padding:40px;border-radius:16px;text-align:center;max-width:400px;box-shadow:0 4px 20px rgba(0,0,0,0.1);}
h2{color:#333;margin-bottom:12px;} p{color:#666;font-size:14px;line-height:1.6;}
a{color:#E8231A;text-decoration:none;font-size:14px;display:inline-block;margin-top:16px;}</style></head>
<body><div class="card"><h2>&#x23F3; 账号审核中</h2><p>您的账号正在等待管理员审核<br>审核通过后即可正常使用所有功能</p>
<a href="{{ url_for('auth.logout') }}">退出登录</a></div></body></html>
            """), 200


@app.after_request
def _no_cache(response):
    """禁止浏览器缓存 HTML/JSON，静态资源允许缓存"""
    ct = response.content_type or ""
    if "text/html" in ct or "application/json" in ct:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# ── rembg 可用性检测（懒加载，避免启动时占满内存） ──
REMBG_SESSION = None
REMBG_AVAILABLE = False
_rembg_loaded = False
_rembg_lock = threading.Lock()

def _ensure_rembg():
    """首次抠图时才加载模型，减少启动内存占用"""
    global REMBG_SESSION, REMBG_AVAILABLE, _rembg_loaded
    if _rembg_loaded:
        return REMBG_AVAILABLE
    with _rembg_lock:
        if _rembg_loaded:
            return REMBG_AVAILABLE
        _rembg_loaded = True
        try:
            from rembg import new_session
            REMBG_SESSION = new_session("isnet-general-use")
            REMBG_AVAILABLE = True
            print("[rembg] 模型加载成功，产品图将自动抠图")
        except Exception as e:
            REMBG_AVAILABLE = False
            print(f"[rembg] 模型加载失败（{e}），产品图将保留原背景")
    return REMBG_AVAILABLE

# 仅检测是否安装，不加载模型
try:
    import rembg as _rembg_check
    REMBG_AVAILABLE = True
    print("[启动] rembg 已安装，首次抠图时加载模型")
except ImportError:
    print("[启动] rembg 未安装，产品图将保留原背景")


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

    return rows


def _append_unit(val: str, unit: str = "mm") -> str:
    """给纯数字维度值追加单位后缀"""
    if val and val.replace(".", "").isdigit():
        return val + unit
    return val


def _strip_extreme_in_list(items, fields):
    """批量过滤列表中每个 dict 指定字段的极限词"""
    for item in items:
        if isinstance(item, dict):
            for f in fields:
                if f in item:
                    item[f] = _strip_extreme_words(_to_str(item[f]))


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
    _main = _first_nonempty(
        _to_str(parsed.get("main_title", "")),
        _pn,
        f"{brand} {model}".strip() if (brand or model) else "",
    )
    _cat = _first_nonempty(
        _to_str(parsed.get("category_line", "")),
        _to_str(parsed.get("product_type", "")),
    )
    _hero_sub = _to_str(parsed.get("hero_subtitle", ""))
    # 如果 AI 没返回标语，尝试用品类补位
    if not slogan and _cat:
        slogan = f"高效{_cat}"
        tagline_line1, tagline_line2 = _split_slogan(slogan)
    # 最终兜底：确保首屏至少有产品名
    if not _main and not _cat:
        _cat = product_type_str or "商用清洁设备"
    if not _main:
        _main = _cat

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
        "e_dim_length": _append_unit(dim_length),
        "e_dim_width": _append_unit(dim_width),
        "e_dim_height": _append_unit(dim_height),
    }

    # ── 产品优势（仅用AI返回的，不兜底推导）──
    advantages = parsed.get("advantages", [])
    if advantages:
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
        result["b2_subtitle"] = ""
    # 如果AI没返回advantages，不设置b2字段，模块将不显示

    # ── 清洁故事文案（AI生成）──
    result["b3_header_line1"] = _to_str(parsed.get("story_title_1", ""))
    result["b3_header_line2"] = _to_str(parsed.get("story_title_2", ""))
    result["b3_caption_line1"] = _to_str(parsed.get("story_desc_1", ""))
    result["b3_caption_line2"] = _to_str(parsed.get("story_desc_2", ""))
    result["b3_footer_line1"] = _to_str(parsed.get("story_bottom_1", ""))
    result["b3_footer_line2"] = _to_str(parsed.get("story_bottom_2", ""))

    # ── VS对比文案（仅当AI有实际数据时才填充）──
    vs = parsed.get("vs_comparison", {})
    if isinstance(vs, dict) and vs:
        count_num = _to_str(vs.get("replace_count", ""))
        left_title = _to_str(vs.get("left_title", ""))
        left_bottom = _to_str(vs.get("left_bottom", ""))
        # 只有AI返回了实质数据才生成VS模块
        if count_num or left_title or left_bottom:
            result["f_title_line1"] = "1台顶" if count_num else ""
            result["f_title_line1_red"] = count_num
            result["f_title_line1_end"] = "人" if count_num else ""
            result["f_title_line2"] = left_title + "与人工" if left_title else ""
            result["f_title_line2_red"] = "的区别。" if left_title else ""
            result["f_vs_left_title"] = left_title
            result["f_vs_left_sub"] = _to_str(vs.get("left_sub", ""))
            result["f_vs_right_title"] = _to_str(vs.get("right_title", "")) or ("传统人工" if left_title else "")
            result["f_vs_right_sub"] = _to_str(vs.get("right_sub", ""))
            result["f_vs_left_bottom"] = left_bottom
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
        "tech_items":    "block_j_json",
        "faqs":          "block_s_json",
        "cert_badges":   "block_k_json",
    }
    for src_key, dest_key in _list_field_map.items():
        val = parsed.get(src_key)
        if isinstance(val, list) and val:
            result[dest_key] = json.dumps(val, ensure_ascii=False)
    # install_steps / usage_steps 合并为 block_m_json
    steps = parsed.get("install_steps") or parsed.get("usage_steps")
    if isinstance(steps, list) and steps:
        result["block_m_json"] = json.dumps(steps, ensure_ascii=False)

    # ── 品牌数据（brand_stats / brand_story_lines → block_g）──
    _brand_stats = parsed.get("brand_stats", [])
    if isinstance(_brand_stats, list) and _brand_stats:
        result["block_g_stats_json"] = json.dumps(_brand_stats, ensure_ascii=False)
    _brand_lines = parsed.get("brand_story_lines", [])
    if isinstance(_brand_lines, list) and _brand_lines:
        result["block_g_lines_json"] = json.dumps(_brand_lines, ensure_ascii=False)

    # ── 服务对比（service_compare → block_l）──
    _svc = parsed.get("service_compare", {})
    if isinstance(_svc, dict) and _svc.get("compare_rows"):
        result["block_l_json"] = json.dumps(_svc["compare_rows"], ensure_ascii=False)

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


def _user_upload_dir():
    """返回当前用户的上传目录，按 user_id 隔离"""
    uid = current_user.id if current_user.is_authenticated else 0
    d = STATIC_UPLOADS / str(uid)
    d.mkdir(parents=True, exist_ok=True)
    return d

def _user_output_dir():
    """返回当前用户的输出目录，按 user_id 隔离"""
    uid = current_user.id if current_user.is_authenticated else 0
    d = OUTPUT_DIR / str(uid)
    d.mkdir(parents=True, exist_ok=True)
    return d

def _save_upload(file_field_name, auto_rembg: bool = False) -> str:
    """保存上传图片到 static/uploads/{user_id}/，返回 URL
    auto_rembg=True 时对白底产品图自动抠图（只处理 product_image）
    """
    f = request.files.get(file_field_name)
    if not f or not f.filename:
        return ""
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else "png"
    uid = uuid.uuid4().hex
    user_dir = _user_upload_dir()
    filename = f"{uid}.{ext}"
    save_path = user_dir / filename
    f.save(str(save_path))

    if auto_rembg and _ensure_rembg():
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
                nobg_path = user_dir / nobg_filename
                result_img.save(str(nobg_path))
                print(f"[抠图] 完成 → {nobg_filename}", flush=True)
                return f"/static/uploads/{current_user.id}/{nobg_filename}"
        except Exception as e:
            import traceback
            print(f"[抠图] 失败，使用原图: {e}", flush=True)
            traceback.print_exc()
    elif auto_rembg and not REMBG_AVAILABLE:
        print(f"[抠图] rembg 未安装，跳过 {filename}。运行: pip install rembg onnxruntime", flush=True)

    return f"/static/uploads/{current_user.id}/{filename}"


# ── 基础路由 ─────────────────────────────────────────────────────────

_CATEGORIES = [
    {"type": "设备类", "desc": "商用清洁机器人、洗地机、扫地车等大型设备", "color": "#E8231A", "icon": "🤖"},
    {"type": "配耗类", "desc": "刷盘、滤芯、吸水胶条等设备配件", "color": "#1E6FBF", "icon": "🔧"},
    {"type": "耗材类", "desc": "清洁剂、除垢液、清洁垫等消耗品", "color": "#2E8B57", "icon": "🧪"},
    {"type": "工具类", "desc": "拖把、刮水器、清洁桶等手动工具", "color": "#E87C1A", "icon": "🧹"},
]

@app.route('/api/themes', methods=['GET'])
@login_required
def get_themes():
    """返回所有可用模板的配置（含CSS变量）"""
    themes_path = BASE_DIR / "static" / "themes" / "themes.json"
    with open(themes_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return jsonify(data)


@app.route("/")
@login_required
def index():
    return render_template("workspace.html")


@app.route("/workspace/<product_type>")
@login_required
def build_redirect(product_type):
    _validate_product_type(product_type)
    return render_template("workspace.html", initial_product_type=product_type)


# ── 用户设置页 ──
@app.route("/settings", methods=["GET", "POST"])
@login_required
def user_settings():
    from crypto_utils import encrypt_api_key
    has_custom_key = bool(current_user.custom_api_key_enc)

    if request.method == "POST":
        new_key = request.form.get("custom_api_key", "").strip()
        if new_key:
            current_user.custom_api_key_enc = encrypt_api_key(new_key)
            db.session.commit()
            flash("API Key 已保存", "success")
        elif not new_key and has_custom_key:
            pass  # 空提交不清除已有 Key
        return redirect(url_for("user_settings"))

    return render_template("auth/settings.html", has_custom_key=has_custom_key)


def _get_user_api_key():
    """获取当前用户应使用的 API Key，返回 (key, source)
    source: 'custom' | None
    所有用户（含管理员）均需自行配置 Key
    """
    from crypto_utils import decrypt_api_key
    if current_user.custom_api_key_enc:
        try:
            key = decrypt_api_key(current_user.custom_api_key_enc)
            if key:
                return key, "custom"
        except Exception:
            pass
    return None, None


@app.route("/api/upload", methods=["POST"])
@login_required
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
    user_dir = _user_upload_dir()
    save_path = user_dir / filename
    file.save(str(save_path))
    return jsonify({"path": str(save_path), "filename": filename, "url": f"/static/uploads/{current_user.id}/{filename}"})
# ── 文本解析（DeepSeek API）──────────────────────────────────────────
_NO_FABRICATION_RULE = (
    "【数据准确性要求】\n"
    "1. advantages 中的每一条必须能在用户提供的文案中找到依据，没有依据不要写。\n"
    "2. 如果文案中没有明确提到APP/云平台/智能导航等功能，不要在advantages中包含这些。\n"
    "3. 【最重要】detail_params 必须完整提取文案中的每一个参数，一个都不能遗漏！\n"
    "   包括但不限于：效率、宽度、容量、功率、电机、电池、重量、尺寸、噪音、转速、\n"
    "   吸力、压力、速度、材质、充电时间、续航时间等所有出现的技术数据。\n"
    "   用户给了多少参数就提取多少，不要截断、不要省略、不要合并。\n"
    "4. floor_items（适用地面）：只根据产品实际用途判断，如果无法确定就返回空数组。\n"
    "5. vs_comparison 中的数字（替代人数、节省金额）必须有文案依据，没有依据就留空。\n"
    "6. story_title/story_desc：必须用文案中的真实参数数据，不能编造数字。\n"
    "7. 售后承诺、质保年限等：只有文案中明确写了才能填，没写的一律不填。\n"
    "8. 不要编造用户文案中没有提到的服务承诺（如送货上门、上门培训等）。\n\n"
)

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
            + _NO_FABRICATION_RULE
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
            '  ],\n'
            '  "listing_title": "电商标题（60字以内，含品牌+型号+核心卖点+品类词）",\n'
            '  "listing_keywords": "搜索关键词（10-15个，逗号分隔）",\n'
            '  "listing_selling_points": ["卖点1（15字以内）","卖点2","卖点3","卖点4","卖点5"],\n'
            '  "listing_description": "商品描述（200字以内，适合电商详情页顶部）",\n'
            '  "spec_callouts": [{"label":"参数名","value":"参数值"},...]\n'
            "}\n"
            "```\n\n"
            "【重要提示】\n"
            "- 识别文案中提到的所有兼容机型，填入 compat_models（多列出，不要遗漏）\n"
            "- install_steps 提供清晰的安装步骤（3-6步）\n"
            "- package_items 列出包装内所有配件清单\n"
            "- advantages 6-9项，每项附带贴切的emoji，严禁编造\n"
            "- listing_title 要包含核心搜索词，便于电商平台搜索\n"
            "- spec_callouts 从参数中提取3-6个最吸引眼球的数据，用于主图标注\n\n"
            "只返回JSON，不要其他解释文字：\n\n" + raw_text
        )

    elif product_type == "耗材类":
        return (
            "你是一个清洁耗材营销文案专家。请根据以下产品参数，完成两件事：\n\n"
            "第一，提取所有技术参数（型号、规格、成分、稀释比等）填入对应字段。\n"
            "第二，根据这些参数生成营销文案（严格基于真实数据，不得编造产品没有的功能）。\n\n"
            + _NO_FABRICATION_RULE
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
            '  ],\n'
            '  "listing_title": "电商标题（60字以内，含品牌+型号+核心卖点+品类词）",\n'
            '  "listing_keywords": "搜索关键词（10-15个，逗号分隔）",\n'
            '  "listing_selling_points": ["卖点1（15字以内）","卖点2","卖点3","卖点4","卖点5"],\n'
            '  "listing_description": "商品描述（200字以内，适合电商详情页顶部）",\n'
            '  "spec_callouts": [{"label":"参数名","value":"参数值"},...]\n'
            "}\n"
            "```\n\n"
            "【重要提示】\n"
            "- 强调安全性（是否食品级、是否需要防护）\n"
            "- kpis 列出稀释比、覆盖面积、每升成本等关键指标\n"
            "- usage_steps 提供清晰的使用步骤（3-5步）\n"
            "- before_after 描述使用前后的清洁效果对比\n"
            "- advantages 6-9项，每项附带贴切的emoji，严禁编造\n"
            "- listing_title 要包含核心搜索词，便于电商平台搜索\n"
            "- spec_callouts 从参数中提取3-6个最吸引眼球的数据，用于主图标注\n\n"
            "只返回JSON，不要其他解释文字：\n\n" + raw_text
        )

    elif product_type == "工具类":
        return (
            "你是一个清洁工具营销文案专家。请根据以下产品参数，完成两件事：\n\n"
            "第一，提取所有技术参数（型号、材质、规格等）填入对应字段。\n"
            "第二，根据这些参数生成营销文案（严格基于真实数据，不得编造产品没有的功能）。\n\n"
            + _NO_FABRICATION_RULE
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
            '  ],\n'
            '  "listing_title": "电商标题（60字以内，含品牌+型号+核心卖点+品类词）",\n'
            '  "listing_keywords": "搜索关键词（10-15个，逗号分隔）",\n'
            '  "listing_selling_points": ["卖点1（15字以内）","卖点2","卖点3","卖点4","卖点5"],\n'
            '  "listing_description": "商品描述（200字以内，适合电商详情页顶部）",\n'
            '  "spec_callouts": [{"label":"参数名","value":"参数值"},...]\n'
            "}\n"
            "```\n\n"
            "【重要提示】\n"
            "- 强调材质品质和耐用寿命\n"
            "- scenes 列出适用场景（3-6个），如商场、医院、学校、工厂等\n"
            "- package_items 列出包装内所有配件清单\n"
            "- before_after 描述使用前后的清洁效果对比\n"
            "- advantages 6-9项，每项附带贴切的emoji，严禁编造\n"
            "- listing_title 要包含核心搜索词，便于电商平台搜索\n"
            "- spec_callouts 从参数中提取3-6个最吸引眼球的数据，用于主图标注\n\n"
            "只返回JSON，不要其他解释文字：\n\n" + raw_text
        )

    else:
        # 设备类（默认）
        return (
            "你是一个清洁设备营销文案专家。请根据以下产品参数，完成两件事：\n\n"
            "第一，提取所有技术参数（型号、尺寸、功率等）填入对应字段。\n"
            "第二，根据这些参数生成营销文案（严格基于真实数据，不得编造产品没有的功能）。\n\n"
            + _NO_FABRICATION_RULE
            + _EXTREME_WORDS_RULE +
            "返回以下JSON格式（所有字段必须返回，不要遗漏）：\n"
            "```json\n"
            "{\n"
            '  "brand": "品牌中文名",\n'
            '  "brand_en": "品牌英文名",\n'
            '  "product_name": "产品全称",\n'
            '  "model": "型号",\n'
            '  "product_type": "设备中文类型（如驾驶式扫地车）",\n'
            '  "detail_params": {"参数名":"参数值", ...},\n'
            '  // ⚠️ detail_params 必须提取文案中出现的【每一个】技术参数，不限数量，不能遗漏任何一个！\n'
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
            '  },\n'
            '  "tech_items": [\n'
            '    {"title":"技术/部件名称（如 感应电机）","desc":"一句话技术说明（如 高效稳定，适配长时间作业）"}\n'
            '  ],\n'
            '  // ⚠️ tech_items: 从文案提取4-8项核心技术特征/部件/卖点详解，每项必须有原文依据。没有则返回空数组\n'
            '  "brand_stats": [\n'
            '    {"value":"数值（如 200+）","label":"指标名（如 服务城市）"}\n'
            '  ],\n'
            '  // brand_stats: 提取品牌数字指标（如城市数、客户数、行业年限），没有则返回空数组\n'
            '  "brand_story_lines": [\n'
            '    {"year":"年份","text":"里程碑事件"}\n'
            '  ],\n'
            '  // brand_story_lines: 提取品牌历史里程碑，没有则返回空数组\n'
            '  "scenes": [{"name":"场景名","desc":"一句话描述"}],\n'
            '  // scenes: 从文案提取适用场景（如商场、医院、工厂），没有则返回空数组\n'
            '  "kpis": [{"number":"数字+单位","label":"指标说明"}],\n'
            '  // kpis: 从文案提取关键效率数据（如1368㎡/h、3.5h续航），没有则返回空数组\n'
            '  "faqs": [\n'
            '    {"question":"买家常见问题","answer":"基于文案数据的简洁回答（30字以内）"}\n'
            '  ],\n'
            '  // faqs: 根据已提取参数生成3-5个常见问题，answer必须引用文案真实数据，不可编造。无依据则返回空数组\n'
            '  "service_compare": {\n'
            '    "compare_rows": [\n'
            '      {"label":"对比维度（如 质保时长）","left":"官方优势（如 整机2年）","right":"普通商家（如 无保障）"}\n'
            '    ]\n'
            '  },\n'
            '  // service_compare: 生成3-5行官方vs普通商家服务对比，没有售后信息则返回空对象{}\n'
            '  "cert_badges": [\n'
            '    {"title":"认证名称（如 CE认证）","desc":"简短说明"}\n'
            '  ],\n'
            '  // cert_badges: 从文案提取资质认证（如CE/FCC/IEC/ISO），没有则返回空数组\n'
            '  "listing_title": "电商标题（60字以内，含品牌+型号+核心卖点+品类词，如：XX品牌DZ50X商用驾驶式洗地机 大型商场工厂用全自动清洗机器人）",\n'
            '  "listing_keywords": "搜索关键词（10-15个，逗号分隔，如：洗地机,驾驶式洗地机,商用清洁机器人,...）",\n'
            '  "listing_selling_points": ["卖点1（15字以内）","卖点2","卖点3","卖点4","卖点5"],\n'
            '  "listing_description": "商品描述（200字以内，适合电商详情页顶部，突出核心参数和应用场景）",\n'
            '  "spec_callouts": [{"label":"清扫宽度","value":"1800mm"},{"label":"续航","value":"6小时"},...]  \n'
            "}\n"
            "```\n\n"
            "【advantages规则】\n"
            "- 严格从用户提供的产品文案中提取，每一条必须有原文依据\n"
            "- 如果文案只提到了3个卖点，就只返回3个，不要凑数\n"
            "- 绝对不要添加文案中没有的功能（如：文案没提APP就不能写智慧管理）\n"
            "- 每项2-6个字，附带一个贴切的emoji\n\n"
            "【tech_items 与 advantages 的区别】\n"
            "- advantages 是用户感知的卖点短语（如\"超宽清扫\"），2-6字，附emoji\n"
            "- tech_items 是技术实现细节（如\"感应电机\"），含标题+一句话技术说明\n"
            "- 两者可能描述同一特性的不同角度，这是正常的\n\n"
            "【扩展字段规则】\n"
            "- tech_items/scenes/kpis/cert_badges: 严格从文案提取，文案没提到就返回空数组\n"
            "- faqs: 可基于已提取的参数和卖点合理推导，但answer只能引用文案中的真实参数\n"
            "- brand_stats/brand_story_lines: 仅当文案包含品牌信息时提取，否则返回空数组\n"
            "- service_compare: 可基于产品特性合理推导官方优势，没有售后信息则返回空对象{}\n"
            "- 以上Tier 1字段（tech_items/brand_stats/brand_story_lines/scenes/kpis/cert_badges）必须返回，即使为空数组\n"
            "- Tier 2字段（faqs/service_compare）为补充字段，token不足时可省略\n\n"
            "【detail_params规则 — 最高优先级】\n"
            "- 用户文案中出现的每一个技术参数都必须提取到detail_params中\n"
            "- 不要截断、不要省略、不要合并，有多少写多少\n"
            "- 参数名使用文案中的原始名称，不要改写\n\n"
            "【电商文案规则】\n"
            "- listing_title 要包含核心搜索词，便于电商平台搜索\n"
            "- listing_selling_points 每条15字以内，突出差异化\n"
            "- spec_callouts 从参数中提取3-6个最吸引眼球的数据，用于主图标注\n\n"
            "只返回JSON，不要其他解释文字：\n\n" + raw_text
        )


def _call_deepseek_parse(raw_text: str, product_type: str = "设备类", api_key: str = "") -> dict:
    """调用 DeepSeek API，一次完成：解析产品参数 + 生成营销文案"""
    import requests as req
    use_key = api_key or DEEPSEEK_API_KEY
    if not use_key:
        raise ValueError("未配置 API Key，无法调用 AI 服务")
    prompt = _build_category_prompt(product_type, raw_text)
    print(f"[DeepSeek] 发送请求，文本长度={len(raw_text)}...")
    resp = req.post(
        DEEPSEEK_API_URL,
        headers={"Authorization": f"Bearer {use_key}"},
        json={
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": "你是清洁设备营销文案专家。解析产品参数并生成营销文案。只返回JSON。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 8192,
        },
        proxies={"http": None, "https": None},  # DeepSeek 国内API，不走代理
        timeout=180,
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

    # ── 新增字段极限词过滤 ──
    _strip_extreme_in_list(parsed.get("tech_items", []), ["title", "desc"])
    _strip_extreme_in_list(parsed.get("brand_stats", []), ["label"])
    _strip_extreme_in_list(parsed.get("brand_story_lines", []), ["text"])
    _strip_extreme_in_list(parsed.get("faqs", []), ["answer"])
    _svc = parsed.get("service_compare", {})
    if isinstance(_svc, dict):
        _strip_extreme_in_list(_svc.get("compare_rows", []), ["left", "right"])

    # ── 退化检测：Tier 1 must-extract 字段完整性 ──
    _dp = parsed.get("detail_params", {})
    _adv = parsed.get("advantages", [])
    _warnings = []
    if isinstance(_dp, dict) and len(_dp) < 3:
        _warnings.append(f"detail_params={len(_dp)}项（期望>=3）")
    if isinstance(_adv, list) and len(_adv) < 2:
        _warnings.append(f"advantages={len(_adv)}项（期望>=2）")
    if not parsed.get("slogan", "").strip():
        _warnings.append("slogan为空")
    if not parsed.get("story_title_1", "").strip():
        _warnings.append("story_title_1为空")
    if _warnings:
        print(f"[DeepSeek] ⚠️ Tier 1 退化警告: {'; '.join(_warnings)}")

    return parsed


def _derive_advantages_from_specs(detail_params: dict) -> list:
    """兜底：当 AI 不返回 advantages 时，从参数规格用中性词推导。
    注意：主流程已改为只用AI返回的advantages，此函数仅作极端降级。"""
    if not isinstance(detail_params, dict) or not detail_params:
        return []
    mapping = [
        (["清扫宽度", "清扫作业宽度"], "🧹", "清扫功能"),
        (["工作效率", "清洁效率", "最大清洁效率"], "⚡", "清洁效率"),
        (["垃圾箱容量"], "🗑️", "垃圾收集"),
        (["水箱容量", "清水容量"], "💧", "水箱配备"),
        (["爬坡能力"], "⛰️", "爬坡能力"),
        (["制动方式"], "🛑", "制动系统"),
        (["电池容量", "电瓶容量", "锂电容量"], "🔋", "电池续航"),
        (["连续工作时间", "工作时间", "续航时间"], "⏱️", "续航能力"),
        (["清洗宽度", "吸水宽度"], "🧽", "洗地功能"),
    ]
    items = []
    used = set()
    for keys, emoji, text in mapping:
        for k in keys:
            if detail_params.get(k) and k not in used:
                items.append({"emoji": emoji, "text": text})
                used.add(k)
                break
        if len(items) >= 6:
            break
    return items
@app.route("/api/build/<product_type>/parse-text", methods=["POST"])
@login_required
@csrf.exempt
def parse_text_for_build(product_type):
    _validate_product_type(product_type)
    data = request.get_json(silent=True)
    if not data or not data.get("text"):
        return jsonify({"error": "缺少 text 字段"}), 400

    raw_text = _to_str(data.get("text"))
    if not raw_text:
        return jsonify({"error": "文本内容为空"}), 400

    # 如果用户提供了产品标题，拼入文案顶部增强 AI 识别
    product_title = _to_str(data.get("product_title", ""))
    if product_title:
        raw_text = f"【产品标题】{product_title}\n\n{raw_text}"

    # 检查用户是否有 API Key 可用
    api_key, key_source = _get_user_api_key()
    if not api_key:
        return jsonify({"error": "请先在「账号设置」中配置您的 DeepSeek API Key"}), 403

    # 直接调 DeepSeek —— 必须用 AI 才能生成 advantage_labels 和 clean_story
    try:
        parsed = _call_deepseek_parse(raw_text, product_type, api_key=api_key)
    except Exception as e:
        import traceback
        print(f"[DeepSeek] ❌ API调用失败: {e}")
        traceback.print_exc()
        # DeepSeek 失败时降级到模板解析（不含卖点生成）
        parsed = _extract_json_object(raw_text)
        if not isinstance(parsed, dict):
            parsed = _parse_text_by_template(raw_text)
        if not isinstance(parsed, dict) or not parsed:
            return jsonify({"error": f"AI 解析失败: {e}"}), 500
        print(f"[DeepSeek] ⚠️ 降级到模板解析，字段: {list(parsed.keys())[:10]}")

    # 记录生成日志
    log = GenerationLog(
        user_id=current_user.id,
        product_type=product_type,
        model_name=parsed.get("model", ""),
        api_key_source=key_source,
        action="ai_parse",
    )
    db.session.add(log)
    db.session.commit()

    # 完整 AI 返回调试
    import pprint
    _debug_keys = ["brand","brand_en","model","product_name","product_type","slogan","sub_slogan",
                   "category_line","hero_subtitle","main_title","advantages","vs_comparison",
                   "story_title_1","tech_items","scenes","kpis","faqs","cert_badges"]
    _debug_out = {k: parsed.get(k, '(缺失)') for k in _debug_keys}
    _dp = parsed.get("detail_params", {})
    _debug_out["detail_params_count"] = len(_dp)
    print(f"[AI完整返回] {_debug_out}")
    print(f"[AI参数明细] {dict(list(_dp.items())[:30]) if isinstance(_dp, dict) else _dp}")

    # 如果 AI 没返回 brand/model/product_name，用产品标题兜底
    if product_title:
        if not parsed.get("product_name"):
            parsed["product_name"] = product_title
        if not parsed.get("main_title"):
            parsed["main_title"] = product_title
    mapped = _map_parsed_to_form_fields(parsed)
    return jsonify(mapped)


# ── AI 生图（通义万相）─────────────────────────────────────────────

@app.route("/api/generate-ai-images", methods=["POST"])
@login_required
@csrf.exempt
def generate_ai_images():
    """
    AI 生图 API：根据产品数据生成完整详情图集
    输入：parsed_data（DeepSeek解析结果）、product_image（产品图URL）
    输出：生成的图片URL列表
    """
    import ai_image
    import image_composer

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "缺少请求数据"}), 400

    parsed_data = data.get("parsed_data", {})
    product_image_url = data.get("product_image", "")

    # 阿里云百炼 API Key（优先用户配置，否则用环境变量）
    dashscope_key = data.get("dashscope_api_key", "")
    if not dashscope_key:
        dashscope_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not dashscope_key and hasattr(current_user, 'dashscope_api_key_enc') and current_user.dashscope_api_key_enc:
        from crypto_utils import decrypt_api_key
        dashscope_key = decrypt_api_key(current_user.dashscope_api_key_enc)
    if not dashscope_key:
        return jsonify({"error": "请提供阿里云百炼 API Key（DASHSCOPE_API_KEY）"}), 403

    # 准备输出目录
    user_out = _user_output_dir()
    ai_dir = user_out / "ai_images"
    ai_dir.mkdir(parents=True, exist_ok=True)

    # 解析产品图本地路径
    product_image_local = ""
    if product_image_url:
        # /static/uploads/1/xxx.png → static/uploads/1/xxx.png
        rel = product_image_url.lstrip("/")
        local_path = BASE_DIR / rel
        if local_path.exists():
            product_image_local = str(local_path)

    # 构建合成所需的产品数据
    product_data = {}
    if parsed_data:
        mapped = _map_parsed_to_form_fields(parsed_data)
        product_data = {
            "brand": _to_str(parsed_data.get("brand", "")),
            "brand_text": mapped.get("brand_text", ""),
            "model_name": mapped.get("model_name", ""),
            "model": _to_str(parsed_data.get("model", "")),
            "product_name": _to_str(parsed_data.get("product_name", "")),
            "product_type": _to_str(parsed_data.get("product_type", "")),
            "category_line": mapped.get("category_line", ""),
            "tagline_line1": mapped.get("tagline_line1", ""),
            "tagline_line2": mapped.get("tagline_line2", ""),
            "sub_slogan": mapped.get("tagline_sub", ""),
            "slogan": _to_str(parsed_data.get("slogan", "")),
            "param_1_label": mapped.get("param_1_label", ""),
            "param_1_value": mapped.get("param_1_value", ""),
            "param_2_label": mapped.get("param_2_label", ""),
            "param_2_value": mapped.get("param_2_value", ""),
            "param_3_label": mapped.get("param_3_label", ""),
            "param_3_value": mapped.get("param_3_value", ""),
            "param_4_label": mapped.get("param_4_label", ""),
            "param_4_value": mapped.get("param_4_value", ""),
            "detail_params": parsed_data.get("detail_params", {}),
            "dimensions": parsed_data.get("dimensions", {}),
            "specs": mapped.get("e_specs", []),
            "advantages": parsed_data.get("advantages", []),
            # VS对比数据
            "vs_comparison": parsed_data.get("vs_comparison", {}),
            # 清洁故事数据
            "story_title_1": _to_str(parsed_data.get("story_title_1", "")),
            "story_title_2": _to_str(parsed_data.get("story_title_2", "")),
            "story_desc_1": _to_str(parsed_data.get("story_desc_1", "")),
            "story_desc_2": _to_str(parsed_data.get("story_desc_2", "")),
            "story_bottom_1": _to_str(parsed_data.get("story_bottom_1", "")),
            "story_bottom_2": _to_str(parsed_data.get("story_bottom_2", "")),
            "footer_note": "*产品参数以实物为准，图片仅供参考",
        }

    print(f"[AI生图] 开始为 {product_data.get('model_name', '未知')} 生成详情图...")

    # Step 1: 生成AI背景图
    try:
        backgrounds = ai_image.generate_detail_backgrounds(
            product_data, dashscope_key, ai_dir
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[AI生图] 背景生成失败: {e}，使用纯色背景继续")
        backgrounds = {}

    # Step 2: Pillow 合成最终图片
    try:
        output_dir = ai_dir / "final"
        result_paths = image_composer.compose_all(
            product_data, product_image_local, backgrounds, output_dir
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"图片合成失败: {e}"}), 500

    # 转换为URL
    result_urls = []
    for p in result_paths:
        rel_path = Path(p).relative_to(BASE_DIR)
        result_urls.append(f"/{rel_path.as_posix()}")

    print(f"[AI生图] 完成！共 {len(result_urls)} 张图")
    return jsonify({
        "images": result_urls,
        "count": len(result_urls),
    })


# ══════════════════════════════════════════════════════════════════════
# ── 构建系统（设备类，blocks 引擎）──────────────────────────────────
# ══════════════════════════════════════════════════════════════════════

def _assemble_all_blocks(product_type, mapped_fields, images, cfg):
    """
    Assemble all block data from mapped fields and images.
    Returns dict with all block data ready for template rendering.

    mapped_fields: dict from _map_parsed_to_form_fields()
    images: {"product_image": "...", "scene_image": "...", "logo_image": "...", "qr_image": "...", "product_side_image": "", "effect_image": ""}
    cfg: build_config.json contents
    """
    def field(name, default=""):
        v = mapped_fields.get(name, "")
        return v.strip() if v else default

    product_image = images.get("product_image", "")
    scene_image = images.get("scene_image", "")
    logo_image = images.get("logo_image", "")
    qr_image = images.get("qr_image", "")
    product_side_image = images.get("product_side_image", "")
    effect_image = images.get("effect_image", "")

    # Hero params
    hero_params = []
    for i in range(1, 5):
        v = field(f'param_{i}_value', '').strip()
        l = field(f'param_{i}_label', '').strip()
        if v and v not in ('--', '-', '无', 'N/A') and len(v) <= 16:
            hero_params.append({"value": v, "label": l})
    if not hero_params:
        hero_params = [
            {"value": hp.get("default_value", ""), "label": hp.get("label", "")}
            for hp in cfg.get("hero_params", [])
            if hp.get("default_value", "").strip()
        ]

    _hcov = cfg.get("hero_cover_defaults") or {}
    _def = cfg.get("defaults") or {}

    block_a = {
        "brand_text": field('brand_text', _def.get("brand_text", "")),
        "model_name": field('model_name', _def.get("model_name", "")),
        "tagline_line1": field('tagline_line1', _def.get("tagline_line1", "")),
        "tagline_line2": field('tagline_line2', _def.get("tagline_line2", "")),
        "tagline_sub": field('tagline_sub', _def.get("tagline_sub", "")),
        "bg_image": scene_image,
        "product_image": product_image,
        "logo_image": logo_image,
        "category_line": field('category_line', _hcov.get("category_line", "")),
        "main_title": field('main_title', _hcov.get("main_title", "")),
        "hero_subtitle_pre": field('hero_subtitle_pre', _hcov.get("hero_subtitle_pre", "")),
        "hero_subtitle_em": field('hero_subtitle_em', _hcov.get("hero_subtitle_em", "")),
        "hero_subtitle_post": field('hero_subtitle_post', _hcov.get("hero_subtitle_post", "")),
        "footer_note": field('footer_note', _hcov.get("footer_note", "")),
        "cover_image": "",
        "floor_bg_image": scene_image,
        "bg_focal": field('bg_focal', _hcov.get("bg_focal", "center bottom")) or "center bottom",
        "show_hero_params": True,
        "params": hero_params,
    }
    print(f"[block_a调试] brand_text={block_a['brand_text']!r}, model_name={block_a['model_name']!r}, "
          f"main_title={block_a['main_title']!r}, category_line={block_a['category_line']!r}, "
          f"hero_subtitle_pre={block_a['hero_subtitle_pre']!r}, tagline_sub={block_a['tagline_sub']!r}, "
          f"params={len(hero_params)}个")
    print(f"[block_a调试] mapped_fields keys sample: {list(mapped_fields.keys())[:15]}")

    # Block E
    e_specs = []
    # From mapped e_specs list
    raw_specs = mapped_fields.get("e_specs", [])
    if isinstance(raw_specs, list):
        e_specs = [s for s in raw_specs if s.get("name") and s.get("value")]
    # 兜底：AI 未返回参数时，使用配置中的 default_specs
    if not e_specs:
        default_specs = cfg.get("default_specs", [])
        if isinstance(default_specs, list):
            e_specs = [{"name": s.get("name", ""), "value": s.get("value", "")}
                       for s in default_specs if s.get("name") and s.get("value")]

    model_name = field('model_name', _def.get("model_name", ""))
    _e_red = field("e_red_bar_text", "").strip()
    _dims = cfg.get("default_dims", {})
    block_e = {
        "title": "产品参数",
        "subtitle": field("e_table_subtitle", "规格一览"),
        "red_bar_text": _e_red or f"{model_name}创新升级",
        "product_image": product_side_image or product_image,
        "dim_height": field('e_dim_height', _dims.get("height", "")),
        "dim_width": field('e_dim_width', _dims.get("width", "")),
        "dim_length": field('e_dim_length', _dims.get("length", "")),
        "specs": e_specs,
        "footnote": "*人工测量有误差",
    }

    blocks_hc = cfg.get("blocks_hardcoded", {})

    # Block B2
    block_b2_cfg = blocks_hc.get("block_b2", {})
    b2_items = []
    for i in range(1, 10):
        label = field(f"b2_label_{i}", "")
        icon = field(f"b2_icon_{i}", "")
        if label:
            b2_items.append({"icon_image": "", "icon_text": icon or "✅", "label": label})
    if not b2_items:
        b2_items = block_b2_cfg.get("items", [])
    block_b2 = {
        "title_num": field("b2_title_num", "") or block_b2_cfg.get("title_num", str(len(b2_items))),
        "title_text": field("b2_title_text", "") or block_b2_cfg.get("title_text", "大核心优势"),
        "subtitle": field("b2_subtitle", "") or block_b2_cfg.get("subtitle", ""),
        "grid_columns": block_b2_cfg.get("grid_columns", 3),
        "items": b2_items,
    }

    # Block B3
    block_b3 = dict(blocks_hc.get("block_b3", {}))
    for _f in ["header_line1", "header_line2", "caption_line1", "caption_line2", "footer_line1", "footer_line2"]:
        _v = field(f"b3_{_f}", "")
        if _v:
            block_b3[_f] = _v
    if not (block_b3.get("hero_image") or "").strip():
        block_b3["hero_image"] = product_image
    block_b3["effect_image"] = effect_image  # 有效果图时整张顶替"背景+产品图"组合区
    _floor_json = field("b3_floor_items_json", "")
    if _floor_json:
        try:
            _floor_list = json.loads(_floor_json)
            if isinstance(_floor_list, list) and _floor_list:
                block_b3["floor_items"] = _floor_list
        except (json.JSONDecodeError, ValueError):
            pass

    # Block F
    block_f = dict(blocks_hc.get("block_f", {}))
    for _f in ["title_line1", "title_line1_red", "title_line1_end",
                "title_line2", "title_line2_red",
                "vs_left_title", "vs_left_sub", "vs_right_title", "vs_right_sub",
                "vs_left_bottom", "vs_right_bottom"]:
        _v = field(f"f_{_f}", "")
        if _v:
            block_f[_f] = _v
    block_f["product_image"] = product_image

    fixed_selling_images = [
        f"/static/{product_type}/{fname}"
        for fname in cfg.get("fixed_selling_images", [])
    ]

    extra_blocks = {k: dict(cfg.get(k, {})) for k in _EXTRA_BLOCK_KEYS}

    _g_title = field("g_brand_title", "")
    _g_sub = field("g_brand_subtitle", "")
    if _g_title:
        extra_blocks["block_g"]["brand_title"] = _g_title
    if _g_sub:
        extra_blocks["block_g"]["brand_subtitle"] = _g_sub

    if qr_image:
        extra_blocks["block_n"]["qr_image"] = qr_image

    # ── brand_stats / brand_story_lines → block_g ──
    _g_stats_raw = field("block_g_stats_json", "")
    if _g_stats_raw:
        try:
            _g_stats = json.loads(_g_stats_raw)
            if isinstance(_g_stats, list) and _g_stats:
                extra_blocks["block_g"]["brand_stats"] = _g_stats
        except (json.JSONDecodeError, ValueError):
            pass
    _g_lines_raw = field("block_g_lines_json", "")
    if _g_lines_raw:
        try:
            _g_lines = json.loads(_g_lines_raw)
            if isinstance(_g_lines, list) and _g_lines:
                extra_blocks["block_g"]["brand_story_lines"] = _g_lines
        except (json.JSONDecodeError, ValueError):
            pass

    _json_field_map = {
        "block_h_json": ("block_h", "scenes"),
        "block_i_json": ("block_i", "kpis"),
        "block_m_json": ("block_m", "steps"),
        "block_p_json": ("block_p", "compat_models"),
        "block_q_json": ("block_q", "comparisons"),
        "block_r_json": ("block_r", "package_items"),
        "block_j_json": ("block_j", "tech_items"),
        "block_s_json": ("block_s", "faqs"),
        "block_k_json": ("block_k", "badge_items"),
        "block_l_json": ("block_l", "compare_rows"),
    }
    for form_field, (block_key, data_key) in _json_field_map.items():
        _raw = field(form_field, "")
        if _raw:
            try:
                _parsed_val = json.loads(_raw)
                if isinstance(_parsed_val, list) and _parsed_val:
                    extra_blocks[block_key][data_key] = _parsed_val
            except (json.JSONDecodeError, ValueError):
                pass

    return {
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


# Block rendering metadata: block_id → (template_path, display_name)
_BLOCK_REGISTRY = {
    "block_a": ("blocks/block_a_hero_robot_cover.html", "英雄首屏"),
    "block_b2": ("blocks/block_b2_icon_grid.html", "产品优势"),
    "block_b3": ("blocks/block_b3_clean_story.html", "清洁故事"),
    "block_e": ("blocks/block_e_glass_dimension.html", "产品参数"),
    "block_f": ("blocks/block_f_showcase_vs.html", "VS对比"),
    "block_g": ("blocks/block_g_brand_story.html", "品牌背书"),
    "block_h": ("blocks/block_h_scene_grid.html", "适用场景"),
    "block_i": ("blocks/block_i_kpi_strip.html", "效率数据"),
    "block_j": ("blocks/block_j_core_tech.html", "核心技术"),
    "block_k": ("blocks/block_k_cert_badges.html", "资质认证"),
    "block_l": ("blocks/block_l_service_compare.html", "服务对比"),
    "block_m": ("blocks/block_m_steps.html", "使用流程"),
    "block_n": ("blocks/block_n_quote_cta.html", "询价CTA"),
    "block_o": ("blocks/block_o_disclaimer.html", "免责声明"),
    "block_p": ("blocks/block_p_compatibility.html", "适配型号"),
    "block_q": ("blocks/block_q_before_after.html", "效果对比"),
    "block_r": ("blocks/block_r_package_list.html", "包装清单"),
    "block_s": ("blocks/block_s_faq.html", "常见问题"),
    "block_t": ("blocks/block_t_customer_cases.html", "客户案例"),
    "block_u": ("blocks/block_u_after_sales.html", "售后服务"),
    "block_v": ("blocks/block_v_model_compare.html", "型号对比"),
    "block_w": ("blocks/block_w_video_cover.html", "视频封面"),
    "block_x": ("blocks/block_x_durability.html", "实测数据"),
    "block_y": ("blocks/block_y_value_calc.html", "性价比"),
}

# Main image template registry: tpl_id → (template_path, display_name)
_MAIN_IMG_REGISTRY = {
    "main_img_1": ("blocks/main_img_1_white_bg.html", "纯白底"),
    "main_img_2": ("blocks/main_img_2_gradient_hero.html", "渐变标语"),
    "main_img_3": ("blocks/main_img_3_specs_callout.html", "参数标注"),
    "main_img_4": ("blocks/main_img_4_scene_blend.html", "场景融合"),
    "main_img_5": ("blocks/main_img_5_selling_points.html", "卖点矩阵"),
}


# 智能模块匹配：常量表
_BLOCK_ALWAYS_SHOW = {"block_a", "block_e", "block_n", "block_o"}
_BLOCK_LIST_KEYS = {
    "block_b2": "items",
    "block_h": "scenes",
    "block_i": "kpis",
    "block_j": "tech_items",
    "block_k": "badge_items",
    "block_l": "compare_rows",
    "block_m": "steps",
    "block_p": "compat_models",
    "block_q": "comparisons",
    "block_r": "package_items",
    "block_s": "faqs",
    "block_t": "cases",
    "block_u": "promises",
    "block_v": "models",
    "block_x": "metrics",
    "block_y": "items",
}


def _is_block_empty(block_id, block_data):
    """判断模块是否缺少有效数据——没有数据的模块不渲染。"""
    if not block_data or not isinstance(block_data, dict):
        return True
    if block_id in _BLOCK_ALWAYS_SHOW:
        return False
    if block_id in _BLOCK_LIST_KEYS:
        items = block_data.get(_BLOCK_LIST_KEYS[block_id], [])
        return not (isinstance(items, list) and len(items) > 0)

    # 需要特殊判断的模块
    if block_id == "block_b3":
        return not (block_data.get("header_line1", "").strip() or
                    block_data.get("header_line2", "").strip())
    if block_id == "block_f":
        return not (block_data.get("vs_left_bottom", "").strip() or
                    block_data.get("title_line1_red", "").strip())
    if block_id == "block_g":
        return not (block_data.get("brand_title", "").strip() or
                    (block_data.get("brand_stats") and len(block_data["brand_stats"]) > 0) or
                    (block_data.get("brand_story_lines") and len(block_data["brand_story_lines"]) > 0))
    if block_id == "block_w":
        return not block_data.get("video_title", "").strip()

    # 默认：任何非空字符串或非空列表即视为有数据
    return not any(
        (isinstance(v, str) and v.strip()) or (isinstance(v, list) and v)
        for v in block_data.values()
    )


def _render_single_block(block_id, block_data):
    """Render a single block template with its data, return HTML string."""
    reg = _BLOCK_REGISTRY.get(block_id)
    if not reg:
        return ""
    tpl_path, _ = reg
    # block_h: AI 可能返回 title 而非 name，做兼容映射
    if block_id == "block_h" and "scenes" in block_data:
        for s in block_data["scenes"]:
            if "title" in s and "name" not in s:
                s["name"] = s.pop("title")
    try:
        return render_template(tpl_path, **block_data)
    except Exception as e:
        print(f"[渲染] {block_id} 失败: {e}")
        return f'<div style="padding:20px;color:red;">模块 {block_id} 渲染失败: {e}</div>'


def _get_block_display_name(block_id):
    """Get display name for a block."""
    reg = _BLOCK_REGISTRY.get(block_id)
    return reg[1] if reg else block_id




@app.route('/build/<product_type>', methods=['GET'])
@login_required
def build_form_generic(product_type):
    """Legacy route — redirect to new workspace."""
    _validate_product_type(product_type)
    return redirect(url_for('index', _external=False))


@app.route('/build/<product_type>', methods=['POST'])
@login_required
def build_submit_generic(product_type):
    _validate_product_type(product_type)
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
    qr_image           = _save_upload('qr_image')                            # 微信二维码

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
    # 兜底：表单未填参数时，使用配置中的 default_specs
    if not e_specs:
        default_specs = cfg.get("default_specs", [])
        if isinstance(default_specs, list):
            e_specs = [{"name": s.get("name", ""), "value": s.get("value", "")}
                       for s in default_specs if s.get("name") and s.get("value")]

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
    block_b3["effect_image"] = effect_image  # 有效果图时整张顶替"背景+产品图"组合区
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

    # 二维码图片覆盖 block_n
    if qr_image:
        extra_blocks["block_n"]["qr_image"] = qr_image

    # ── brand_stats / brand_story_lines → block_g ──
    _g_stats_raw = form_text("block_g_stats_json", "")
    if _g_stats_raw:
        try:
            _g_stats = json.loads(_g_stats_raw)
            if isinstance(_g_stats, list) and _g_stats:
                extra_blocks["block_g"]["brand_stats"] = _g_stats
        except (json.JSONDecodeError, ValueError):
            pass
    _g_lines_raw = form_text("block_g_lines_json", "")
    if _g_lines_raw:
        try:
            _g_lines = json.loads(_g_lines_raw)
            if isinstance(_g_lines, list) and _g_lines:
                extra_blocks["block_g"]["brand_story_lines"] = _g_lines
        except (json.JSONDecodeError, ValueError):
            pass

    # 表单 JSON 字段覆盖（AI 识别填入 → 用户可编辑 → 提交覆盖配置默认）
    _json_field_map = {
        "block_h_json": ("block_h", "scenes"),
        "block_i_json": ("block_i", "kpis"),
        "block_m_json": ("block_m", "steps"),
        "block_p_json": ("block_p", "compat_models"),
        "block_q_json": ("block_q", "comparisons"),
        "block_r_json": ("block_r", "package_items"),
        "block_j_json": ("block_j", "tech_items"),
        "block_s_json": ("block_s", "faqs"),
        "block_k_json": ("block_k", "badge_items"),
        "block_l_json": ("block_l", "compare_rows"),
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

    # 保存预览数据供导出使用（按用户隔离）
    _save_data = dict(data)
    _user_out = _user_output_dir()
    _last_preview = _user_out / f"_last_{product_type}_preview.json"
    with open(_last_preview, "w", encoding="utf-8") as fp:
        json.dump(_save_data, fp, ensure_ascii=False)

    return render_template(f"{product_type}/assembled.html", **data)


@app.route('/api/build/<product_type>/render-preview', methods=['POST'])
@login_required
@csrf.exempt
def render_preview(product_type):
    """Render all modules as HTML fragments for the workspace preview."""
    _validate_product_type(product_type)
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "缺少请求数据"}), 400

    parsed = data.get("parsed_data", {})
    # parsed_data is already mapped form-field keys (output of _map_parsed_to_form_fields
    # from the parse-text endpoint). Do NOT re-map it or all AI data is discarded.
    mapped = parsed if parsed else {}
    cfg = _load_build_config(product_type)

    images = {
        "product_image": data.get("product_image", ""),
        "scene_image": data.get("scene_image", ""),
        "logo_image": data.get("logo_image", ""),
        "qr_image": data.get("qr_image", ""),
        "product_side_image": data.get("product_side_image", ""),
        "effect_image": data.get("effect_image", ""),
    }

    all_data = _assemble_all_blocks(product_type, mapped, images, cfg)

    # Save preview data for export
    _user_out = _user_output_dir()
    _last_preview = _user_out / f"_last_{product_type}_preview.json"
    with open(_last_preview, "w", encoding="utf-8") as fp:
        json.dump(all_data, fp, ensure_ascii=False)

    # Define render order (matches assembled.html order)
    render_order = [
        "block_a", "block_b2", "block_b3", "block_g", "block_h", "block_i",
        "block_j", "block_f", "block_x", "block_w", "block_v",
        "block_e",
        "block_k", "block_l", "block_m", "block_t", "block_u", "block_s",
        "block_p", "block_q", "block_r",
        "block_n", "block_o",
    ]

    modules = []
    for bid in render_order:
        block_data = all_data.get(bid, {})
        # 智能模块匹配：跳过没有有效数据的模块
        if _is_block_empty(bid, block_data):
            continue
        html = _render_single_block(bid, block_data)
        if not html or not html.strip():
            continue
        modules.append({
            "id": bid,
            "name": _get_block_display_name(bid),
            "html": html,
            "data": block_data,
        })

    return jsonify({"modules": modules})


@app.route('/api/build/<product_type>/render-block', methods=['POST'])
@login_required
@csrf.exempt
def render_single_block_api(product_type):
    """Re-render a single block's HTML (for edit-and-refresh)."""
    _validate_product_type(product_type)
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "缺少请求数据"}), 400

    block_id = data.get("block_id", "")
    block_data = data.get("block_data", {})

    if not block_id or block_id not in _BLOCK_REGISTRY:
        return jsonify({"error": f"未知模块: {block_id}"}), 400

    html = _render_single_block(block_id, block_data)
    return jsonify({"html": html})


@app.route('/api/build/<product_type>/regenerate-block', methods=['POST'])
@login_required
@csrf.exempt
def regenerate_block_api(product_type):
    """AI-regenerate a single block's content without affecting others."""
    _validate_product_type(product_type)
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "缺少请求数据"}), 400

    block_id = data.get("block_id", "")
    if not block_id or block_id not in _BLOCK_REGISTRY:
        return jsonify({"error": f"未知模块: {block_id}"}), 400

    parsed_data = data.get("parsed_data", {})
    images = {
        "product_image": data.get("product_image", ""),
        "scene_image": data.get("scene_image", ""),
        "logo_image": data.get("logo_image", ""),
        "qr_image": data.get("qr_image", ""),
        "product_side_image": data.get("product_side_image", ""),
        "effect_image": data.get("effect_image", ""),
    }

    # Get API key
    api_key = ""
    if hasattr(current_user, 'deepseek_api_key') and current_user.deepseek_api_key:
        api_key = current_user.deepseek_api_key

    # Build a focused prompt for regenerating just this block
    block_name = _get_block_display_name(block_id)
    raw_context = json.dumps(parsed_data, ensure_ascii=False, indent=2)

    regen_prompt = (
        f"你是清洁设备营销文案专家。请根据以下已有产品信息，重新生成「{block_name}」模块的文案。\n\n"
        f"{_EXTREME_WORDS_RULE}"
        f"已有产品信息：\n{raw_context}\n\n"
        f"请用不同的角度和表达方式重新创作该模块的文案，保持信息准确但措辞新颖。\n"
        f"返回JSON格式，只包含该模块需要的字段。\n"
    )

    import requests as req
    use_key = api_key or DEEPSEEK_API_KEY
    if not use_key:
        return jsonify({"error": "未配置 API Key"}), 400

    try:
        resp = req.post(
            DEEPSEEK_API_URL,
            headers={"Authorization": f"Bearer {use_key}"},
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": "你是清洁设备营销文案专家。只返回JSON。"},
                    {"role": "user", "content": regen_prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 2000,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        regen_data = _extract_json_object(content)
        if not isinstance(regen_data, dict):
            return jsonify({"error": "AI返回数据解析失败"}), 500
    except Exception as e:
        return jsonify({"error": f"AI重新生成失败: {e}"}), 500

    # Merge regenerated fields into existing block data, then re-assemble
    mapped = _map_parsed_to_form_fields(parsed_data)
    cfg = _load_build_config(product_type)
    all_data = _assemble_all_blocks(product_type, mapped, images, cfg)

    existing_block = all_data.get(block_id, {})
    # Merge regen_data into existing block data (regen takes priority for string values)
    for k, v in regen_data.items():
        if v and isinstance(v, str):
            existing_block[k] = v
        elif v and isinstance(v, list) and len(v) > 0:
            existing_block[k] = v

    html = _render_single_block(block_id, existing_block)
    return jsonify({"html": html, "data": existing_block})


# ── 主图渲染 API ───────────────────────────────────────────────────

@app.route('/api/build/<product_type>/render-main-images', methods=['POST'])
@login_required
@csrf.exempt
def render_main_images(product_type):
    """Render all 5 main image templates as HTML fragments."""
    _validate_product_type(product_type)
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "缺少请求数据"}), 400

    parsed = data.get("parsed_data", {})
    tpl_data = {
        "product_image": data.get("product_image", ""),
        "scene_image": data.get("scene_image", ""),
        "logo_image": data.get("logo_image", ""),
        "model_name": parsed.get("model", ""),
        "brand_text": parsed.get("brand", ""),
        "slogan": parsed.get("slogan", ""),
        "sub_slogan": parsed.get("sub_slogan", ""),
        "hero_subtitle": parsed.get("hero_subtitle", ""),
        "category_line": parsed.get("category_line", ""),
        "advantages": parsed.get("advantages", []),
        "spec_callouts": parsed.get("spec_callouts", []),
    }

    results = []
    for tpl_id, (tpl_path, display_name) in _MAIN_IMG_REGISTRY.items():
        try:
            html = render_template(tpl_path, **tpl_data)
        except Exception as e:
            print(f"[主图渲染] {tpl_id} 失败: {e}")
            html = f'<div style="width:800px;height:800px;display:flex;align-items:center;justify-content:center;background:#f5f5f5;color:red;">渲染失败: {e}</div>'
        results.append({
            "id": tpl_id,
            "name": display_name,
            "html": html,
        })

    return jsonify({"main_images": results})


# 模块主图候选（从详情图里挑 5 个信息密度高的 block）
_MAIN_BLOCK_CANDIDATES = [
    ("block_a",  "英雄封面"),
    ("block_b3", "清洁故事"),
    ("block_f",  "VS对比"),
    ("block_h",  "场景网格"),
    ("block_c1", "数据对比"),
]


@app.route('/export/<product_type>/main-images', methods=['POST'])
@login_required
def export_main_images_zip(product_type):
    """Export the 5 module-main-images (block_a/b3/f/h/c1) as 750-wide PNGs in a ZIP."""
    _validate_product_type(product_type)
    req_data = request.get_json(silent=True) or {}
    theme_id = req_data.get("theme_id", "classic-red")

    # 读取详情预览缓存（包含所有 block 已组装好的数据）
    _user_out = _user_output_dir()
    preview_json = _user_out / f"_last_{product_type}_preview.json"
    if not preview_json.exists():
        return jsonify({"error": "请先生成详情图预览，再导出模块主图"}), 400

    with open(preview_json, "r", encoding="utf-8") as fp:
        preview_data = json.load(fp)

    # 主题 CSS 变量
    theme_vars = {}
    themes_path = BASE_DIR / "static" / "themes" / "themes.json"
    if themes_path.exists():
        with open(themes_path, "r", encoding="utf-8") as f:
            themes_data = json.load(f)
        for t in themes_data.get("themes", []):
            if t["id"] == theme_id:
                theme_vars = t.get("vars", {})
                break
    css_vars = "; ".join(f"{k}:{v}" for k, v in theme_vars.items()) if theme_vars else ""

    import zipfile, io
    zip_buffer = io.BytesIO()
    base_url_str = str(BASE_DIR).replace("\\", "/")

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                args=["--no-sandbox", "--disable-web-security", "--allow-file-access-from-files"]
            )
            ctx = browser.new_context(
                viewport={"width": 750, "height": 1200},  # 宽固定，高度由 full_page 自适应
                device_scale_factor=2,
            )

            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                for block_id, display_name in _MAIN_BLOCK_CANDIDATES:
                    block_data = preview_data.get(block_id) or {}
                    if not block_data:
                        continue
                    html = _render_single_block(block_id, block_data)
                    if not html or not html.strip():
                        continue

                    full_html = f'''<!DOCTYPE html><html><head><meta charset="UTF-8">
                    <style>*{{margin:0;padding:0;box-sizing:border-box;}} body{{width:750px;background:#fff;}}</style>
                    </head><body style="{css_vars}">{html}</body></html>'''

                    full_html = full_html.replace('src="/static/', f'src="file:///{base_url_str}/static/')
                    full_html = full_html.replace("src='/static/", f"src='file:///{base_url_str}/static/")

                    temp_html = _user_out / f"_mainimg_{block_id}_{uuid.uuid4().hex[:6]}.html"
                    with open(temp_html, "w", encoding="utf-8") as f:
                        f.write(full_html)

                    page = ctx.new_page()
                    page.goto(temp_html.as_uri(), wait_until="networkidle", timeout=15000)
                    page.wait_for_timeout(500)
                    png_bytes = page.screenshot(full_page=True)
                    page.close()

                    zf.writestr(f"{display_name}_{block_id}.png", png_bytes)
                    try:
                        temp_html.unlink()
                    except Exception:
                        pass

            browser.close()
    except Exception as exc:
        import traceback; traceback.print_exc()
        return jsonify({"error": f"模块主图导出失败: {exc}"}), 500

    zip_buffer.seek(0)
    model_name = preview_data.get("block_a", {}).get("model_name", product_type)
    return send_file(
        zip_buffer, mimetype="application/zip",
        as_attachment=True,
        download_name=f"{product_type}_{model_name}_模块主图.zip"
    )


# ── 导出PNG（Playwright截图）────────────────────────────────────────

@app.route('/export/<product_type>', methods=['POST'])
@login_required
def export_generic(product_type):
    _validate_product_type(product_type)
    _user_out = _user_output_dir()
    preview_json = _user_out / f"_last_{product_type}_preview.json"
    if not preview_json.exists():
        return jsonify({"error": "没有预览数据，请先生成预览"}), 400

    with open(preview_json, "r", encoding="utf-8") as fp:
        data = json.load(fp)

    # Get module order and hidden modules from request
    req_data = request.get_json(silent=True) or {}
    module_order = req_data.get("module_order", [])
    hidden_modules = set(req_data.get("hidden_modules", []))
    theme_id = req_data.get("theme_id", "classic-red")

    # Load theme CSS vars
    theme_vars = {}
    themes_path = BASE_DIR / "static" / "themes" / "themes.json"
    if themes_path.exists():
        with open(themes_path, "r", encoding="utf-8") as f:
            themes_data = json.load(f)
        for t in themes_data.get("themes", []):
            if t["id"] == theme_id:
                theme_vars = t.get("vars", {})
                break
    css_vars_str = "; ".join(f"{k}:{v}" for k, v in theme_vars.items()) if theme_vars else ""

    if module_order:
        # Render blocks individually in user-specified order, skipping hidden
        block_htmls = []
        for bid in module_order:
            if bid in hidden_modules:
                continue
            block_data = data.get(bid, {})
            html = _render_single_block(bid, block_data)
            if html and html.strip():
                block_htmls.append(html)

        # Also render fixed selling images
        fixed_imgs_html = ""
        for img_url in data.get("fixed_selling_images", []):
            if img_url:
                fixed_imgs_html += f'<div class="screen"><img style="width:750px;display:block;" src="{img_url}" alt=""></div>'

        html_content = f'''<!DOCTYPE html><html><head><meta charset="UTF-8">
        <style>*{{margin:0;padding:0;box-sizing:border-box;}} body{{width:750px;background:#fff;}}</style>
        </head><body style="{css_vars_str}">
        {"".join(block_htmls)}
        {fixed_imgs_html}
        </body></html>'''
    else:
        # Fallback: use assembled template (legacy)
        data["export_mode"] = True
        tpl = f"{product_type}/assembled.html"
        html_content = render_template(tpl, **data)

    base_url_str = str(BASE_DIR).replace("\\", "/")
    html_content = html_content.replace('src="/static/', f'src="file:///{base_url_str}/static/')
    html_content = html_content.replace("src='/static/", f"src='file:///{base_url_str}/static/")

    temp_html = OUTPUT_DIR / f"_export_{product_type}_{current_user.id}_{uuid.uuid4().hex[:8]}.html"
    with open(temp_html, "w", encoding="utf-8") as f:
        f.write(html_content)

    from datetime import datetime
    model_name = data.get("block_a", {}).get("model_name", product_type)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_filename = f"{product_type}_{model_name}_{timestamp}.png"
    _user_outputs = STATIC_OUTPUTS / str(current_user.id)
    _user_outputs.mkdir(parents=True, exist_ok=True)
    out_path = _user_outputs / out_filename

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                args=["--no-sandbox", "--disable-web-security", "--allow-file-access-from-files"]
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

    # 记录导出日志
    log = GenerationLog(
        user_id=current_user.id,
        product_type=product_type,
        model_name=data.get("block_a", {}).get("model_name", ""),
        api_key_source="",
        action="export",
    )
    db.session.add(log)
    db.session.commit()

    return send_file(str(out_path), mimetype="image/png",
                     as_attachment=True, download_name=out_filename)


# ── 设备类静态预览（调试用）──────────────────────────────────────────

@app.route("/preview/设备类")
@login_required
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


# ── 注册蓝图 ──
from auth import auth_bp
from admin import admin_bp
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)

# ── CLI 命令：创建管理员 ──
import click

@app.cli.command("create-admin")
@click.option("--username", prompt=True, help="管理员用户名")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True, help="管理员密码")
def create_admin(username, password):
    """创建管理员账号"""
    existing = User.query.filter_by(username=username).first()
    if existing:
        click.echo(f"用户 {username} 已存在")
        return
    admin = User(username=username, is_admin=True, is_approved=True, is_paid=True)
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    click.echo(f"管理员 {username} 创建成功")

# ── 启动时自动建表 ──
with app.app_context():
    db.create_all()


if __name__ == "__main__":
    _kill_old_flask(5000)
    print("=" * 50)
    print("  小玺AI产品详情页生成器 - Web UI")
    print("=" * 50)
    print(f"  入口: http://localhost:5000/build/{PRODUCT_TYPE}")
    print(f"  预览: http://localhost:5000/preview/{PRODUCT_TYPE}")
    print("=" * 50)
    app.run(debug=True, port=5000, use_reloader=False)
