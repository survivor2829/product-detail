"""regenerate-screen 端点 单测 (v3.3 task5/6).

mock 掉 ai_refine_v2.regen_single.regenerate_screen, 只测 endpoint 自己的
权限/边界/锁/WS publish 行为. 真实重生成走 ai_refine_v2/tests/test_regen_single.py.
"""
from __future__ import annotations

import json
import unittest
import uuid
from unittest import mock

from app import app, db
from models import User, Batch, BatchItem


def _uid(prefix: str) -> str:
    """返回跨 session 唯一的字符串 ID，避免与其他测试文件的 batch_id / username 冲突."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _make_authed_client(username="testuser"):
    client = app.test_client()
    with app.app_context():
        u = User.query.filter_by(username=username).first()
        if u is None:
            u = User(username=username, is_approved=True, is_paid=True)
            u.set_password("x")
            db.session.add(u)
            db.session.commit()
        uid = u.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
    return client, uid


class TestRegenEndpoint4xx(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

    def test_unauthed_redirects_login(self):
        client = app.test_client()
        r = client.post("/api/batch/x/items/1/regenerate-screen", json={})
        self.assertIn(r.status_code, (302, 401))

    def test_batch_not_exist_404(self):
        client, _ = _make_authed_client()
        r = client.post(
            "/api/batch/NOTEXIST/items/1/regenerate-screen",
            json={"block_index": 0},
        )
        self.assertEqual(r.status_code, 404)

    def test_batch_other_owner_403(self):
        alice_name = _uid("alice")
        bob_name = _uid("bob_other")
        batch_id = _uid("bob_batch")
        client, my_uid = _make_authed_client(alice_name)
        with app.app_context():
            other = User(username=bob_name, is_approved=True)
            other.set_password("x")
            db.session.add(other)
            db.session.commit()
            b = Batch(batch_id=batch_id, name="b", raw_name="b",
                      user_id=other.id, batch_dir="x")
            db.session.add(b)
            db.session.commit()
        r = client.post(
            f"/api/batch/{batch_id}/items/1/regenerate-screen",
            json={"block_index": 0},
        )
        self.assertEqual(r.status_code, 403)

    def test_item_not_done_409(self):
        username = _uid("done_user")
        batch_id = _uid("d_b")
        client, uid = _make_authed_client(username)
        with app.app_context():
            b = Batch(batch_id=batch_id, name="b", raw_name="b", user_id=uid,
                      batch_dir="x")
            db.session.add(b)
            db.session.commit()
            it = BatchItem(batch_pk=b.id, name="p", status="done",
                           ai_refine_status="processing",  # 不是 done
                           result=json.dumps({"task_id": "v2_test"}))
            db.session.add(it)
            db.session.commit()
            it_pk = it.id
        r = client.post(
            f"/api/batch/{batch_id}/items/{it_pk}/regenerate-screen",
            json={"block_index": 0},
        )
        self.assertEqual(r.status_code, 409)

    def test_block_index_missing_400(self):
        username = _uid("bi_user")
        batch_id = _uid("bi_b")
        client, uid = _make_authed_client(username)
        with app.app_context():
            b = Batch(batch_id=batch_id, name="b", raw_name="b", user_id=uid,
                      batch_dir="x")
            db.session.add(b)
            db.session.commit()
            it = BatchItem(batch_pk=b.id, name="p", status="done",
                           ai_refine_status="done",
                           result=json.dumps({"task_id": "v2_test"}))
            db.session.add(it)
            db.session.commit()
            it_pk = it.id
        r = client.post(
            f"/api/batch/{batch_id}/items/{it_pk}/regenerate-screen",
            json={},
        )
        self.assertEqual(r.status_code, 400)
