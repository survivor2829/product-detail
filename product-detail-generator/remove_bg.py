"""
抠图工具：去除产品图背景，输出透明底 PNG
用法: python remove_bg.py <图片路径> [图片路径2 ...]
输出: 同目录下，文件名加 _nobg 后缀
"""
import sys
from pathlib import Path
from PIL import Image
from rembg import remove


def remove_background(input_path: str) -> str:
    """
    去除图片背景，保存透明底 PNG。
    返回输出文件路径。
    """
    p = Path(input_path)
    if not p.exists():
        print(f"[错误] 文件不存在: {input_path}")
        return ""

    output_path = p.parent / f"{p.stem}_nobg.png"

    print(f"[处理] {p.name} ...")
    with open(p, "rb") as f:
        input_data = f.read()

    output_data = remove(input_data)

    with open(output_path, "wb") as f:
        f.write(output_data)

    # 验证输出
    img = Image.open(output_path)
    print(f"[完成] -> {output_path}")
    print(f"       尺寸: {img.size[0]}x{img.size[1]}  模式: {img.mode}")
    return str(output_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python remove_bg.py <图片路径> [图片路径2 ...]")
        sys.exit(1)

    for path in sys.argv[1:]:
        remove_background(path)
