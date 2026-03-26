"""
物保云产品详情页生成器
用法：
    python generate.py                      # 使用 product_config.json
    python generate.py DW2000B_config.json  # 指定配置文件
    python generate.py --scale 1            # 1x 普通分辨率（文件更小）
"""
import sys
from render import render_page, open_result

if __name__ == "__main__":
    cfg = None
    scale = 2

    args = sys.argv[1:]
    skip_next = False
    for i, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg == "--scale" and i + 1 < len(args):
            scale = int(args[i + 1])
            skip_next = True
        elif not arg.startswith("--"):
            cfg = arg

    print("=" * 50)
    print("  物保云产品详情页生成器")
    print("=" * 50)

    out = render_page(cfg, scale=scale)

    print(f"\n正在打开预览图...")
    open_result(out)
