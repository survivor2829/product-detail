"""产品主色提取 + 色卡渲染 (v3.2.2 颜色保真双图锚定).

设计文档: docs/superpowers/specs/2026-04-29-color-anchor-hex-design.md

核心理念: PIL 像素级测量主色 → hex 数值锚 + 程序生成色卡, 对任意产品对称.
依赖: 仅 Pillow (已在 deps), 不引 numpy / scikit-learn.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, UnidentifiedImageError


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


def _filter_background_pixels(img: Image.Image) -> list[tuple[int, int, int]]:
    """返回非背景像素的 RGB 列表.

    PNG with alpha: alpha < 128 排除
    其他模式 (JPG): 转 HSV, V > 240/255 且 S < 0.05 视为白背景排除
    """
    if img.mode == "RGBA":
        rgba_pixels = list(img.getdata())
        return [(r, g, b) for r, g, b, a in rgba_pixels if a >= 128]

    # JPG / RGB 路径: 用 HSV 滤白背景
    rgb_img = img.convert("RGB") if img.mode != "RGB" else img
    hsv_img = rgb_img.convert("HSV")
    rgb_pixels = list(rgb_img.getdata())
    hsv_pixels = list(hsv_img.getdata())
    out = []
    for (r, g, b), (h, s, v) in zip(rgb_pixels, hsv_pixels):
        # V > 240/255 且 S < 0.05 视为白背景 (S 范围 0-255, 0.05 * 255 ≈ 13)
        if v > 240 and s < 13:
            continue
        out.append((r, g, b))
    return out


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
    p = Path(cutout_path)
    if not p.is_file():
        return None
    try:
        img = Image.open(p)
        # 下采样加速 quantize
        if max(img.size) > downsample_to:
            ratio = downsample_to / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        non_bg = _filter_background_pixels(img)
        if len(non_bg) < min_non_bg_pixels:
            return None
    except (UnidentifiedImageError, OSError, Exception):
        return None

    # Task 3 在这里加 quantize 算主色, 暂时仍返 None
    return None
