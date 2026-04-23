"""AI 精修 v2 · DeepSeek 规划官核心.

对外入口:
    from ai_refine_v2.refine_planner import plan, PlannerError

    result = plan(
        product_text="DZ600M 无人水面清洁机 ...",
        product_image_url="https://.../product_cut.png",  # 可选
        user_opts={"force_vs": False, "force_scenes": False, "force_specs": False},
        api_key=None,  # 不传则从 env DEEPSEEK_API_KEY 读
    )
    # → dict, 符合 PRD §3.3 schema (product_meta / selling_points / planning)

职责边界 (W1 Day 3):
  - 只做"规划层": 产品文案 → 结构化 planning JSON
  - 不触碰 refine_processor.py (旧管线保持不变)
  - 不跑 gpt-image-2 生图 (W2 才做)
  - DeepSeek 国内 API 绕 Clash 代理 (铁律, 见 MEMORY)

失败策略:
  - API HTTP 错误 / 网络错误 / JSON 解析错误 → 重试 1 次
  - JSON schema 验证失败 (缺字段 / 枚举越界) → 重试 1 次
  - 超过重试次数 → 抛 PlannerError

P2 后处理:
  - 过滤"产品名当独立卖点"的条目 (W2 发现的新 bug)
  - 同步 block_order 和 total_blocks
"""
from __future__ import annotations
import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

from ai_refine_v2.prompts.planner import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE


# ── 常量 ────────────────────────────────────────────────────────
_API_URL = "https://api.deepseek.com/v1/chat/completions"
_MODEL_DEFAULT = "deepseek-chat"
_TIMEOUT = 120
_TEMPERATURE = 0.1
_MAX_TOKENS = 4096
_UA = "ai-refine-v2-planner/1.0"

_VALID_CATEGORIES = ("设备类", "耗材类", "工具类")
_VALID_VISUAL_TYPES = ("product_in_scene", "product_closeup", "concept_visual")
_VALID_PRIORITIES = ("high", "medium", "low")


# ── 异常 ────────────────────────────────────────────────────────
class PlannerError(RuntimeError):
    """规划层失败 (API / 解析 / schema 验证 超过重试次数)."""


# ── HTTP 客户端 (urllib + 显式关代理 - DeepSeek 国内 API 禁走 Clash) ──
def _http_post_deepseek(body: dict, api_key: str) -> dict:
    """POST JSON 到 DeepSeek. 返回原始 response dict.

    关代理是必须的: 国内 API 被 Clash 代理会静默超时或 502.
    参考 MEMORY: feedback_proxy_deepseek.md + app.py:2639.
    """
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(
        _API_URL,
        method="POST",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": _UA,
        },
    )
    with opener.open(req, timeout=_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


# ── LLM 响应解析 ────────────────────────────────────────────────
def _extract_json(raw: str) -> dict:
    """从 LLM 文本响应中剥离 ```json``` + 从首个 { 截取, 再 json.loads."""
    raw = raw.strip()
    if "```" in raw:
        m = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
        if m:
            raw = m.group(1).strip()
    if not raw.startswith("{"):
        i = raw.find("{")
        if i >= 0:
            raw = raw[i:]
    return json.loads(raw)


def _validate_schema(parsed: dict) -> list[str]:
    """返回 warning 列表. 空列表 = 完全合规; 非空 = 触发重试."""
    warnings = []

    pm = parsed.get("product_meta") or {}
    for k in ("name", "category", "primary_color", "key_visual_parts", "proportions"):
        if not pm.get(k):
            warnings.append(f"product_meta.{k} 缺失")
    if pm.get("category") not in _VALID_CATEGORIES:
        warnings.append(f"product_meta.category 非法: {pm.get('category')!r}")
    kvp = pm.get("key_visual_parts")
    if isinstance(kvp, list) and not all(isinstance(x, str) and x.strip() for x in kvp):
        warnings.append("product_meta.key_visual_parts 含空/非字符串项")

    sps = parsed.get("selling_points") or []
    if not sps:
        warnings.append("selling_points 为空")
    elif len(sps) > 8:
        warnings.append(f"selling_points 超上限 {len(sps)} > 8")
    for i, sp in enumerate(sps):
        if sp.get("visual_type") not in _VALID_VISUAL_TYPES:
            warnings.append(f"selling_points[{i}].visual_type 非法: {sp.get('visual_type')!r}")
        if sp.get("priority") not in _VALID_PRIORITIES:
            warnings.append(f"selling_points[{i}].priority 非法: {sp.get('priority')!r}")
        if not sp.get("text") or not isinstance(sp.get("text"), str):
            warnings.append(f"selling_points[{i}].text 缺失或非字符串")

    pl = parsed.get("planning") or {}
    for k in ("total_blocks", "block_order", "hero_scene_hint"):
        if pl.get(k) in (None, "", []):
            warnings.append(f"planning.{k} 缺失")

    return warnings


# ── P2 过滤器: 移除产品名当独立卖点的条目 ────────────────────────
def _filter_product_name_redundant(parsed: dict) -> tuple[dict, list[int]]:
    """过滤 selling_points 中跟 product_meta.name 重复的条目.

    判定依据 (与 W2 发现的 bug 对应):
      若卖点 text 前 15 个字符包含 product_name 的首个 token (通常是型号,
      如 "PC-80" / "DZ600M"), 判定为"产品名/型号重复", 从 selling_points
      和 planning.block_order 中都移除.

    示例命中:
      product_name = "PC-80 便携手持工业吸尘器"
      first_token = "PC-80"
      sp[0].text = "PC-80 便携手持工业吸尘器" → "PC-80" 在前 15 字 → 移除

    不会误杀:
      product_name = "DZ600M 无人水面清洁机"
      first_token = "DZ600M"
      sp[0].text = "螺旋清污机构清污效率提升 3 倍" → 前 15 字无 "DZ600M" → 保留

    返回:
      (过滤后的 parsed, 被移除的 idx 列表)
    """
    pm = parsed.get("product_meta") or {}
    product_name = (pm.get("name") or "").strip()
    if not product_name:
        return parsed, []

    # 型号通常是首个 token (空格 / 连字符 / 中文逗号分隔)
    first_token = re.split(r"[\s,，]", product_name, maxsplit=1)[0]
    if not first_token or len(first_token) < 2:
        return parsed, []

    sps = parsed.get("selling_points") or []
    kept = []
    removed_idx = []
    for sp in sps:
        text = (sp.get("text") or "").strip()
        # 前 15 个字符含型号 → 认为是产品名重复
        if first_token in text[:15]:
            removed_idx.append(sp.get("idx"))
            continue
        kept.append(sp)

    if not removed_idx:
        return parsed, []

    # 同步 planning.block_order 移除对应 selling_point_X
    removed_refs = {f"selling_point_{i}" for i in removed_idx if i is not None}
    planning = parsed.get("planning") or {}
    order = planning.get("block_order") or []
    new_order = [b for b in order if b not in removed_refs]

    parsed["selling_points"] = kept
    parsed["planning"] = {
        **planning,
        "block_order": new_order,
        "total_blocks": len(new_order),
    }
    return parsed, removed_idx


# ── 对外主函数 ──────────────────────────────────────────────────
def plan(
    product_text: str,
    product_image_url: Optional[str] = None,
    user_opts: Optional[dict] = None,
    api_key: Optional[str] = None,
    model: str = _MODEL_DEFAULT,
    max_retries: int = 1,
    http_fn: Optional[Callable[[dict, str], dict]] = None,
) -> dict:
    """产品文案 → DeepSeek 规划 JSON.

    Args:
        product_text: 产品文案原文 (不能为空)
        product_image_url: 产品图 URL, 可选. W1 不用, 仅在 prompt 里提 hint;
                           W2 接 gpt-image-2 时才真用.
        user_opts: {"force_vs": bool, "force_scenes": bool, "force_specs": bool}
        api_key: DeepSeek API key. None 时从 env DEEPSEEK_API_KEY 读.
        model: DeepSeek 模型名, 默认 deepseek-chat
        max_retries: API / 解析 / schema 任一失败时的重试次数
        http_fn: 注入点, 测试时传 mock; 生产走默认 _http_post_deepseek

    Returns:
        dict, PRD §3.3 schema (product_meta / selling_points / planning)
        已做 P2 过滤. 若过滤掉卖点, 会 stdout 打日志.

    Raises:
        PlannerError: 参数非法 / 超过 max_retries 仍失败
    """
    if not product_text or not product_text.strip():
        raise PlannerError("product_text 不能为空")

    use_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not use_key:
        raise PlannerError("未配置 DEEPSEEK_API_KEY (传参或设 env var)")

    opts = user_opts or {}
    image_hint = product_image_url or "(暂无, 请从文案和品类推断视觉特征)"

    user_prompt = USER_PROMPT_TEMPLATE.format(
        product_text=product_text.strip(),
        product_image_hint=image_hint,
        force_vs=str(opts.get("force_vs", False)).lower(),
        force_scenes=str(opts.get("force_scenes", False)).lower(),
        force_specs=str(opts.get("force_specs", False)).lower(),
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": _TEMPERATURE,
        "max_tokens": _MAX_TOKENS,
    }

    post_fn = http_fn or _http_post_deepseek
    last_err = None

    for attempt in range(max_retries + 1):
        try:
            resp = post_fn(payload, use_key)
            raw_content = resp["choices"][0]["message"]["content"]
            parsed = _extract_json(raw_content)
            schema_warnings = _validate_schema(parsed)
            if schema_warnings:
                last_err = f"schema 不合规: {schema_warnings}"
                if attempt < max_retries:
                    print(f"[planner] attempt {attempt+1} schema 失败, 重试: {last_err}")
                    time.sleep(0.5)
                    continue
                raise PlannerError(last_err)

            # P2 过滤
            parsed, removed = _filter_product_name_redundant(parsed)
            if removed:
                print(f"[planner:filter] 跳过 {len(removed)} 个产品名重复卖点 idx={removed}")

            return parsed

        except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError,
                KeyError, TypeError) as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt < max_retries:
                print(f"[planner] attempt {attempt+1} 失败, 重试: {last_err}")
                time.sleep(1)
                continue
            raise PlannerError(f"API/解析失败 (重试 {max_retries} 次后): {last_err}") from e

    # 逻辑上不可达
    raise PlannerError(f"unreachable: last_err={last_err}")
