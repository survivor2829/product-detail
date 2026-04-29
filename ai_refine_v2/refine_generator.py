"""AI 精修 v2 · gpt-image-2 生图层 (W2 Day 3-5 实现).

职责:
  1. planning JSON → 每 block 按 visual_type 渲染 prompt (调 prompts.generator.render)
  2. 并发调 APIMart gpt-image-2 (thinking=medium, 默认并发度 3)
  3. 分层失败策略 (PRD §7):
     - Hero 失败 (重试 max_retries_hero 次仍挂) → raise HeroFailure → 整单 fail
     - 卖点图失败 (重试 max_retries_sp 次仍挂) → BlockResult(placeholder=True), 不阻塞整单
  4. 成本累计 + 端到端耗时 (存 GenerationResult)

注入点 (单测用):
  api_call_fn: (prompt, image_data_url, api_key, thinking, size) -> image_url
               生产用 _default_api_call (submit + poll). 测试传 mock.

对外:
  from ai_refine_v2.refine_generator import (
      generate, BlockResult, GenerationResult, HeroFailure
  )

历史:
  W2 Day 1 (2026-04-23): 骨架 + dataclass + NotImplementedError 桩
  W2 Day 3-5 (2026-04-24): HTTP/并发/重试/成本/注入点全部落地
"""
from __future__ import annotations
import base64
import concurrent.futures
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from ai_refine_v2.prompts.generator import render
from ai_refine_v2.refine_planner import _VALID_ROLES_V2


# ── 常量 ────────────────────────────────────────────────────────
_APIMART_BASE = "https://api.apimart.ai/v1"
_APIMART_MODEL = "gpt-image-2"
_APIMART_SIZE_DEFAULT = "1:1"
_POLL_INTERVAL_S = 3
_POLL_TIMEOUT_S = 240
_COST_PER_CALL_RMB = 0.70  # gpt-image-2 + thinking=medium
_UA = (
    "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


# ── 数据结构 ────────────────────────────────────────────────────
@dataclass
class BlockResult:
    """单个 block 的生成结果. 无论成功失败都记录.

    Attributes:
        block_id: "hero" / "selling_point_N" / "force_vs" / "force_scenes_M" / ...
        visual_type: 对应 prompts/generator.py 的三选一
        prompt: 实际送给 gpt-image-2 的完整 prompt 字符串
        image_url: 成功时 APIMart 返回的图 URL, 失败则 None
        error: 失败原因 (API 错误 / timeout / 内容拒绝等)
        placeholder: True = 走了"best-effort 降级",上层渲染时要用占位图或跳过.
                     False = 真实生成的 AI 图 (image_url 非空) 或 Hero 彻底失败 (已 raise).
    """
    block_id: str
    visual_type: str
    prompt: str
    image_url: Optional[str] = None
    error: Optional[str] = None
    placeholder: bool = False


@dataclass
class GenerationResult:
    """一次 generate() 调用的完整结果.

    Attributes:
        blocks: 所有 block 的结果数组, 按 planning.block_order 顺序 (ThreadPool 乱序结果会在末尾重排)
        hero_success: Hero 是否成功生成. False → 整单 fail 前的状态 (调用者一般拿不到, 因为会 raise)
        total_cost_rmb: 本次累计成本 (人民币, 按成功的 APIMart 调用数 × cost_per_call_rmb)
        total_elapsed_s: 端到端耗时 (秒, 从 generate() 进入到返回)
        errors: 所有失败的 "block_id: reason" 字符串, 供前端 debug
    """
    blocks: list[BlockResult] = field(default_factory=list)
    hero_success: bool = False
    total_cost_rmb: float = 0.0
    total_elapsed_s: float = 0.0
    errors: list[str] = field(default_factory=list)


class HeroFailure(RuntimeError):
    """Hero 屏生成失败 → PRD §7 规定整单 fail, 全额退款.

    Raises 时机: Hero block 重试 max_retries_hero 次后仍挂.
    上层 (batch_processor / refine_orchestrator) 捕获后应:
      1. 标记该产品批次为 failed
      2. 不保留任何已生成的其它屏 (卖点图/强制屏), 避免"残次产品"
      3. 退款 / 通知用户
    """


# ── HTTP 底层 (私有) ────────────────────────────────────────────
def _http_post_json(
    url: str, payload: dict, api_key: str, timeout: int = 90,
) -> tuple[int, Any]:
    """POST JSON, 默认读 env HTTP_PROXY (APIMart 需要走代理).

    返回 (status_code, parsed_body | raw_text). HTTPError 时也返错误 body 而非 raise,
    便于 submit 层精细判断 APIMart 的自定义 code 字段.
    """
    req = urllib.request.Request(
        url, method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": _UA,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8")
            try:
                return r.status, json.loads(body)
            except json.JSONDecodeError:
                return r.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body


def _http_get_json(url: str, api_key: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        url, method="GET",
        headers={"Authorization": f"Bearer {api_key}", "User-Agent": _UA},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ── APIMart submit / poll (私有) ────────────────────────────────
def _submit_image_task(
    prompt: str,
    image_data_url: Optional[str],
    api_key: str,
    thinking: str = "medium",
    size: str = _APIMART_SIZE_DEFAULT,
) -> str:
    """提交 gpt-image-2 任务到 APIMart, 返回 task_id."""
    payload: dict[str, Any] = {
        "model": _APIMART_MODEL,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "thinking": thinking,
        "reasoning_effort": thinking,
    }
    if image_data_url:
        payload["image_urls"] = [image_data_url]

    code, body = _http_post_json(
        f"{_APIMART_BASE}/images/generations", payload, api_key,
    )
    if code != 200 or not isinstance(body, dict) or body.get("code") != 200:
        raise RuntimeError(f"APIMart submit HTTP {code}: {body}")
    tasks = body.get("data") or []
    if not tasks or not tasks[0].get("task_id"):
        raise RuntimeError(f"APIMart 响应缺 task_id: {body}")
    return tasks[0]["task_id"]


def _poll_image_task(
    task_id: str,
    api_key: str,
    poll_interval: int = _POLL_INTERVAL_S,
    poll_timeout: int = _POLL_TIMEOUT_S,
) -> str:
    """轮询 APIMart task 直到 completed, 返回 image_url. 失败/超时抛异常."""
    t0 = time.time()
    while True:
        elapsed = time.time() - t0
        if elapsed > poll_timeout:
            raise TimeoutError(
                f"APIMart 轮询超时 {poll_timeout}s, task_id={task_id}"
            )
        data = _http_get_json(
            f"{_APIMART_BASE}/tasks/{task_id}?language=en", api_key,
        )
        node = data.get("data") or data
        status = node.get("status")
        if status == "completed":
            images = (node.get("result") or {}).get("images") or []
            if not images:
                raise RuntimeError(f"APIMart completed 但无 images: {node}")
            url = images[0].get("url")
            if isinstance(url, list):
                url = url[0] if url else None
            if not url:
                raise RuntimeError(f"APIMart completed 但无 url: {images}")
            return url
        if status in ("failed", "cancelled"):
            raise RuntimeError(f"APIMart 任务 {status}: {node}")
        time.sleep(poll_interval)


def _default_api_call(
    prompt: str,
    image_data_url: Optional[str],
    api_key: str,
    thinking: str = "medium",
    size: str = _APIMART_SIZE_DEFAULT,
) -> str:
    """生产默认: submit + poll. 单测注入 mock 时替换此函数.

    签名约束 (ApiCallFn):
        (prompt, image_data_url, api_key, thinking, size) -> image_url
    """
    task_id = _submit_image_task(
        prompt, image_data_url, api_key, thinking=thinking, size=size,
    )
    return _poll_image_task(task_id, api_key)


ApiCallFn = Callable[[str, Optional[str], str, str, str], str]


# ── 工具: 产品图 → data URL ────────────────────────────────────
def _to_data_url(path_or_url: str) -> str:
    """路径/URL 规范化到可喂 APIMart 的字符串.

    - data:... → 原样返回
    - http(s):// → 原样返回 (APIMart 支持远程 URL)
    - 本地路径 → 读文件, base64 编码为 data URL
    """
    if path_or_url.startswith(("data:", "http://", "https://")):
        return path_or_url
    p = Path(path_or_url)
    raw = p.read_bytes()
    mime, _ = mimetypes.guess_type(p.name)
    if not mime:
        mime = "image/png"
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


# ── Block 展开 + prompt 渲染 ───────────────────────────────────
def _build_blocks(planning: dict) -> list[dict]:
    """planning.block_order → [{block_id, visual_type, is_hero, selling_point}, ...]"""
    sps_by_idx = {sp["idx"]: sp for sp in planning.get("selling_points", [])}
    pl = planning.get("planning", {})
    result: list[dict] = []
    for bid in pl.get("block_order", []):
        if bid == "hero":
            result.append({
                "block_id": "hero",
                "visual_type": "product_in_scene",
                "is_hero": True,
                "selling_point": None,
            })
        elif bid.startswith("selling_point_"):
            try:
                idx = int(bid.split("_")[-1])
            except ValueError:
                continue
            sp = sps_by_idx.get(idx)
            if not sp:
                continue
            result.append({
                "block_id": bid,
                "visual_type": sp["visual_type"],
                "is_hero": False,
                "selling_point": sp,
            })
    return result


def _render_prompt_for_block(block: dict, planning: dict) -> str:
    """按 visual_type 调对应 Jinja2 模板, 全部参数从 planning 取."""
    pm = planning["product_meta"]
    pl = planning["planning"]
    vt = block["visual_type"]

    if vt == "product_in_scene":
        if block["is_hero"]:
            scene = pl.get("hero_scene_hint") or "product in application scene"
            sp_for_context = {"text": "hero shot"}
            human_hint = "operator with tablet reviewing real-time data"
        else:
            sp = block["selling_point"]
            scene = sp.get("text") or "product in scene"
            sp_for_context = sp
            human_hint = ""
        return render(
            "product_in_scene",
            product=pm, scene=scene, hero=block["is_hero"],
            human_hint=human_hint, selling_point=sp_for_context,
        )

    if vt == "product_closeup":
        sp = block["selling_point"]
        # focus_part 优先用 key_visual_parts 首条英文 phrase (更适合特写),
        # 否则回退用卖点 text (中文也可, gpt-image-2 能理解).
        key_parts = pm.get("key_visual_parts") or []
        focus_part = (key_parts[0] if key_parts else None) or sp.get("text", "key part")
        return render("product_closeup", product=pm, focus_part=focus_part)

    if vt == "concept_visual":
        return render("concept_visual", selling_point=block["selling_point"])

    raise ValueError(f"unknown visual_type: {vt}")


# ── 单 block 生成 (含重试) ─────────────────────────────────────
def _generate_one_block(
    block: dict,
    planning: dict,
    product_cutout_url: Optional[str],
    api_key: str,
    api_call_fn: ApiCallFn,
    max_retries: int,
    thinking: str,
    size: str,
) -> tuple[BlockResult, float]:
    """生成单个 block, 内部做重试. 返回 (BlockResult, 实际累计成本).

    成功返 image_url 且成本 = cost_per_call_rmb.
    重试耗尽返 image_url=None, 成本 = 0 (失败调用不计费).

    NOTE: placeholder 标记由上层 generate() 打 (只对 SP 失败打,
          Hero 失败直接 raise HeroFailure 不走 placeholder 路径).
    """
    bid = block["block_id"]
    vt = block["visual_type"]

    try:
        prompt = _render_prompt_for_block(block, planning)
    except Exception as e:
        # prompt 渲染失败 → 不重试, 直接返错 (typically StrictUndefined bug)
        return (
            BlockResult(
                block_id=bid, visual_type=vt,
                prompt="(render failed)",
                image_url=None,
                error=f"render 失败: {type(e).__name__}: {e}",
                placeholder=False,
            ),
            0.0,
        )

    # product_in_scene + product_closeup 需要参考图 (PRESERVE 段)
    # concept_visual 不需要
    image_data_url: Optional[str] = None
    if vt in ("product_in_scene", "product_closeup") and product_cutout_url:
        try:
            image_data_url = _to_data_url(product_cutout_url)
        except Exception as e:
            # 参考图转换失败不致命, 降级纯文生 (会丢失产品还原但不 crash)
            print(f"[gen][{bid}] 参考图转 data URL 失败, 降级纯文生: {e}")

    last_err = None
    attempts = 0
    while attempts <= max_retries:
        try:
            url = api_call_fn(prompt, image_data_url, api_key, thinking, size)
            return (
                BlockResult(
                    block_id=bid, visual_type=vt,
                    prompt=prompt, image_url=url,
                    error=None, placeholder=False,
                ),
                _COST_PER_CALL_RMB,
            )
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            attempts += 1
            if attempts <= max_retries:
                print(f"[gen][{bid}] attempt {attempts} 失败, 重试: {last_err}")
                time.sleep(1)
                continue
            break

    # 重试耗尽
    return (
        BlockResult(
            block_id=bid, visual_type=vt,
            prompt=prompt, image_url=None,
            error=f"重试 {max_retries} 次后仍失败: {last_err}",
            placeholder=False,
        ),
        0.0,
    )


# ── 主入口 ──────────────────────────────────────────────────────
def generate(
    planning: dict,
    product_cutout_url: Optional[str] = None,
    api_key: Optional[str] = None,
    thinking: str = "medium",
    size: str = _APIMART_SIZE_DEFAULT,
    concurrency: int = 3,
    max_retries_hero: int = 2,
    max_retries_sp: int = 1,
    api_call_fn: Optional[ApiCallFn] = None,
    cost_per_call_rmb: float = _COST_PER_CALL_RMB,
) -> GenerationResult:
    """planning JSON → 一组 gpt-image-2 图片 URL.

    执行顺序:
      1. Hero 同步跑 (最多 max_retries_hero 次重试).
         失败 → raise HeroFailure (PRD §7 整单 fail).
      2. 其它 block 在 ThreadPoolExecutor(max_workers=concurrency) 里并发跑,
         每个 block 最多 max_retries_sp 次重试.
         失败 → BlockResult(placeholder=True), 不阻塞整单.
      3. result.blocks 按 planning.block_order 重排 (因 ThreadPool 无序).

    Args:
        planning: ai_refine_v2.refine_planner.plan() 的返回
        product_cutout_url: 产品裁图路径/URL/data URL, None 则纯文生 (PRESERVE 段效果差)
        api_key: APIMart gpt-image-2 API key. None 从 env GPT_IMAGE_API_KEY 读.
                 (api_call_fn 注入 mock 时可传任意占位字符串)
        thinking: "off" / "low" / "medium" / "high". medium 性价比最好.
        size: "1:1" / "16:9" / "3:4" 等比例字符串 (APIMart 格式)
        concurrency: SP block 并发度, APIMart 限流保护默认 3
        max_retries_hero: Hero 失败重试次数 (PRD §7 严格, 默认 2 = 最多跑 3 次)
        max_retries_sp: 卖点图失败重试次数 (PRD §7 best-effort, 默认 1 = 最多跑 2 次)
        api_call_fn: 单测注入点, 生产默认 _default_api_call (submit + poll)
                     签名: (prompt, image_data_url, api_key, thinking, size) -> image_url
        cost_per_call_rmb: 每次成功调用成本, 默认 ¥0.70

    Returns:
        GenerationResult

    Raises:
        ValueError: planning 结构不合规 / blocks 为空 / blocks[0] 非 hero
        HeroFailure: Hero 重试 max_retries_hero 次后仍失败 (PRD §7 整单 fail)
    """
    # ── 参数校验 ────────────────────────────
    if not planning or not isinstance(planning, dict):
        raise ValueError("planning 必须是非空 dict")
    for required_key in ("product_meta", "selling_points", "planning"):
        if required_key not in planning:
            raise ValueError(f"planning 结构不合规, 缺 {required_key!r}")

    use_key = api_key or os.environ.get("GPT_IMAGE_API_KEY", "").strip()
    if not use_key and api_call_fn is None:
        # 只有走真 _default_api_call 时才强制要 key. 注入 mock 时可空.
        raise ValueError("未配置 GPT_IMAGE_API_KEY (传参或设 env var)")

    call_fn: ApiCallFn = api_call_fn or _default_api_call

    result = GenerationResult()
    t_start = time.time()

    # ── 展开 blocks ─────────────────────────
    blocks = _build_blocks(planning)
    if not blocks:
        raise ValueError("planning.block_order 展开后为空, 无 block 可生成")
    if not blocks[0].get("is_hero"):
        raise ValueError(f"blocks[0] 不是 hero (block_order 第一项必须是 'hero'): {blocks[0]}")

    # 覆盖 cost_per_call_rmb (用局部常量供 _generate_one_block 知道)
    # _generate_one_block 里写的是 _COST_PER_CALL_RMB 常量, 这里可以通过参数覆盖
    # 但为保持签名简洁, 本函数内部直接算: 每次成功调用 += cost_per_call_rmb
    # _generate_one_block 返回 "1.0 或 0.0" 的布尔式成本, 然后这里乘 cost_per_call_rmb ...
    # 简化: 让 _generate_one_block 返回 (result, success_count_int), 这里乘 cost.
    # 不. 为最小改动, 保留返 cost=_COST_PER_CALL_RMB, 然后这里 rescale:
    scale = cost_per_call_rmb / _COST_PER_CALL_RMB if _COST_PER_CALL_RMB else 0.0

    # ── Step 1: Hero 同步 + 重试 ─────────────
    print(f"[gen] Hero 开始 (重试上限 {max_retries_hero})...")
    hero_res, hero_cost = _generate_one_block(
        blocks[0], planning, product_cutout_url,
        use_key, call_fn, max_retries_hero, thinking, size,
    )
    result.blocks.append(hero_res)
    result.total_cost_rmb += hero_cost * scale

    if hero_res.image_url is None:
        # Hero 彻底失败 → PRD §7 整单 fail
        result.errors.append(f"hero: {hero_res.error}")
        result.total_elapsed_s = round(time.time() - t_start, 2)
        raise HeroFailure(
            f"Hero 重试 {max_retries_hero} 次后仍失败: {hero_res.error}. "
            f"PRD §7: 已生成的其它 block 不保留 (整单 fail)."
        )

    result.hero_success = True
    print(f"[gen] Hero OK · url={str(hero_res.image_url)[:60]}...")

    # ── Step 2: SP block 并发 + 分层重试 ─────
    sp_blocks = blocks[1:]
    if not sp_blocks:
        result.total_elapsed_s = round(time.time() - t_start, 2)
        return result

    print(f"[gen] SP blocks × {len(sp_blocks)}, 并发度 {concurrency}...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(
                _generate_one_block,
                b, planning, product_cutout_url, use_key, call_fn,
                max_retries_sp, thinking, size,
            ): b
            for b in sp_blocks
        }
        for fut in concurrent.futures.as_completed(futures):
            b = futures[fut]
            try:
                br, cost = fut.result()
            except Exception as e:
                # 内部已捕获, 防御: pool 本身异常
                br = BlockResult(
                    block_id=b["block_id"], visual_type=b["visual_type"],
                    prompt="(executor error)", image_url=None,
                    error=f"{type(e).__name__}: {e}",
                    placeholder=True,
                )
                cost = 0.0

            # SP 失败 → placeholder=True (PRD §7 best-effort 降级)
            if br.image_url is None:
                br.placeholder = True
                result.errors.append(f"{br.block_id}: {br.error}")

            result.blocks.append(br)
            result.total_cost_rmb += cost * scale

    # 按 block_order 重排 (ThreadPool 完成顺序乱)
    order_map = {b["block_id"]: i for i, b in enumerate(blocks)}
    result.blocks.sort(key=lambda br: order_map.get(br.block_id, 10_000))

    result.total_elapsed_s = round(time.time() - t_start, 2)
    return result


# ──────────────────────────────────────────────────────────────────
# v2 (PRD §阶段二·任务 2.1, 2026-04-27): gpt-image-2 直出整屏
# ──────────────────────────────────────────────────────────────────
# generate_v2() 跟老 generate() 同文件并存:
#   - 老 generate (v1 schema, selling_points + visual_type 三选一) — 60 单测保护
#   - 新 generate_v2 (v2 schema, screens[] + 导演 prompt) — plan_v2 直接喂进来
#
# 共用基础设施 (不重写):
#   - _http_post_json / _http_get_json / _submit_image_task / _poll_image_task
#     / _default_api_call / _to_data_url
#   - BlockResult / GenerationResult / HeroFailure
#   - 并发 / 重试 / cost tracking 模式
#
# v2 区别:
#   - 不 _build_blocks 按 visual_type 分流, 不 _render_prompt_for_block 渲染模板
#   - 直接用 plan_v2 给的 screens[i].prompt (已是导演视角完整 prompt)
#   - size 固定 "3:4" (1536×2048 @ 2k), 不是 v1 的 "1:1"
#   - 第 1 屏 (idx=1) 严格视为 hero (整单 fail), 其他屏 SP best-effort

_V2_SIZE_DEFAULT = "3:4"  # PRD §阶段二: 1536×2048 锁定

# v3 (PRD AI_refine_v3.1 §5.2): 喂 cutout 屏的 prompt 开头注入此句, 让 gpt-image-2
# 知道 image_urls[0] 是产品参考图, 必须保留产品 silhouette / 主色 / 关键部件.
# 不喂图屏不注入 (没 image_urls, 注入这句反而误导模型). 跟 cutout_whitelist 联动.
#
# v3.2 (2026-04-29 deliberate_iron_rule_5_break_2nd): 强化版,
# 加 "EXACT original color WITHOUT ambient color shifting", 因为
# DZ70X (黑色产品) 用 v3.iter2 INJECTION_PREFIX 仍被暖色阳光环境染金色 —
# 必须显式禁掉 ambient color shifting 才能保黑色产品的颜色.
_INJECTION_PREFIX_V3 = (
    "Image 1 is the reference product cutout. Preserve the product's "
    "EXACT original color WITHOUT ambient color shifting. The product's "
    "primary color must remain unchanged regardless of lighting or "
    "background. Preserve silhouette, key visual parts, and original "
    "hue exactly. "
)

# v3.iter2 默认喂图白名单: 12 个 role 中除 FAQ 外全喂.
# 从 _VALID_ROLES_V2 单一来源派生, 避免 13th 屏型加入时手动同步漂移.
# (Scott 改动 4 修正版: spec_table / lifestyle_demo 都改回喂图)
_DEFAULT_CUTOUT_WHITELIST_V3 = _VALID_ROLES_V2 - {"FAQ"}


def _build_blocks_v2(planning_v2: dict) -> list[dict]:
    """v2 schema 的 screens[] → 内部 block dict 列表.

    跟 _build_blocks (v1) 不同, 不查 selling_points / visual_type, 直接用 screens[i].
    第 1 屏 (idx=1) 严格视为 hero (PRD §7 整单 fail 锚点).
    """
    screens = planning_v2.get("screens") or []
    blocks: list[dict] = []
    for s in screens:
        if not isinstance(s, dict):
            continue
        idx = s.get("idx")
        role = (s.get("role") or "").strip() or "screen"
        # block_id 用 idx + role 组合, 易识别 + 唯一 (assembler / pipeline_runner 引用按它)
        if isinstance(idx, int):
            bid = f"screen_{idx:02d}_{role}"
        else:
            bid = f"screen_{role}"
        blocks.append({
            "block_id": bid,
            "visual_type": role,        # role 填 visual_type 字段 (v2 不分 in_scene/closeup/concept)
            "is_hero": (idx == 1),       # 第 1 屏 (idx=1) 严格视为 hero
            "prompt": s.get("prompt") or "",
            "title": s.get("title") or "",
        })
    return blocks


def _generate_one_block_v2(
    block: dict,
    image_data_url: Optional[str],
    api_key: str,
    api_call_fn: ApiCallFn,
    max_retries: int,
    thinking: str,
    size: str,
) -> tuple[BlockResult, float]:
    """v2 单 block 生成. prompt 直接用 plan_v2 已渲染好的, 不再模板化.

    成功 → BlockResult(image_url=<url>, placeholder=False), cost = _COST_PER_CALL_RMB
    重试耗尽 → BlockResult(image_url=None, error=<reason>, placeholder=False).
              placeholder 标记由 generate_v2 打 (Hero raise, SP best-effort).

    block.prompt 必须非空 (plan_v2 _validate_schema_v2 已守门 ≥200 字符).
    image_data_url: 已转好的 data:image/...;base64,... 字符串, None = 不喂图.
    (v3.2 simplify: 由 generate_v2 在循环外一次性转好, 避免 N 次重复 base64).
    """
    bid = block["block_id"]
    vt = block.get("visual_type", "screen")
    prompt = block.get("prompt") or ""
    if not prompt.strip():
        return (
            BlockResult(
                block_id=bid, visual_type=vt,
                prompt="(empty prompt from planning_v2)",
                image_url=None,
                error="block.prompt 为空 (plan_v2 schema 校验失效?)",
                placeholder=False,
            ),
            0.0,
        )

    # v3 (PRD AI_refine_v3.1 §5.2): 喂图屏 prompt 开头注入 INJECTION_PREFIX,
    # 让 gpt-image-2 把 image_urls[0] 当形态锚点而非装饰品.
    # 不喂图屏 (image_data_url is None) 不注入, 否则误导模型脑补不存在的 Image 1.
    effective_prompt = prompt
    if image_data_url:
        effective_prompt = _INJECTION_PREFIX_V3 + prompt

    last_err = None
    attempts = 0
    while attempts <= max_retries:
        try:
            url = api_call_fn(effective_prompt, image_data_url, api_key, thinking, size)
            return (
                BlockResult(
                    block_id=bid, visual_type=vt,
                    prompt=prompt, image_url=url,
                    error=None, placeholder=False,
                ),
                _COST_PER_CALL_RMB,
            )
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            attempts += 1
            if attempts <= max_retries:
                print(f"[gen_v2][{bid}] attempt {attempts} 失败, 重试: {last_err}")
                time.sleep(1)
                continue
            break

    return (
        BlockResult(
            block_id=bid, visual_type=vt,
            prompt=prompt, image_url=None,
            error=f"重试 {max_retries} 次后仍失败: {last_err}",
            placeholder=False,
        ),
        0.0,
    )


def generate_v2(
    planning_v2: dict,
    product_cutout_url: Optional[str] = None,
    api_key: Optional[str] = None,
    thinking: str = "medium",
    size: str = _V2_SIZE_DEFAULT,
    concurrency: int = 3,
    max_retries_hero: int = 2,
    max_retries_sp: int = 1,
    api_call_fn: Optional[ApiCallFn] = None,
    cost_per_call_rmb: float = _COST_PER_CALL_RMB,
    cutout_whitelist: Optional[set[str]] = None,  # v3 (PRD AI_refine_v3.1)
) -> GenerationResult:
    """v2 schema (plan_v2 输出) → 一组 1536×2048 gpt-image-2 PNG.

    跟 v1 generate() 的核心区别:
      - 接收 v2 schema (planning_v2["screens"]), 不用 selling_points + visual_type
      - 不渲染 prompt, 直接用 screens[i].prompt (导演视角完整 prompt)
      - size 默认 "3:4" (1536×2048 @ 2k)

    保持跟 v1 一致:
      - HeroFailure 整单 fail (PRD §7), max_retries_hero 重试上限
      - SP best-effort, max_retries_sp + placeholder 降级
      - 并发 3, ThreadPool, 结果按 screens.idx 顺序
      - cost_per_call_rmb (默认 ¥0.70/张)

    Args:
        planning_v2: ai_refine_v2.refine_planner.plan_v2() 返回 dict (含 screens[])
        product_cutout_url: 产品参考图 URL/path (可选, 给了就喂 image_urls hint)
        api_key: APIMart key, None 从 env GPT_IMAGE_API_KEY 读
        api_call_fn: 单测注入点, 生产用 _default_api_call (submit + poll)
        cutout_whitelist: v3 (PRD AI_refine_v3.1) per-screen 喂图控制.
            屏型 role 集合, 仅这些 role 喂参考图.
            None (默认) = PRD v3.iter2 默认 (除 FAQ 外全喂, spec_table 改回喂图).
            空 set() = 全不喂. 自定义 set = 仅指定 role 喂.
        其他参数: 同 v1 generate()

    Returns:
        GenerationResult, blocks 按 screens.idx 顺序排序

    Raises:
        ValueError: planning_v2 不合规 / screens 为空 / 未配 key 也没 mock
        HeroFailure: 第 1 屏 (hero) 重试 max_retries_hero 次后仍失败
    """
    if not planning_v2 or not isinstance(planning_v2, dict):
        raise ValueError("planning_v2 必须是非空 dict")
    if "screens" not in planning_v2 or not isinstance(planning_v2["screens"], list):
        raise ValueError("planning_v2 缺 'screens' 字段或不是 list (期望 v2 schema)")

    use_key = api_key or os.environ.get("GPT_IMAGE_API_KEY", "").strip()
    if not use_key and api_call_fn is None:
        raise ValueError(
            "未配置 GPT_IMAGE_API_KEY (传参或设 env var); 测试场景注入 api_call_fn 也可"
        )

    call_fn: ApiCallFn = api_call_fn or _default_api_call

    # v3.iter2 默认 cutout_whitelist: 除 FAQ 外全喂 (spec_table / lifestyle_demo 都喂图).
    # 从 _VALID_ROLES_V2 单一来源派生 (_DEFAULT_CUTOUT_WHITELIST_V3), 13th 屏型加入时不需手动同步.
    if cutout_whitelist is None:
        effective_whitelist: frozenset[str] = _DEFAULT_CUTOUT_WHITELIST_V3
    else:
        effective_whitelist = frozenset(cutout_whitelist)

    # v3.2 simplify: hoist _to_data_url 出循环, 避免 N 次重复 base64 同一文件.
    # 转换失败 → 全部 block 走纯文生 (跟旧行为一致, 单 block 失败 print warning 即可).
    base_image_data_url: Optional[str] = None
    if product_cutout_url:
        try:
            base_image_data_url = _to_data_url(product_cutout_url)
        except Exception as e:
            print(f"[gen_v2] 参考图转 data URL 失败, 全部 block 降级纯文生: {e}")

    def _cutout_for(block: dict) -> Optional[str]:
        """v3: 根据 block role 决定该屏是否喂 cutout. 返回已转好的 data URL 或 None."""
        if base_image_data_url is None:
            return None
        return base_image_data_url if block.get("visual_type", "") in effective_whitelist else None

    result = GenerationResult()
    t_start = time.time()

    blocks = _build_blocks_v2(planning_v2)
    if not blocks:
        raise ValueError("planning_v2.screens 展开后为空, 无屏可生成")

    # cost 缩放 (跟 v1 一致的 trick: _generate_one_block 内部用常量 _COST_PER_CALL_RMB,
    # 这里用 cost_per_call_rmb / _COST_PER_CALL_RMB 做缩放)
    scale = cost_per_call_rmb / _COST_PER_CALL_RMB if _COST_PER_CALL_RMB else 0.0

    # ── Step 1: 第 1 屏 (Hero) 同步 + 重试 ────────
    hero_block = blocks[0]
    print(f"[gen_v2] Hero ({hero_block['block_id']}) 开始, 重试上限 {max_retries_hero}...")
    hero_res, hero_cost = _generate_one_block_v2(
        hero_block, _cutout_for(hero_block), use_key, call_fn,
        max_retries_hero, thinking, size,
    )
    result.blocks.append(hero_res)
    result.total_cost_rmb += hero_cost * scale

    if hero_res.image_url is None:
        result.errors.append(f"hero ({hero_block['block_id']}): {hero_res.error}")
        result.total_elapsed_s = round(time.time() - t_start, 2)
        raise HeroFailure(
            f"v2 Hero 重试 {max_retries_hero} 次后仍失败: {hero_res.error}. "
            f"PRD §7: 整单 fail, 已生成的其他屏不保留."
        )

    result.hero_success = True
    print(f"[gen_v2] Hero OK · url={str(hero_res.image_url)[:60]}...")

    # ── Step 2: 其他屏 (SP) 并发 + 分层重试 ───────
    sp_blocks = blocks[1:]
    if not sp_blocks:
        result.total_elapsed_s = round(time.time() - t_start, 2)
        return result

    print(f"[gen_v2] 其他屏 × {len(sp_blocks)}, 并发度 {concurrency}...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(
                _generate_one_block_v2,
                b, _cutout_for(b), use_key, call_fn,
                max_retries_sp, thinking, size,
            ): b
            for b in sp_blocks
        }
        for fut in concurrent.futures.as_completed(futures):
            b = futures[fut]
            try:
                br, cost = fut.result()
            except Exception as e:
                # ThreadPool 本身异常 (内部已捕获, 这里防御)
                br = BlockResult(
                    block_id=b["block_id"],
                    visual_type=b.get("visual_type", "screen"),
                    prompt=b.get("prompt", "(executor error)"),
                    image_url=None,
                    error=f"{type(e).__name__}: {e}",
                    placeholder=True,
                )
                cost = 0.0

            # SP 失败 → placeholder=True (PRD §7 best-effort 降级)
            if br.image_url is None:
                br.placeholder = True
                result.errors.append(f"{br.block_id}: {br.error}")

            result.blocks.append(br)
            result.total_cost_rmb += cost * scale

    # 按 screens.idx 顺序重排 (ThreadPool 完成顺序乱)
    order_map = {b["block_id"]: i for i, b in enumerate(blocks)}
    result.blocks.sort(key=lambda br: order_map.get(br.block_id, 10_000))

    result.total_elapsed_s = round(time.time() - t_start, 2)
    return result
