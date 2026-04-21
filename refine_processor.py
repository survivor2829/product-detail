"""任务11 单产品 AI 精修处理器。

PRD F6: 调豆包 Seedream 生成 6 屏 AI 背景 → HTML/CSS 合成 → Playwright 截图 → 落 ai_refined.jpg

与任务4 `batch_processor.process_one_product` 的关系:
  - 任务4 出 preview.png (HTML 版底图, 纯 CSS + 产品图, 无 AI 背景)
  - 任务11 出 ai_refined.jpg (专业精修, 用 Seedream 6 屏 AI 背景)
  - 任务11 复用任务4 已落盘的 parsed.json / product_cut.png, 不重跑 DeepSeek / rembg

与 /api/generate-ai-detail-html 的关系:
  - 路由层做 HTTP 请求调度 + 单次精修
  - 本模块做 worker 线程内的同样逻辑, 跳过 Flask 路由但复用底层链:
    ai_bg_cache.generate_backgrounds + _build_ctxs_from_parsed + ai_compose_pipeline

覆盖语义:
  - 文件 product_dir/ai_refined.jpg — Pillow 保存自动覆盖
  - 重跑 done 的产品 → 旧文件永久丢失, 这是 PRD F6 "确认后覆盖重扣费" 的承诺
"""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path


def refine_one_product(scope_id: str, payload: dict, *, ark_api_key: str) -> dict:
    """对单个 BatchItem 执行 AI 精修, 产出最终 ai_refined.jpg。

    scope_id: batch_id (batch_queue.submit_refine 透传, 主要用于日志前缀)
    payload:
        {
            "name":                "产品A",
            "main_image_path":     "/uploads/.../产品A/product.jpg",   # URL
            "cutout_path":         "/uploads/.../产品A/product_cut.png",  # 可空
            "parsed_json_path":    "/uploads/.../产品A/parsed.json",   # 必填
            "resolved_theme_id":   "tech-blue",                         # 任务9 已算好
            "product_category":    "设备类",
        }
    ark_api_key: 用户豆包 Key (从 POST body 里拿, 由端点闭包绑定)

    raises: 任何异常上抛 (batch_queue._submit_one 会兜成 status=failed)
        - ValueError: payload 必填缺失 / parsed.json 不存在
        - FileNotFoundError: 主图路径不存在
        - 其它: ai_bg_cache / ai_compose_pipeline 内部抛的

    returns:
        {
            "ai_refined_path":  "/uploads/.../产品A/ai_refined.jpg",  # URL
            "ai_refined_at":    1712345678,                           # unix 秒
            "segments_count":   7,                                    # 合成的屏数
            "total_elapsed":    13.5,                                 # 秒
            "bg_cache_hits":    ...,  # 调试用, 命中了几个缓存
        }
    """
    # app: 注入 Flask app context — 本模块跑在 ThreadPoolExecutor worker 里,
    # 默认没有 request/app context; _build_ctxs_from_parsed 走 _match_scene_image
    # 会调 url_for('static', ...),没上下文直接抛 "Working outside of application context".
    # 用 with app.app_context(): 包住所有调用 url_for 的链路 — 修复 2026-04-20 线上事故.
    from app import (
        app,
        BASE_DIR,
        _build_ctxs_from_parsed,
        _resolve_asset_urls_in_ctx,
    )
    import ai_bg_cache
    import ai_compose_pipeline

    name = payload.get("name") or "unknown"
    main_url = (payload.get("main_image_path") or "").strip()
    cutout_url = (payload.get("cutout_path") or "").strip()
    parsed_url = (payload.get("parsed_json_path") or "").strip()
    theme_id = (payload.get("resolved_theme_id") or "classic-red").strip()
    product_category = (payload.get("product_category") or "设备类").strip()

    if not (ark_api_key or "").strip():
        raise ValueError(f"产品 {name} 缺 ark_api_key")
    if not main_url:
        raise ValueError(f"产品 {name} 缺 main_image_path")
    if not parsed_url:
        raise ValueError(f"产品 {name} 缺 parsed_json_path (任务4 应已落盘)")

    parsed_path = BASE_DIR / parsed_url.lstrip("/")
    if not parsed_path.is_file():
        raise FileNotFoundError(f"parsed.json 不在: {parsed_path}")
    parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
    product_dir = parsed_path.parent

    # 产品图优先用抠图版 (没有就用原图) — 跟 batch_processor._render_product_preview 一致
    product_image_url = cutout_url or main_url

    brand = str(parsed.get("brand") or "").strip()
    product_name = str(
        parsed.get("product_name") or parsed.get("model")
        or parsed.get("main_title") or name
    ).strip()

    print(f"[refine] {scope_id}/{name} → 生成 6 屏 AI 背景 "
          f"(theme={theme_id} brand={brand!r})", flush=True)
    t0 = time.time()
    try:
        backgrounds = ai_bg_cache.generate_backgrounds(
            theme_id=theme_id,
            product_category=product_category,
            brand=brand,
            api_key=ark_api_key,
            product_name=product_name,
            reference_image_url="",   # 批次场景无场景参考图,用 theme_id 即可
        )
    except Exception as e:
        # 让 ai_bg_cache 内部的失败逻辑已经打过 traceback,这里再打一次防吞掉
        traceback.print_exc()
        raise RuntimeError(f"AI 背景生成失败: {type(e).__name__}: {e}") from e
    bg_elapsed = round(time.time() - t0, 2)
    print(f"[refine] {scope_id}/{name} → 背景就绪 ({len(backgrounds)}/6 成功, "
          f"{bg_elapsed}s)", flush=True)

    # 构建 ctxs — 必须在 test_request_context 里跑:
    #   _match_scene_image 调 url_for('static', ...), 光 app_context 不够,
    #   url_for 还需要 request context (或 SERVER_NAME 配置) 才能推导 URL scheme.
    #   test_request_context() 注入一个假请求环境, 让 url_for('static', ...) 能输出
    #   /static/scene_bank/xxx 这种相对路径 — 足够 compose 用 _to_file_uri_if_local 转.
    #   修复 2026-04-20 事故: worker 线程之前既没 app context 也没 request context.
    with app.test_request_context():
        ctxs = _build_ctxs_from_parsed(
            parsed, product_image_url, theme_id,
            backgrounds=backgrounds,
            scene_image_url="", effect_image_url="", qr_image_url="",
        )
        if not ctxs:
            raise ValueError(f"parsed 空 ctxs, 无可渲染屏 (至少要 main_title)")

        resolved_ctxs = {
            k: _resolve_asset_urls_in_ctx(v) for k, v in ctxs.items()
            if isinstance(v, dict)
        }
    order = ai_compose_pipeline.DEFAULT_ORDER

    print(f"[refine] {scope_id}/{name} → 合成长图 (order={order})", flush=True)
    t1 = time.time()
    result = ai_compose_pipeline.compose_detail_page(
        ctxs=resolved_ctxs,
        order=order,
        out_dir=product_dir,            # 落产品目录, 跟 preview.png 同家
        out_jpg_name="ai_refined.jpg",  # 覆盖语义: 原地重写
        jpg_quality=90,
        verbose=False,
    )
    compose_elapsed = round(time.time() - t1, 2)

    jpg_abs = Path(result["jpg"])
    ai_refined_url = "/" + jpg_abs.resolve().relative_to(
        BASE_DIR.resolve()
    ).as_posix()

    out = {
        "ai_refined_path": ai_refined_url,
        "ai_refined_at":   int(time.time()),
        "segments_count":  len(result.get("segments") or []),
        "total_elapsed":   round(bg_elapsed + compose_elapsed, 2),
        "bg_elapsed":      bg_elapsed,
        "compose_elapsed": compose_elapsed,
        "theme_id":        theme_id,
        "width":           result.get("width"),
        "height":          result.get("height"),
    }
    print(f"[refine] {scope_id}/{name} → 完成 {ai_refined_url} "
          f"({out['total_elapsed']}s, {out['segments_count']} 屏)", flush=True)
    return out
