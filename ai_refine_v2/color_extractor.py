"""产品主色提取 + 色卡渲染 (v3.2.2 颜色保真双图锚定).

设计文档: docs/superpowers/specs/2026-04-29-color-anchor-hex-design.md

核心理念: PIL 像素级测量主色 → hex 数值锚 + 程序生成色卡, 对任意产品对称.
依赖: 仅 Pillow (已在 deps), 不引 numpy / scikit-learn.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ColorAnchor:
    """产品主色锚点 (一次提取, 12 屏共享).

    成员:
        primary_hex: '#RRGGBB' 大写, 主簇 centroid hex
        palette_hex: top-3 簇 hex (含 primary_hex 在 [0])
        confidence: 主簇像素 / 非背景像素总数, 范围 [0.0, 1.0]
        swatch_png_bytes: 512x512 纯色 PNG bytes (primary_hex 作色), 用作 image_urls[1]
    """
    primary_hex: str
    palette_hex: list[str]
    confidence: float
    swatch_png_bytes: bytes


def extract_color_anchor(
    cutout_path: str | Path,
    *,
    downsample_to: int = 200,
    min_non_bg_pixels: int = 100,
    min_confidence: float = 0.30,
    swatch_size: int = 512,
) -> Optional[ColorAnchor]:
    """从 cutout 算主色 hex 锚, 失败返 None (调用方走 fallback).

    失败条件:
      - 文件不存在 / 读图失败 / 损坏
      - 非背景像素 < min_non_bg_pixels (整图基本是白底)
      - 主簇 confidence < min_confidence (产品多色无主导)
      - quantize 内部异常
    """
    return None  # 骨架: 后续 Task 逐步实现
