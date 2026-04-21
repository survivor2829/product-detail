"""批次进度推送的内存级 Pub/Sub。

PRD: PRD_批量生成.md F5（实时通信 + 浏览器连接状态）

为什么要单独成模块:
- 不污染 batch_queue（批次队列只管 worker 状态机，不该知道有 WebSocket）
- 不污染 app.py（已经够厚）
- 给未来横向扩展留口（升 Redis Pub/Sub 就只动这一文件）

设计:
- subscribe(batch_id, ws)   → 把 ws 加进 dict[batch_id]={ws,...}
- publish(batch_id, event)  → 把 event 序列化后发给该批次所有订阅者
- 任何 ws.send 失败 → 自动从订阅集合里摘掉（连接已断）
- 全部走一把 _lock，避免 worker 线程 publish 与 ws 线程 subscribe 撞车

"WebSocket 断开 → 后台暂停"那条 PRD 是 v2 才能做（需要 process_one_product 加
checkpoint），本模块只负责"前端能看到所有 worker 状态变化"，断开就不再推就完事。
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from typing import Any

_lock = threading.Lock()
_subscribers: dict[str, set[Any]] = {}  # batch_id → set of ws-like objects


def subscribe(batch_id: str, ws: Any) -> None:
    """注册 ws 到指定批次的订阅集合。"""
    with _lock:
        _subscribers.setdefault(batch_id, set()).add(ws)


def unsubscribe(batch_id: str, ws: Any) -> None:
    """显式移除 ws；ws 端点退出时务必调一次。"""
    with _lock:
        s = _subscribers.get(batch_id)
        if not s:
            return
        s.discard(ws)
        if not s:
            _subscribers.pop(batch_id, None)


def publish(batch_id: str, event: dict) -> int:
    """把事件 broadcast 给该批次的所有订阅者。

    event 至少含 type 字段；ts 由本函数补；返回成功推送的数量。
    任何 ws.send 抛错 → 把那个 ws 从订阅集合里摘掉（认定已死）。
    """
    payload = dict(event)
    payload.setdefault("ts", time.time())
    payload.setdefault("batch_id", batch_id)
    msg = json.dumps(payload, ensure_ascii=False)

    # 拷一份订阅者快照，避免持锁时调 ws.send（可能阻塞）
    with _lock:
        targets = list(_subscribers.get(batch_id, ()))

    dead: list[Any] = []
    sent = 0
    for ws in targets:
        try:
            ws.send(msg)
            sent += 1
        except Exception:
            traceback.print_exc()
            dead.append(ws)

    if dead:
        with _lock:
            s = _subscribers.get(batch_id)
            if s:
                for d in dead:
                    s.discard(d)
                if not s:
                    _subscribers.pop(batch_id, None)
    return sent


def subscriber_count(batch_id: str) -> int:
    """看某批次当前有多少前端在听（debug 用）。"""
    with _lock:
        return len(_subscribers.get(batch_id, ()))


def stats() -> dict:
    """全局快照：哪些批次有订阅、各几个 ws。"""
    with _lock:
        return {
            "batches_with_listeners": len(_subscribers),
            "listeners_per_batch": {
                bid: len(s) for bid, s in _subscribers.items()
            },
        }
