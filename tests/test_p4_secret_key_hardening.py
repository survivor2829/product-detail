"""P4 §A.1 SECRET_KEY 硬编码回退修复 — 守护测试.

per `docs/superpowers/specs/_stubs/A1-secret-key-fallback-stub.md` 方案 A.

漏洞: app.py 在 SECRET_KEY 空时静默回退 "dev-change-me-in-production"
公开默认值, 攻击者可伪造 session cookie 接管账号.

修复: 非 development 模式 SECRET_KEY 空时 sys.exit(1) fail-fast,
不再有公开默认值兜底.

本测试组防止未来 PR 把 fallback 加回去.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_PY = REPO_ROOT / "app.py"


class TestNoPublicFallback:
    """守护: app.py 不能再有公开的 SECRET_KEY 默认字符串."""

    def test_no_dev_change_me_string_assigned_to_secret_key(self):
        """app.py 不能把 'dev-change-me-in-production' 直接当 SECRET_KEY 用.

        允许在 development 分支用, 但禁止 `_secret_key or "dev-change-me-..."`
        这种"空就回退"的模式 — 因为它对生产也生效.
        """
        content = APP_PY.read_text(encoding="utf-8")
        # 禁止: SECRET_KEY 赋值时用 `or "dev-change-me-in-production"`
        forbidden = re.search(
            r'SECRET_KEY.*=.*_secret_key\s+or\s+"dev-change-me',
            content,
        )
        assert forbidden is None, (
            "app.py 仍在用 `_secret_key or \"dev-change-me-in-production\"` 兜底, "
            "这等于把公开默认值当生产 SECRET_KEY. 改成方案 A: "
            "非 development 模式直接 sys.exit(1)."
        )

    def test_secret_key_assignment_has_fail_fast_path(self):
        """app.py 必须有 sys.exit 或 raise 处理 SECRET_KEY 缺失的非 dev 路径."""
        content = APP_PY.read_text(encoding="utf-8")
        # 取 SECRET_KEY 赋值附近 30 行做检查
        lines = content.split("\n")
        secret_key_lines = []
        for i, line in enumerate(lines):
            if "SECRET_KEY" in line and ("config" in line or "_secret_key" in line):
                # 取该行往前 5 行往后 10 行的上下文
                start = max(0, i - 5)
                end = min(len(lines), i + 15)
                secret_key_lines.extend(lines[start:end])
        block = "\n".join(secret_key_lines)
        has_fail_fast = "sys.exit" in block or "raise RuntimeError" in block
        assert has_fail_fast, (
            "SECRET_KEY 赋值附近缺 sys.exit / raise — 缺 SECRET_KEY 时必须 fail-fast, "
            "不能静默回退到公开默认值."
        )


class TestEnvExampleDocumentsSecretKey:
    """守护: .env.example 必须文档化 SECRET_KEY 要求."""

    def test_env_example_mentions_secret_key(self):
        env_example = REPO_ROOT / ".env.example"
        if not env_example.exists():
            return  # 没文件就跳过 (生产部署不依赖 .env.example)
        content = env_example.read_text(encoding="utf-8")
        assert "SECRET_KEY" in content, (
            ".env.example 应文档化 SECRET_KEY 要求, "
            "运维 deploy 时知道这是必填项."
        )
