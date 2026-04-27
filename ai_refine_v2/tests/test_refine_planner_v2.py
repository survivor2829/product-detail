"""plan_v2 单测: 不调真 DeepSeek, 仅 mock 验证 schema 解析 + 重试逻辑.

PRD §阶段一·任务 1.1 — 新 v2 schema (style_dna + N 屏导演 prompt) 的回归保护.
跟 v1 plan() 单测共存, 两套互不影响 (60 v1 单测继续过, 这里加 v2 一组).

设计:
  - 用 mock http_fn 模拟 DeepSeek 响应, 不烧任何成本
  - 黄金 fixture _v2_sample(): 一份完整合规的 v2 dict, 各测试基于它做变异
  - 每条测试只破坏一个字段, 保证 fail message 单一可定位
"""
from __future__ import annotations

import json
import unittest
import urllib.error
from unittest import mock

from ai_refine_v2.refine_planner import (
    PlannerError,
    _validate_schema_v2,
    plan_v2,
)


# ── 黄金 fixture (合规的 v2 schema dict) ────────────────────────────
def _v2_sample(screen_count: int = 7) -> dict:
    """一份合规的 v2 schema 样本. 测试通过 deepcopy + 改字段做边界 case."""
    screens = []
    for i in range(1, screen_count + 1):
        screens.append({
            "idx": i,
            "role": [
                "hero", "feature_wall", "scenario", "vs_compare",
                "detail_zoom", "spec_table", "value_story",
                "brand_quality", "value_story", "brand_quality",
            ][(i - 1) % 10],
            "title": f"屏 {i} 标题",
            # 长 prompt (> 200 字符), 模拟导演视角
            "prompt": (
                "Wide low-angle hero shot of an industrial yellow water-cleaning "
                "robot cruising on a calm urban river at golden hour. The product "
                "fills the center-right of the frame, two crane silhouettes blurred "
                "in the distance. A bold white display headline anchors the upper-left "
                "with generous negative space. Cinematic lens flare on water ripples, "
                "deep slate-blue sky transitions to amber on horizon. Magazine-cover "
                f"composition with editorial confidence. (screen {i})"
            ),
        })
    return {
        "product_meta": {
            "name": "DZ600M 无人水面清洁机",
            "category": "设备类",
            "primary_color": "industrial yellow with black auger trim",
            "key_visual_parts": [
                "industrial yellow body",
                "two black cylindrical auger floats",
                "transparent dome camera housing",
            ],
        },
        "style_dna": {
            "color_palette": "industrial yellow + slate gray + amber highlight palette",
            "lighting": "cinematic low-angle golden-hour key light with steel-blue rim",
            "composition_style": "asymmetric editorial layout with large negative space top-left",
            "mood": "confident B2B premium industrial mood",
            "typography_hint": "modern condensed sans-serif headlines",
            "unified_visual_treatment": "documentary photo-realism dominant; HUD overlays on photo backgrounds; shared film grain + color grading + typography family",
        },
        "screen_count": screen_count,
        "screens": screens,
    }


def _mock_http(response_dict: dict):
    """构造 mock http_fn: 返 OpenAI-style chat completions response.

    response_dict 是 plan_v2 期望从 .choices[0].message.content 解析出来的 JSON.
    """
    def _fn(payload: dict, api_key: str) -> dict:
        return {
            "choices": [{
                "message": {"content": json.dumps(response_dict, ensure_ascii=False)}
            }],
        }
    return _fn


# ──────────────────────────────────────────────────────────────────
# A: schema validation — 合规样本不报警, 各种破坏分别报对警
# ──────────────────────────────────────────────────────────────────
class TestValidateSchemaV2Pass(unittest.TestCase):
    """合规样本应返空 warning list."""

    def test_minimal_valid_sample_no_warnings(self):
        self.assertEqual(_validate_schema_v2(_v2_sample(screen_count=6)), [])

    def test_max_screens_10_no_warnings(self):
        self.assertEqual(_validate_schema_v2(_v2_sample(screen_count=10)), [])


class TestValidateSchemaV2ProductMeta(unittest.TestCase):
    """product_meta 破坏 → 对应 warning."""

    def test_missing_product_meta(self):
        d = _v2_sample()
        d.pop("product_meta")
        w = _validate_schema_v2(d)
        self.assertTrue(any("product_meta 缺失" in x for x in w))

    def test_illegal_category(self):
        d = _v2_sample()
        d["product_meta"]["category"] = "餐具类"
        w = _validate_schema_v2(d)
        self.assertTrue(any("category 非法" in x for x in w))

    def test_empty_key_visual_parts(self):
        d = _v2_sample()
        d["product_meta"]["key_visual_parts"] = []
        w = _validate_schema_v2(d)
        self.assertTrue(any("key_visual_parts 缺失或空列表" in x for x in w))


class TestValidateSchemaV2StyleDna(unittest.TestCase):
    """style_dna 5 字段破坏 → 警告对应字段."""

    def test_missing_style_dna(self):
        d = _v2_sample()
        d.pop("style_dna")
        w = _validate_schema_v2(d)
        self.assertTrue(any("style_dna 缺失或非 dict" in x for x in w))

    def test_color_palette_too_short(self):
        d = _v2_sample()
        d["style_dna"]["color_palette"] = "blue, white"  # 11 字符 < 20
        w = _validate_schema_v2(d)
        self.assertTrue(any("color_palette 过短" in x for x in w))

    def test_mood_too_short(self):
        d = _v2_sample()
        d["style_dna"]["mood"] = "cool"  # 4 < 12
        w = _validate_schema_v2(d)
        self.assertTrue(any("mood 过短" in x for x in w))

    def test_each_field_required(self):
        for k in ("color_palette", "lighting", "composition_style", "mood",
                  "typography_hint", "unified_visual_treatment"):
            with self.subTest(field=k):
                d = _v2_sample()
                d["style_dna"].pop(k)
                w = _validate_schema_v2(d)
                self.assertTrue(
                    any(k in x and "缺失" in x for x in w),
                    f"删除 style_dna.{k} 应触发 '缺失' 警告, 实际 warnings={w}",
                )

    def test_unified_visual_treatment_required(self):
        """v2 PRD §阶段五·step2 修补: unified_visual_treatment 必填 (准则 2)."""
        d = _v2_sample()
        d["style_dna"].pop("unified_visual_treatment")
        w = _validate_schema_v2(d)
        self.assertTrue(
            any("unified_visual_treatment" in x and "缺失" in x for x in w),
            f"删除 unified_visual_treatment 应触发 '缺失' 警告, warnings={w}",
        )

    def test_unified_visual_treatment_too_short(self):
        """unified_visual_treatment 阈值 30 字符 (比 typography_hint 8 严, 强制有针对性)."""
        d = _v2_sample()
        d["style_dna"]["unified_visual_treatment"] = "short text"  # 10 < 30
        w = _validate_schema_v2(d)
        self.assertTrue(
            any("unified_visual_treatment" in x and "过短" in x for x in w),
            f"unified_visual_treatment < 30 应触发 '过短' 警告, warnings={w}",
        )


class TestValidateSchemaV2Screens(unittest.TestCase):
    """screens 数组破坏."""

    def test_screen_count_below_min(self):
        d = _v2_sample()
        d["screen_count"] = 5
        d["screens"] = d["screens"][:5]
        w = _validate_schema_v2(d)
        self.assertTrue(any("screen_count" in x and "[6,10]" in x for x in w))

    def test_screen_count_above_max(self):
        d = _v2_sample(screen_count=10)
        d["screen_count"] = 11
        # screens 仍 10 个, 触发 "长度不一致"
        w = _validate_schema_v2(d)
        self.assertTrue(any("screen_count" in x for x in w))

    def test_screens_count_mismatch(self):
        d = _v2_sample(screen_count=8)
        d["screens"] = d["screens"][:6]  # 留 6 屏但 screen_count=8
        w = _validate_schema_v2(d)
        self.assertTrue(any("不一致" in x for x in w))

    def test_screen_idx_wrong_order(self):
        d = _v2_sample()
        d["screens"][2]["idx"] = 99  # 应为 3
        w = _validate_schema_v2(d)
        self.assertTrue(any("screens[2].idx 应为 3" in x for x in w))

    def test_prompt_too_short_seo_list(self):
        d = _v2_sample()
        d["screens"][0]["prompt"] = "industrial robot, 8K, sharp focus"  # 33 < 200
        w = _validate_schema_v2(d)
        self.assertTrue(any("prompt 过短" in x for x in w))

    def test_screen_missing_role(self):
        d = _v2_sample()
        d["screens"][0].pop("role")
        w = _validate_schema_v2(d)
        self.assertTrue(any("screens[0].role" in x for x in w))


# ──────────────────────────────────────────────────────────────────
# B: plan_v2 主入口 — mock http_fn, 端到端 schema 解析
# ──────────────────────────────────────────────────────────────────
class TestPlanV2HappyPath(unittest.TestCase):

    def test_returns_parsed_v2_dict(self):
        sample = _v2_sample()
        result = plan_v2(
            product_text="DZ600M 无人水面清洁机, 续航 8 小时...",
            product_image_url="https://example.com/p.jpg",
            product_title="DZ600M",
            api_key="dummy",
            http_fn=_mock_http(sample),
        )
        self.assertEqual(result["product_meta"]["name"], sample["product_meta"]["name"])
        self.assertEqual(result["screen_count"], sample["screen_count"])
        self.assertEqual(len(result["screens"]), sample["screen_count"])
        # 关键: 解析出来的就是合规 v2 dict
        self.assertEqual(_validate_schema_v2(result), [])

    def test_no_product_image_url_still_works(self):
        result = plan_v2(
            product_text="DZ600M 无人水面清洁机, 续航 8 小时...",
            product_image_url=None,
            product_title=None,
            api_key="dummy",
            http_fn=_mock_http(_v2_sample()),
        )
        self.assertEqual(_validate_schema_v2(result), [])

    def test_payload_uses_v2_system_prompt(self):
        """plan_v2 的 payload 必须用 SYSTEM_PROMPT_V2 (含'导演视角'关键词), 不是 v1."""
        captured: dict = {}

        def _capture(payload, api_key):
            captured["payload"] = payload
            return _mock_http(_v2_sample())(payload, api_key)

        plan_v2(
            product_text="x", api_key="dummy", http_fn=_capture,
        )
        sys_msg = captured["payload"]["messages"][0]
        self.assertEqual(sys_msg["role"], "system")
        # SYSTEM_PROMPT_V2 应含"导演视角"和"style_dna"两个关键概念
        self.assertIn("导演视角", sys_msg["content"])
        self.assertIn("style_dna", sys_msg["content"])
        # 不应含 v1 的"卖点 → 视觉"判定逻辑
        self.assertNotIn("visual_type", sys_msg["content"])

    def test_payload_uses_higher_temperature(self):
        """v2 默认 temperature=0.7, 不是 v1 的 0.1."""
        captured: dict = {}

        def _capture(payload, api_key):
            captured["payload"] = payload
            return _mock_http(_v2_sample())(payload, api_key)

        plan_v2(product_text="x", api_key="dummy", http_fn=_capture)
        self.assertAlmostEqual(captured["payload"]["temperature"], 0.7, places=2)

    def test_system_prompt_v2_warns_against_brand_logos(self):
        """SYSTEM_PROMPT_V2 必须含品牌 logo 禁令 (PRD §明确排除 §2)."""
        from ai_refine_v2.prompts.planner import SYSTEM_PROMPT_V2
        self.assertIn("logo", SYSTEM_PROMPT_V2.lower())
        self.assertIn("失真", SYSTEM_PROMPT_V2)
        # 应明确说由客户后期合成
        self.assertTrue(
            "客户" in SYSTEM_PROMPT_V2 and "合成" in SYSTEM_PROMPT_V2,
            "SYSTEM_PROMPT_V2 应说明 logo 由客户后期合成",
        )

    def test_system_prompt_v2_teaches_chinese_text_quoting(self):
        """SYSTEM_PROMPT_V2 必须教 DeepSeek 用「」标记画面文字 + 强调清晰准确."""
        from ai_refine_v2.prompts.planner import SYSTEM_PROMPT_V2
        # 「」必须出现 (中文角括号示范)
        self.assertIn("「」", SYSTEM_PROMPT_V2)
        # 必须含"清晰/准确/sharp/accurate"任一关键词强调
        clarity_keywords = ("sharp", "accurate", "清晰", "no typos")
        hits = [k for k in clarity_keywords if k.lower() in SYSTEM_PROMPT_V2.lower()]
        self.assertTrue(
            len(hits) >= 2,
            f"SYSTEM_PROMPT_V2 至少应含 2 个清晰度关键词, 实际命中 {hits}",
        )

    def test_system_prompt_v2_includes_information_density_rule(self):
        """准则 6: 信息密度规则必须在 (2026-04-27 stage5 step2 修补)."""
        from ai_refine_v2.prompts.planner import SYSTEM_PROMPT_V2
        self.assertIn("信息单元", SYSTEM_PROMPT_V2)
        self.assertIn("数据卡", SYSTEM_PROMPT_V2)
        self.assertIn("spec chip", SYSTEM_PROMPT_V2)
        # hero 是特例必须明说 (不强求)
        self.assertIn("hero 屏不强求", SYSTEM_PROMPT_V2)

    def test_system_prompt_v2_includes_layout_mapping_table(self):
        """准则 7: 屏型 → layout 类型映射表必须在 (2026-04-27 stage5 step2 修补)."""
        from ai_refine_v2.prompts.planner import SYSTEM_PROMPT_V2
        # 3 类 layout 类型关键词 (中文)
        self.assertIn("聚焦镜头", SYSTEM_PROMPT_V2)
        self.assertIn("拼贴", SYSTEM_PROMPT_V2)
        self.assertIn("混合", SYSTEM_PROMPT_V2)
        # 关键 prompt 词汇 (英文, 防 DeepSeek 写成中文)
        self.assertIn("triptych", SYSTEM_PROMPT_V2)                  # scenario
        self.assertIn("split-screen comparison", SYSTEM_PROMPT_V2)   # vs_compare
        self.assertIn("HUD overlays", SYSTEM_PROMPT_V2)              # value_story
        self.assertIn("grid layout", SYSTEM_PROMPT_V2)               # feature_wall


class TestPlanV2InputValidation(unittest.TestCase):

    def test_empty_text_raises(self):
        with self.assertRaises(PlannerError) as ctx:
            plan_v2(product_text="", api_key="dummy")
        self.assertIn("不能为空", str(ctx.exception))

    def test_whitespace_only_raises(self):
        with self.assertRaises(PlannerError):
            plan_v2(product_text="   \n\t  ", api_key="dummy")

    def test_no_api_key_raises(self):
        import os as _os
        old = _os.environ.pop("DEEPSEEK_API_KEY", None)
        try:
            with self.assertRaises(PlannerError) as ctx:
                plan_v2(product_text="dummy text", api_key=None)
            self.assertIn("DEEPSEEK_API_KEY", str(ctx.exception))
        finally:
            if old is not None:
                _os.environ["DEEPSEEK_API_KEY"] = old


class TestPlanV2RetryLogic(unittest.TestCase):

    def test_retries_on_http_error_then_raises(self):
        """两次 HTTPError → PlannerError."""
        class _FakeHTTPError(urllib.error.HTTPError):
            def __init__(self):
                super().__init__("http://x", 500, "err", {}, None)
        calls = {"n": 0}

        def _failing(payload, key):
            calls["n"] += 1
            raise _FakeHTTPError()

        with self.assertRaises(PlannerError) as ctx:
            plan_v2(product_text="dummy", api_key="k",
                    http_fn=_failing, max_retries=1)
        self.assertIn("v2 API/解析失败", str(ctx.exception))
        self.assertEqual(calls["n"], 2, "应跑 1 次原 + 1 次重试 = 2 次")

    def test_retries_on_schema_invalid_then_raises(self):
        """两次 schema 不合规 → PlannerError."""
        bad = _v2_sample()
        bad["screen_count"] = 3  # 违反 [6,10]
        bad["screens"] = bad["screens"][:3]
        calls = {"n": 0}

        def _bad(payload, key):
            calls["n"] += 1
            return {
                "choices": [{
                    "message": {"content": json.dumps(bad, ensure_ascii=False)}
                }],
            }

        with self.assertRaises(PlannerError) as ctx:
            plan_v2(product_text="dummy", api_key="k",
                    http_fn=_bad, max_retries=1)
        self.assertIn("v2 schema 不合规", str(ctx.exception))
        self.assertEqual(calls["n"], 2)

    def test_recovers_after_one_retry(self):
        """第 1 次 URLError + 第 2 次合规 → 返回成功结果."""
        good = _v2_sample()
        calls = {"n": 0}

        def _flaky(payload, key):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.URLError("first call fails")
            return _mock_http(good)(payload, key)

        result = plan_v2(product_text="dummy", api_key="k",
                         http_fn=_flaky, max_retries=1)
        self.assertEqual(_validate_schema_v2(result), [])
        self.assertEqual(calls["n"], 2)


# ──────────────────────────────────────────────────────────────────
# C: v1 / v2 互不污染验证
# ──────────────────────────────────────────────────────────────────
class TestV1V2Isolation(unittest.TestCase):
    """v1 schema 不应被 v2 校验通过, 反之亦然."""

    def test_v1_sample_fails_v2_validation(self):
        """v1 schema 缺 style_dna / screens → v2 校验大量警告."""
        v1_sample = {
            "product_meta": {
                "name": "X", "category": "设备类",
                "primary_color": "yellow",
                "key_visual_parts": ["a", "b"],
                "proportions": "compact",
            },
            "selling_points": [
                {"idx": 1, "text": "x", "visual_type": "product_in_scene",
                 "priority": "high", "reason": "y"},
            ],
            "planning": {
                "total_blocks": 2,
                "block_order": ["hero", "selling_point_1"],
                "hero_scene_hint": "scene",
            },
        }
        warnings = _validate_schema_v2(v1_sample)
        # 应至少警告 style_dna 缺失 + screen_count 缺失 + screens 缺失
        msg = " ".join(warnings)
        self.assertIn("style_dna", msg)
        self.assertIn("screen_count", msg)
        self.assertIn("screens", msg)

    def test_v2_sample_fails_v1_validation(self):
        """v2 schema 喂给 v1 _validate_schema 也应警告 (selling_points 缺失等)."""
        from ai_refine_v2.refine_planner import _validate_schema as _v1_validate
        v2_sample = _v2_sample()
        v1_warnings = _v1_validate(v2_sample)
        # v1 必查 selling_points / planning.block_order
        msg = " ".join(v1_warnings)
        self.assertIn("selling_points", msg)


class TestPlanV2ExportPath(unittest.TestCase):
    """from ai_refine_v2 import plan_v2 的导入路径."""

    def test_import_from_package_root(self):
        from ai_refine_v2 import plan_v2 as p2  # noqa: F401
        self.assertTrue(callable(p2))

    def test_v1_plan_still_exported(self):
        """加 plan_v2 不能挤掉老 plan."""
        from ai_refine_v2 import plan as p1, PlannerError as PE  # noqa: F401
        self.assertTrue(callable(p1))
        self.assertTrue(issubclass(PE, RuntimeError))


if __name__ == "__main__":
    unittest.main()
