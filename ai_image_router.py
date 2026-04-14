"""
AI 生图双引擎路由层 — 统一接口，按 engine 字段分发到通义万相或豆包 Seedream
"""
import os
from pathlib import Path

import ai_image                  # 通义万相 (DashScope)
import ai_image_volcengine       # 豆包 Seedream 4.0 (Ark)
import prompt_templates          # 专业级 prompt 模板库（六维结构化）


# ── 引擎元数据（前端下拉框可读取）──────────────────────────────
ENGINES = {
    "wanxiang": {
        "id": "wanxiang",
        "label": "通义万相",
        "vendor": "阿里云百炼",
        "model": ai_image.T2I_MODEL,
        "key_env": "DASHSCOPE_API_KEY",
        "key_field": "dashscope_api_key",
        "cost_hint": "约 0.04-0.08 元/张",
    },
    "seedream": {
        "id": "seedream",
        "label": "豆包 Seedream 4.0",
        "vendor": "字节跳动 火山方舟",
        "model": ai_image_volcengine.T2I_MODEL,
        "key_env": "ARK_API_KEY",
        "key_field": "ark_api_key",
        "cost_hint": "约 0.08-0.16 元/张",
    },
}

DEFAULT_ENGINE = "seedream"


# ── 专业 prompt 规划 ─────────────────────────────────────────────
# 统一入口：app.py 调本函数拿到每段 prompt，再交给 generate_segment_to_local

def plan_page(theme_id: str,
              zones: list[str] | None = None,
              product_hint: str = "",
              variants: dict[str, str] | None = None) -> list[dict]:
    """
    规划无缝长图的每段 prompt（使用 prompt_templates 的六维模板）。

    返回 list[dict]，每项含：
        zone / variant / height / overlap_bottom / prompt / negative_prompt
    """
    zones = zones or prompt_templates.DEFAULT_VARIANT  # dict → keys iterable
    if isinstance(zones, dict):
        zones = ["hero", "advantages", "specs", "vs", "scene", "brand", "cta"]
    return prompt_templates.get_prompts_for_theme(
        theme_id, zones, variants=variants, product_hint=product_hint
    )


def list_engines() -> list[dict]:
    """返回引擎列表，前端下拉框直接消费"""
    return list(ENGINES.values())


def _resolve_key(engine: str, api_keys: dict) -> str:
    """
    解析 API key：优先 api_keys 字段（请求体传入），其次环境变量。
    api_keys = {"dashscope_api_key": "...", "ark_api_key": "..."}
    """
    meta = ENGINES.get(engine) or ENGINES[DEFAULT_ENGINE]
    key = (api_keys or {}).get(meta["key_field"], "")
    if not key:
        key = os.environ.get(meta["key_env"], "")
    return key.strip()


def generate_segment(engine: str, zone: str, prompt: str,
                     api_keys: dict,
                     width: int = 750, height: int = 1334,
                     negative_prompt: str = "") -> list[str]:
    """
    统一段生成接口（无缝长图方案）。
    返回 URL 列表（成功时长度 1，失败时空列表）。
    """
    engine = engine if engine in ENGINES else DEFAULT_ENGINE
    key = _resolve_key(engine, api_keys)
    if not key:
        meta = ENGINES[engine]
        raise ValueError(f"缺少 {meta['label']} 的 API Key（环境变量 {meta['key_env']} 或请求字段 {meta['key_field']}）")

    if engine == "seedream":
        return ai_image_volcengine.generate_segment(zone, prompt, key,
                                                    width=width, height=height,
                                                    negative_prompt=negative_prompt)
    return ai_image.generate_segment(zone, prompt, key,
                                     width=width, height=height,
                                     negative_prompt=negative_prompt)


def download_image(engine: str, url: str, save_dir, filename: str = "") -> str:
    """按引擎选择对应的下载实现（两边接口一致，但保留分发以便未来差异化）"""
    if engine == "seedream":
        return ai_image_volcengine.download_image(url, save_dir, filename)
    return ai_image.download_image(url, save_dir, filename)


def generate_segment_to_local(engine: str, zone: str, prompt: str,
                              api_keys: dict, save_dir,
                              width: int = 750, height: int = 1334,
                              filename: str = "") -> str:
    """
    一步到位：调用引擎生成 + 下载到本地，返回本地文件路径（失败返回空串）。
    供 /api/build/<type>/generate-ai-detail 端点逐段调用。
    """
    urls = generate_segment(engine, zone, prompt, api_keys,
                            width=width, height=height)
    if not urls:
        return ""
    fname = filename or f"{engine}_{zone}.png"
    return download_image(engine, urls[0], save_dir, fname)


# ── 兼容旧 /api/generate-ai-images 流程（逐块模式）─────────────

def generate_detail_backgrounds(engine: str, product_data: dict,
                                api_keys: dict, save_dir) -> dict:
    """旧版逐块生成接口（保留兼容），按 engine 分发"""
    engine = engine if engine in ENGINES else DEFAULT_ENGINE
    key = _resolve_key(engine, api_keys)
    if not key:
        meta = ENGINES[engine]
        raise ValueError(f"缺少 {meta['label']} 的 API Key")

    if engine == "seedream":
        return ai_image_volcengine.generate_detail_backgrounds(product_data, key, save_dir)
    return ai_image.generate_detail_backgrounds(product_data, key, save_dir)


if __name__ == "__main__":
    print("可用引擎:")
    for e in list_engines():
        print(f"  - {e['id']} ({e['label']} / {e['vendor']}) → 模型 {e['model']}, 环境变量 {e['key_env']}")
