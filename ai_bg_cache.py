"""
AI 背景图缓存层 — v2 HTML 合成管线专用

两种模式(环境变量 AI_BG_MODE 控制):
  - cache    (默认/开发/测试):  同 (theme_id, screen_type, product_category) 24h 内复用
                                不重复烧 Seedream API
  - realtime (生产/面向客户):   每次都实时调 Seedream 生成全新背景
                                忽略缓存文件的存在

失败降级:
  API 未配置 / 调用超时 / 下载失败 → 返回空字符串 bg_url
  → 模板 {% if bg_url %}...{% else %}<CSS 渐变>{% endif %} 自动走兜底

屏级策略(SCREENS_NEEDING_BG):
  需要 AI 背景的 6 屏: hero / advantages / specs / vs / scene / brand
  主动排除 1 屏: cta
    原因: cta.html 已有精心设计的 3 层渐变 + 左下金晕 + 右上聚光
          AI 背景会破坏这套品牌色视觉,留 CSS 渐变效果更好
"""
from __future__ import annotations

import hashlib
import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterable

import ai_image_volcengine as vol
import theme_color_flows


# ── 常量 ─────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / "static" / "cache" / "ai_bg"

PROMPT_VERSION = "v1"            # 提示词模板版本,改版时 +1 使旧缓存失效
CACHE_TTL_SECONDS = 24 * 3600    # cache 模式的文件新鲜期(24h)

SCREENS_NEEDING_BG = ("hero", "advantages", "specs", "vs", "scene", "brand")

# 每屏的 Seedream 生图尺寸(会被 _pick_seedream_size 映射到最接近的支持尺寸)
# 按模板 canvas 宽高比选,不必精确匹配 — CSS background-size: cover 会托底
_SCREEN_CANVAS: dict[str, tuple[int, int]] = {
    "hero":       (768, 1024),
    "advantages": (768, 960),
    "specs":      (768, 832),
    "vs":         (768, 960),
    "scene":      (768, 832),
    "brand":      (768, 768),
}


# ── 模式解析 ────────────────────────────────────────────────

def get_mode() -> str:
    """读 AI_BG_MODE,缺省返回 'cache'"""
    return (os.getenv("AI_BG_MODE") or "cache").strip().lower()


def _cache_key(theme_id: str, screen: str, category: str,
               product_name: str = "") -> str:
    """
    缓存 key 要把"能决定背景视觉差异的轴"都混入:
      theme_id   — 主题色调决定
      screen     — 屏别(hero/specs/...)决定构图
      category   — 品类(驾驶式洗地机/扫地机/...)决定主体语义
      product_name — 型号(DZ50X/DZ60X/...)决定具体产品;不加 → 同品类所有型号串包
      PROMPT_VERSION — 提示词版本,改版时自动让旧缓存失效
    """
    raw = f"{theme_id}|{screen}|{category}|{product_name}|{PROMPT_VERSION}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _cached_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.png"


def _is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < CACHE_TTL_SECONDS


def _to_static_url(path: Path) -> str:
    """把 static/cache/ai_bg/xxx.png 绝对路径转成 /static/cache/ai_bg/xxx.png"""
    rel = path.relative_to(BASE_DIR)
    return "/" + rel.as_posix()


# ── Prompt 构造 ─────────────────────────────────────────────

def _build_prompt(theme_id: str, screen: str, category: str, brand: str) -> str:
    """
    拼接"基础产品语义" + "主题色调" → 最终给 Seedream 的提示词。
    基础语义来自 ai_image_volcengine 的 prompt_* 函数;
    色调来自 theme_color_flows.get_flow(theme_id)["screens"][screen]["bg_tone"]。
    """
    flow = theme_color_flows.get_flow(theme_id) or {}
    tone = (flow.get("screens") or {}).get(screen, {}).get("bg_tone", "")

    if screen == "hero":
        base = vol.prompt_hero(category or "商用设备", brand)
    elif screen == "specs":
        base = vol.prompt_specs_bg()
    elif screen == "vs":
        base = vol.prompt_comparison_bg()
    elif screen == "brand":
        base = vol.prompt_brand_bg(brand)
    elif screen == "scene":
        base = vol.prompt_scene("通用应用场景", category or "商用设备")
    elif screen == "advantages":
        base = f"{category or '商用设备'} 优势说明屏背景,干净极简商业摄影,充足留白以叠加白色卡片和文字"
    else:
        base = f"{category or '商用设备'} 产品详情页背景"

    return f"{base}, {tone}" if tone else base


# ── 单屏生成 ────────────────────────────────────────────────

def _generate_one(theme_id: str, screen: str, category: str,
                  brand: str, api_key: str, mode: str,
                  product_name: str = "") -> str:
    """
    单屏生成入口 — 根据 mode 决定走缓存或实时调 API。
    返回 /static/cache/ai_bg/<key>.png(成功)或 ""(失败 → 模板兜底)
    """
    key = _cache_key(theme_id, screen, category, product_name)
    path = _cached_path(key)

    # cache 模式且缓存新鲜 → 直接复用
    if mode == "cache" and _is_fresh(path):
        print(f"[bg] HIT   {screen:11s} → {path.name}")
        return _to_static_url(path)

    prompt = _build_prompt(theme_id, screen, category, brand)
    w, h = _SCREEN_CANVAS.get(screen, (768, 1024))

    try:
        urls = vol.generate_segment(screen, prompt, api_key,
                                    width=w, height=h)
        if not urls:
            print(f"[bg] EMPTY {screen:11s} Seedream 返回空 URL 列表")
            return ""

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # 复用 vol.download_image,它内部会清代理 + 重试
        local = vol.download_image(urls[0], CACHE_DIR, filename=f"{key}.png")
        if not local or not Path(local).exists():
            print(f"[bg] DLFAIL {screen:11s} 下载失败")
            return ""

        tag = "NEW  " if mode == "realtime" else "MISS "
        print(f"[bg] {tag} {screen:11s} → {path.name}")
        return _to_static_url(path)

    except Exception as e:
        print(f"[bg] ERROR {screen:11s} 生成失败: {e}")
        traceback.print_exc()
        return ""


# ── 批量并发生成 ────────────────────────────────────────────

def generate_backgrounds(theme_id: str,
                         product_category: str,
                         brand: str = "",
                         api_key: str = "",
                         screens: Iterable[str] = SCREENS_NEEDING_BG,
                         product_name: str = "",
                         ) -> Dict[str, str]:
    """
    并发生成 N 屏背景图。返回 {screen_type: bg_url 或 ""}。

    注意: 这里不抛异常,任何单屏失败都降级为 "" → 模板走 CSS 兜底。
    这样单点故障不会阻塞整张长图生成。

    product_name 是缓存 key 的一部分(见 _cache_key):
      不传 → 同主题+品类所有产品串用同一张背景(DZ50X 看到 DZ60X 的图)
      传了 → 每个型号各自有独立缓存,避免视觉串包
    """
    screens = tuple(screens)
    mode = get_mode()

    # 没有 API key → 全部走 CSS 兜底,不联网
    if not api_key:
        print(f"[bg] 无 ARK_API_KEY,全部 {len(screens)} 屏走 CSS 兜底")
        return {s: "" for s in screens}

    print(f"[bg] 模式={mode}  主题={theme_id}  品类={product_category or '(空)'}  "
          f"产品={product_name or '(空)'}  并发屏数={len(screens)}")

    results: Dict[str, str] = {s: "" for s in screens}
    # I/O bound,用线程池;Seedream 调用是串行 HTTP,并发可减总时长到接近单屏
    with ThreadPoolExecutor(max_workers=min(len(screens), 7)) as pool:
        futures = {
            pool.submit(_generate_one, theme_id, s, product_category,
                        brand, api_key, mode, product_name): s
            for s in screens
        }
        for fut in as_completed(futures):
            s = futures[fut]
            try:
                results[s] = fut.result() or ""
            except Exception as e:
                print(f"[bg] ERROR {s} 未捕获异常: {e}")
                traceback.print_exc()
                results[s] = ""

    hits = sum(1 for v in results.values() if v)
    print(f"[bg] 完成: {hits}/{len(screens)} 屏拿到背景图")
    return results
