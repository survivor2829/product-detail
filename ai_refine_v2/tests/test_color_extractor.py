"""color_extractor 单测.

所有 fixture 用 PIL 程序生成, 绝不依赖任何真实产品图 (避免硬编码具体产品).
"""
from __future__ import annotations

import io
import unittest
from pathlib import Path

from PIL import Image

from ai_refine_v2.color_extractor import ColorAnchor, extract_color_anchor


def _make_solid_png(rgb: tuple[int, int, int], size: int = 100, alpha: bool = False) -> bytes:
    """生成纯色 PNG bytes (in-memory). alpha=True 加 alpha=255."""
    mode = "RGBA" if alpha else "RGB"
    color = (*rgb, 255) if alpha else rgb
    img = Image.new(mode, (size, size), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestColorAnchorDataclass(unittest.TestCase):
    """验 ColorAnchor dataclass 的 schema 跟 spec §4.1 一致."""

    def test_color_anchor_fields(self):
        anchor = ColorAnchor(
            primary_hex="#FF0000",
            palette_hex=["#FF0000", "#00FF00", "#0000FF"],
            confidence=0.85,
            swatch_png_bytes=b"\x89PNG\r\n\x1a\n",
        )
        self.assertEqual(anchor.primary_hex, "#FF0000")
        self.assertEqual(len(anchor.palette_hex), 3)
        self.assertAlmostEqual(anchor.confidence, 0.85)
        self.assertTrue(anchor.swatch_png_bytes.startswith(b"\x89PNG"))


class TestBackgroundFilter(unittest.TestCase):
    """验非背景像素过滤. PNG alpha + JPG 白底两条路径."""

    def test_fully_transparent_png_returns_none(self):
        """完全透明的 PNG → 无非背景像素 → None (不应崩)."""
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as td:
            p = Path(td) / "fully_transparent.png"
            img = Image.new("RGBA", (100, 100), (255, 0, 0, 0))  # 红色 + alpha=0
            img.save(p, format="PNG")
            anchor = extract_color_anchor(p)
            self.assertIsNone(anchor, "全透明 PNG 应返 None, 不应识别红色")

    def test_pure_white_jpg_returns_none(self):
        """纯白 JPG → 全是背景 → None."""
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as td:
            p = Path(td) / "pure_white.jpg"
            img = Image.new("RGB", (100, 100), (255, 255, 255))
            img.save(p, format="JPEG", quality=90)
            anchor = extract_color_anchor(p)
            self.assertIsNone(anchor, "纯白 JPG 应返 None (产品像素被全部当背景滤掉)")


if __name__ == "__main__":
    unittest.main()
