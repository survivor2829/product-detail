"""P0 僵尸清理 — 验证 addCleanup teardown 机制真正防止残留行.

这两个测试必须按顺序执行且都绿才算 fixture 有效:
  test_a: 在 DB 里创建 fixture_test_a 用户
  test_b: 断言 fixture_test_a 已被清除（因为 test_a 注册了 addCleanup）

逻辑上 test_b 是 test_a 的"事后验尸"。
pytest 默认按字母序执行同文件内的方法，a < b 保证顺序正确。
"""
from __future__ import annotations

import unittest

from app import app, db
from models import User, Batch


def _cleanup_user(username: str) -> None:
    """在 app context 里删除指定用户及关联 Batch 行（幂等）。

    Batch.user_id FK 没有 ondelete=CASCADE，必须先删 Batch 再删 User。
    """
    with app.app_context():
        u = User.query.filter_by(username=username).first()
        if u is None:
            return
        for b in Batch.query.filter_by(user_id=u.id).all():
            db.session.delete(b)
        db.session.flush()
        db.session.delete(u)
        db.session.commit()


class TestAddCleanupPattern(unittest.TestCase):
    """验证 addCleanup 能防止僵尸用户残留."""

    def setUp(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

    def test_a_create_user_with_cleanup(self):
        """创建用户并注册 addCleanup——测试结束后行应被删除."""
        username = "fixture_test_a"
        # 注册清理钩子（在 test_a 结束时执行）
        self.addCleanup(_cleanup_user, username)

        with app.app_context():
            u = User(username=username, is_approved=True, is_paid=True)
            u.set_password("x")
            db.session.add(u)
            db.session.commit()
            found = User.query.filter_by(username=username).first()

        self.assertIsNotNone(found, "用户应在 test_a 里可见")

    def test_b_user_from_test_a_is_gone(self):
        """test_a 的 addCleanup 执行后，fixture_test_a 行应已消失."""
        with app.app_context():
            found = User.query.filter_by(username="fixture_test_a").first()
        self.assertIsNone(found, "fixture_test_a 没被 addCleanup 清除, 是个 bug")
