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


class TestPrimaryColorExtraction(unittest.TestCase):
    """验 quantize 主色 + palette + confidence."""

    def _save_solid(self, td: Path, name: str, rgb: tuple[int, int, int]) -> Path:
        p = td / name
        img = Image.new("RGBA", (200, 200), (*rgb, 255))
        img.save(p, format="PNG")
        return p

    def _hex_distance(self, hex1: str, hex2: str) -> float:
        """欧式距离, 单位 0-255 通道."""
        r1, g1, b1 = int(hex1[1:3], 16), int(hex1[3:5], 16), int(hex1[5:7], 16)
        r2, g2, b2 = int(hex2[1:3], 16), int(hex2[3:5], 16), int(hex2[5:7], 16)
        return ((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2) ** 0.5

    def test_solid_red_primary_extracted(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as td:
            p = self._save_solid(Path(td), "red.png", (255, 0, 0))
            anchor = extract_color_anchor(p)
            self.assertIsNotNone(anchor, "纯红 cutout 应能算出主色")
            dist = self._hex_distance(anchor.primary_hex, "#FF0000")
            self.assertLess(dist, 10, f"primary_hex {anchor.primary_hex} 偏离 #FF0000 太远 (dist={dist:.1f})")

    def test_solid_red_palette_size(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as td:
            p = self._save_solid(Path(td), "red.png", (255, 0, 0))
            anchor = extract_color_anchor(p)
            self.assertIsNotNone(anchor)
            self.assertEqual(len(anchor.palette_hex), 3, "palette 必须 top-3")
            self.assertEqual(anchor.palette_hex[0], anchor.primary_hex,
                             "palette[0] 必须等于 primary_hex")

    def test_solid_red_confidence_high(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as td:
            p = self._save_solid(Path(td), "red.png", (255, 0, 0))
            anchor = extract_color_anchor(p)
            self.assertIsNotNone(anchor)
            self.assertGreater(anchor.confidence, 0.95,
                               f"纯色产品 confidence 应近 1.0, 实际 {anchor.confidence:.3f}")

    def test_he180_gray_white_not_yellow(self):
        """HE180 染黄 bug 直接钉死回归保护:
        浅白底 + 灰色机身的产品图, primary_hex 必须在灰色区间, 绝不能被算成黄色.
        """
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as td:
            p = Path(td) / "he180_simulation.png"
            # 模拟 HE180: 200x200, 中央 60% 是灰色机身 #6B7280, 四周白底
            img = Image.new("RGBA", (200, 200), (255, 255, 255, 255))
            for y in range(40, 160):
                for x in range(40, 160):
                    img.putpixel((x, y), (107, 114, 128, 255))  # #6B7280
            img.save(p, format="PNG")
            anchor = extract_color_anchor(p)
            self.assertIsNotNone(anchor, "HE180 模拟图应能算出主色")

            # primary 必须在灰色区间 (R≈G≈B 且 都不接近 255)
            r = int(anchor.primary_hex[1:3], 16)
            g = int(anchor.primary_hex[3:5], 16)
            b = int(anchor.primary_hex[5:7], 16)

            # 钉死 bug: 黄色定义 = R和G都高 而 B低. 反向断言不能是黄色.
            is_yellow_ish = (r > 200 and g > 200 and b < 150)
            self.assertFalse(is_yellow_ish,
                             f"primary {anchor.primary_hex} 不应被算成黄色 (HE180 染黄 bug 回归保护)")

            # 正向断言: 应在灰色区间 (R, G, B 接近 + 都不极亮)
            max_channel = max(r, g, b)
            min_channel = min(r, g, b)
            spread = max_channel - min_channel
            self.assertLess(spread, 50,
                            f"primary {anchor.primary_hex} 应在灰色区间 (R≈G≈B), 实际 spread={spread}")
            self.assertLess(max_channel, 200,
                            f"primary {anchor.primary_hex} 不应极亮 (机身灰应在中等亮度)")


if __name__ == "__main__":
    unittest.main()
