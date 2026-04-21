# 批量生成功能 项目状态

> 最后更新：2026-04-21
> 当前进度：阶段四全部归档，待启动阶段五

## 任务进度

### 阶段一：后台基础 ✅
- [x] 任务1：文件夹上传 API + 文件夹结构解析（2026-04-20，curl 验证通过）
- [x] 任务2：双资源池任务队列（2026-04-20，3 并发上限 + 池隔离 + 失败容错）
- [x] 任务3：批次数据库表 batches+batch_items（2026-04-20，`(第N次)` 后缀 + 5 个端点）
- [x] 任务4a：DeepSeek + rembg 主干集成 + 用户 Key 鉴权（2026-04-20）
- [x] 任务4b：Playwright HTML 渲染 + 落 PNG（2026-04-20，用户验证通过）

### 阶段二：前端工作台 ✅
- [x] 任务5–8.5：workspace UI（批次列表、产品卡片、状态徽章、查看/重跑/下载按钮）
  - 完成于 2026-04-20。详见 `PRD_批量生成.md` 任务 5–8.5 章节。

### 阶段三：模板策略 + AI 精修 ✅
- [x] 任务9：模板智能匹配（2026-04-20，auto/fixed 策略 + `theme_matcher.py`，commit `3b6e3a3`）
- [x] 任务10：费用预估弹窗（2026-04-20，`pricing_config` + `/ai-refine-estimate`，commit `3b6e3a3`）
- [x] 任务11：AI 精修队列（2026-04-20，`refine_processor.py` + 三层防扣费，commit `e67700b`）

### 阶段四：完整下载体验 ✅
- [x] Step A：`/uploads/` 静态路由修复（`login_required` + 路径穿越防御，commit `e67700b`）
- [x] Step B：单文件下载端点 `/api/batch/<id>/item/<item_id>/download`
- [x] Step C：工作台缩略图列 + lightbox + lazy load
- [x] Step D：整批 zip 打包下载 `/api/batch/<id>/export`

### 阶段五：收尾清理 🔜 待启动
执行顺序（用户 2026-04-21 拍板）：**1 → 2 → 3 → 4**
- [ ] **1. 清理 Claude Code plugin/skill/agent** — 当前 190+ agents，裁到常用子集（block-editor / ai-image-debugger / explore / plan 等），减少加载时间和决策噪音
- [ ] **2. DZ70X / DZ95X 旧批次重跑精修** — 前期试跑 failed 状态的产品需重新走 refine_processor，用真实 theme_id
- [ ] **3. 磁盘孤儿文件清理脚本** — `uploads/batches/` 下无 DB 记录的目录（比 `cleanup_orphan_items.py` 的 DB 侧清理更彻底）
- [ ] **4. 服务器部署配置文档整理** — Docker / Playwright / `ARK_API_KEY` / `.env.example` 同步至 `CLOUD_HANDOFF.md`

## 已确认的决策
- [2026-04-20] 任务1 暂不加 `@login_required` + `@csrf.exempt`，方便 curl/Postman 直测；任务4 整链路打通后补回。
- [2026-04-20] 批次目录路径固定为 `uploads/batches/{batch_id}/{产品名}/...`，不污染现有平铺 uploads 结构。
- [2026-04-20] batch_id 格式 `batch_YYYYMMDD_NNN_xxxx`：NNN 当天序号，xxxx 4 字符随机后缀防并发碰撞。
- [2026-04-20] 50 个产品上限按 PRD F3 硬约束：超过直接 400 拒绝并清理已落盘目录。
- [2026-04-20] 用户偏好 PEV 严格循环：每个任务完成→curl 验证→用户点头→下一个。
- [2026-04-20] 任务4 拆 4a/4b：4a = DeepSeek+rembg+DB 同步（无 Playwright），4b = HTML 渲染+落 PNG。
- [2026-04-20] 抠图失败不阻塞产品 done（cutout_error 字段记录），DeepSeek 失败 → 整产品 failed（PRD F7）。
- [2026-04-20] **DeepSeek Key 必须从批次发起者账号读，不读 .env**：用户自带 Key 模式已上线，`.env` 路径已废弃。
  → 所有批量端点加 `@login_required`；启动时验 `batch.user_id == current_user.id`（防 A 用 B 的 quota）。
- [2026-04-20] ARK_API_KEY（豆包 Seedream）同理走"用户账号设置"路线 — 任务 4b 的 Playwright 渲染暂时不需要，
  任务 5 做 AI 精修（文生图/图生图）时才接入。

## 经验日志
- [2026-04-20] 条件：Windows 11 + Python 3.x + zipfile 标准库
  发现：Python `ZipFile.write()` 默认就设置 UTF-8 标志位 (flag_bits 0x800)，所以同代码生成的 zip 中文名不会进 cp437→GBK 兜底分支。
  影响：兜底逻辑只对老版 Windows 工具生成的 zip 生效，但测试时不会触发；保留代码不删。

- [2026-04-20] 条件：Flask + flask-wtf CSRFProtect 全局启用
  发现：所有 POST 端点默认要 CSRF token；curl 测试 multipart 上传必须 `@csrf.exempt`，否则 400。
  影响：`@login_required` 后 cookie 鉴权 + `@csrf.exempt` 共存仍然安全（cookie 由 SameSite + 浏览器同源策略保护）。

- [2026-04-20] 条件：Flask-SQLAlchemy + Flask-Migrate 已 init 但项目无 migrations/ 目录
  发现：项目走 `db.create_all()` 路线（app.py:4178），idempotent 自动建新表；不维护 Alembic 版本链。
  影响：新模型加进 models.py 即可，无需 `flask db migrate`；改字段需要手动 drop 表或加迁移。

- [2026-04-20] 条件：ThreadPoolExecutor wrapper 中 stats.queued/active/done/failed
  发现：所有计数器更新必须在同一把 _lock 内，避免 active 跨线程读到中间态。
  影响：任务3 把 DB 写入也放在 wrapper 内时，DB 写入要在 lock 外做（避免锁 SQLite 的连接）。

- [2026-04-20] 条件：worker 线程跑 SQLAlchemy 操作
  发现：必须套 `with app.app_context():`，否则 `current_app` 报 RuntimeError。
  影响：`_batch_db_sync_callback` 每次回调都进 / 出 app_context；性能影响可忽略。

- [2026-04-20] 条件：batch_processor.py 需要 app.py 的 _call_deepseek_parse / REMBG_SESSION
  发现：模块顶层 `from app import ...` 会引发循环导入。
  影响：所有 app 依赖都做"函数体内延迟导入"。模块加载零成本，运行时才解析。

- [2026-04-20] 条件：DeepSeek Key 走用户账号（custom_api_key_enc，Fernet 加密）
  发现：第一版 `process_one_product` 错用 `_call_deepseek_parse(api_key="")` → 走 .env 兜底 → "未配置 API Key"。
  影响：processor 必须接受显式 `api_key` kwarg；submit_batch 的 processor_fn 是固定两参签名 (scope_id, payload)，
        因此 `/api/batch/<id>/start` 用闭包绑定 key：`lambda s,p,_k=key: process_one_product(s, p, api_key=_k)`。
        worker 池里跑的是闭包不是裸函数。

- [2026-04-20] 条件：Playwright file:// 协议加载 assembled.html
  发现：模板内 `src="/static/foo.png"` 在 `file://` 下被解析成磁盘根目录(C:/static/foo.png)，全部 404。
        `src="/uploads/..."` 同理。原 `/export/<product_type>` 只替换 `/static/`，因为它的产品图都走 `/static/uploads/`。
        但批次产品图落在 `uploads/batches/.../` 下（URL `/uploads/...`），所以 batch_processor 必须**同时替换两个前缀**。
  影响：`_render_product_preview` 用一个 for 循环把 `src=` 和 `href=` 的 `/static/` 与 `/uploads/` 都改成
        `file:///{BASE_DIR绝对路径}{prefix}` 才能保证截图里所有图片正常显示。

- [2026-04-20] 条件：worker 线程跑 render_template
  发现：`render_template` 需要 app context（拿 jinja_env / url_for / globals），但**不需要** request context。
        我们已经在 `_batch_db_sync_callback` 用过 `with app.app_context()`，render 复用同样模式即可。
  影响：`_render_product_preview` 在 `with _flask_app.app_context():` 内调一次 `render_template`；
        复用现有 BLOCK_REGISTRY、build_config 缓存等，不重写任何业务逻辑。
  ⚠ **2026-04-20 深夜推翻**：这条经验错了! render_template 走 Flask-Login context processor 时会
    访问 current_user → 间接查 current_app，app_context **只 push app 不 push request**,触发
    "Working outside of application context"。真实案例：batch_20260420_019_3932 3 个产品全部 render 失败,
    DB 存了 render_error 但 status=done,前端以为一切 OK。正确修法看"技术债/经验教训"→ "Flask context 铁律"。

- [2026-04-20] 条件：3 worker 并发起 sync_playwright + Chromium
  发现：每个 Chromium 实例 ~600MB → 3 并发 ≈ 1.8GB 内存峰值；MacBook M2/Win10 16GB 都扛得住。
        sync_api 是同步阻塞、不能跨线程共享 Page，所以"单 Chromium + per-thread context"不可行。
  影响：当前架构最简单也够用；任务 5+ 如果再扩并发到 5–8 worker 才需要换 async_playwright + 单进程多 context。

## 技术债 / 经验教训

### Flask context 铁律 (2026-04-20 两次踩坑后立碑)

**铁律**：所有 worker 线程（ThreadPoolExecutor / threading.Thread）里调用的代码，
只要链路上**任何一处**摸到以下 Flask API，必须用 `with app.test_request_context():` 包住：

| API | 为什么要 request context (不只是 app context) |
|-----|---|
| `url_for(...)` | Flask 3.x 要求 SERVER_NAME 或 request context 才能推 URL scheme |
| `render_template(...)` | Flask-Login 装的 context processor 在渲染时读 `current_user` → 查 `current_app` → 若无 app context 就炸 |
| `current_app` / `current_user` | 这俩是 LocalProxy,直接访问就需要 context |
| `request` / `session` | 只有 request context 里能访问 |
| 任何 Jinja 模板里间接调的 `url_for('static', ...)` / Flask-Login 扩展 / flask-wtf CSRF 标签 | 同上 |

**正确写法**（已验证 2 次：refine_processor.py + batch_processor.py）：
```python
from app import app
# 注意: app_context() 不够! 必须 test_request_context() — 它一次性 push app + request
with app.test_request_context():
    # 所有 Flask 相关调用都放这里面
    html = render_template("...", ...)
    url = url_for("static", filename="...")
```

**错误写法**（已被推翻 2 次）：
```python
# ✗ 只 push app context, Flask-Login context processor 仍然炸
with app.app_context():
    html = render_template(...)
# ✗ 只包一行, 前面/后面的 _match_scene_image 调 url_for 会抛
mapped = _build_ctxs_from_parsed(...)  # 这里炸
with app.app_context():
    html = render_template(...)
```

**判定规则**：写新 worker 前先问"我这条链路上会不会调到 `render_template` / `url_for` / `current_*` /
任何 Flask 扩展注入的模板全局？" — 答案只要是"可能"或"不清楚"，就包 `test_request_context()`。
**包总比不包稳**：`test_request_context()` 不依赖真实 HTTP 请求、零成本、push/pop 是 O(1)。

**历史案例存档**：
- 2026-04-20 早：refine_processor.py worker 抛 "Working outside of application context" — 修法 `test_request_context()`
- 2026-04-20 晚：batch_processor.py worker 同一错误，3 个产品 render 失败但 status=done（前端假绿）— 相同修法
- **漏网根源**：第一次修 refine 时只改了触发文件，没做全局 grep 扫"ThreadPoolExecutor + url_for/render_template/current_app 组合"

**未来防御**：
1. 新增 worker 代码 PR 里必须 grep 检查 `url_for|render_template|current_app`
2. 单元测试用真 `ThreadPoolExecutor` 跑一次 worker（参考 scripts/verify_refine_worker_context.py 模式）
3. 异常不要静默塞 result JSON；worker 抛出 → 标记产品 `status=failed`，别让前端看到假 done

### 修 bug 后必问同类问题 (2026-04-20 漏网复盘)

**原则**：修完一个 bug 不等于结束。必须立刻问：
**"这是个例还是模式？代码库里还有多少处会犯同样的错？"**

**案例**：
- 早上 `refine_processor.py` 修 Flask context bug → 以为搞定收工
- 晚上 `batch_processor.py` 被同一 bug 击穿 → 3 个产品 render 失败但 status=done（前端假绿）
- 共享模式：worker 线程 + `render_template/url_for/current_*`，当时没做全局扫描

**动作清单**（任何 bug 修完必跑一遍）：
1. 归纳 bug 的本质模式（e.g. "worker 线程里摸 Flask context"）
2. 用 grep 搜同类模式（`ThreadPoolExecutor|threading.Thread` 交叉 `render_template|url_for|current_app`）
3. 每一处都检查是否有同样缺陷，不放过任何一处
4. 写一个 `verify_*.py` 把这个不变量锁死（参考 `scripts/verify_refine_worker_context.py` 模式）

**反例**（永远不要再犯）：修完一处就 commit 收工，不做全局扫描 → 等同一 bug 第二次爆炸。

### 烧钱 API 必须三层防护 (2026-04-20 ¥10.8 事故后立碑)

**背景**：任务 11 AI 精修首次试跑意外烧 ¥10.8（正常预估 ¥3.6 的 3 倍）。
根因：前端按钮未锁 → 用户连点 → 3 个并发批次同时跑 → 每批 6 屏 × Seedream 全额烧。

**三层防护**（缺一不可，已全部落地 — 见 commit `e67700b`）：

1. **前端按钮锁（防误点）**
   - 点"开始 AI 精修"立刻 `disabled` + loading 文案
   - `window.confirm` 弹窗期也保持锁，防止弹窗阶段连点
   - fetch 成功/失败都在 `finally` 里解锁

2. **Key 缺失跳转（防空跑）**
   - 后端启动端点第一步查 `ARK_API_KEY`
   - 没 key 直接 302 `/settings`，**不入队**（不扣费也不产生 failed 记录）
   - 前端错误 toast 指向"去配置"链接

3. **硬上限 `MAX_REFINE_COST_PER_RUN`（防意外）**
   - 环境变量 `MAX_REFINE_COST_PER_RUN`（默认 ¥50）
   - 启动前调 `compute_estimate()` 预估费用，超额直接 400 拒绝
   - 日志打印预估 vs 上限，方便运维调参

**未来新增烧钱 API 的上线清单**（强制检查）：
- [ ] 前端按钮有 `disabled` + loading 态？
- [ ] 后端入队前查依赖 Key？没 Key 走跳转不走队列？
- [ ] 有硬上限 env var？`compute_estimate()` 接入了吗？
- [ ] 失败场景的提示是否让用户能自己修复（而不只是 "error 500"）？

## 用户偏好
- 用户能看 JSON 字段对错，但不直接读 Python 代码 → 验证步骤要写"预期看到 X"而不是"运行什么测试"
- 用户用 curl 验证（但需要登录态时改用 requests.Session 脚本，curl + CSRF 在 PowerShell 里太啰嗦）
- 用户喜欢 4 选 1 的反馈模板（OK/不对/方向错/跳过）

## 待解决问题
（暂无）

---

## 任务 4b 验证步骤（在 4a 基础上多看 preview.html / preview.png）

### 前提（同 4a）
1. 已登录账号配好 DeepSeek Key
2. rembg + onnxruntime + Playwright + Chromium 都已 ready
3. 测试 zip 已生成

### 一键跑（同 4a 脚本，4b 自动复用）

```powershell
python scripts\test_batch_login_flow.py --user 你的用户名 --pass 你的密码 --zip test_batch.zip
```

DeepSeek ~5–15s + 抠图 ~2–4s + Playwright 截图 ~5–10s/产品 = 单产品总耗时约 15–30s。
3 并发 → 5 个产品大约 30–50s。

### 看 4b 新增产物（关键）

每个产品目录现在应该多两个文件：
```powershell
$batchId = "batch_20260420_001_xxxx"  # 替换成实际值
ls "uploads\batches\$batchId\产品A"
# 应看到（4a 已有 + 4b 新增 ★）：
#   product.jpg
#   desc.txt
#   parsed.json        ← 4a 落
#   product_cut.png    ← 4a 落（抠图成功的话）
#   preview.html  ★    ← 4b 新增
#   preview.png   ★    ← 4b 新增（高清长图）
```

**preview.png 必须满足：**
- 文件大小 > 200KB（空白长图通常 < 50KB）
- 用图片 viewer 打开能看到完整的产品详情页（首屏 + 六大优势 + 参数表 + 对比屏 等）
- 产品图位置正确（不是占位图、不是 broken image）

**preview.html 必须满足：**
- 直接双击用浏览器打开，能渲染（图片可能因为 file:/// 安全策略不显示，但布局完整）

### DB 字段验证

```powershell
$batchId = "batch_20260420_001_xxxx"
curl.exe -b cookies.txt http://localhost:5000/api/batches/$batchId | python -m json.tool
```

`items[].result` 现在应该多三个字段：
```json
{
  "result": {
    "parsed_path":  "/uploads/batches/.../parsed.json",
    "parsed_keys":  ["brand", "product_name", ...],
    "cutout_path":  "/uploads/batches/.../product_cut.png",
    "cutout_error": null,
    "preview_html": "/uploads/batches/.../preview.html",
    "preview_png":  "/uploads/batches/.../preview.png",
    "render_error": null,
    "product_name": "产品A"
  }
}
```

### 失败兜底验证（可选）

**测试 1：parsed 缺核心字段（导致模板渲染挂掉）**
- 不需要主动制造，看是否有产品 `render_error != null` 但 `status == "done"`
- 预期：`preview_png` 字段是 `null`，但 `parsed_path` 还在；产品在 UI 上显示"渲染失败"提示而非整产品 failed

**测试 2：Playwright 启动失败（卸载 Chromium 模拟）**
- `python -m playwright uninstall chromium`（先备份！）
- 跑批次 → 全部产品 status=done 但 render_error 字段都有 "BrowserType.launch: Executable doesn't exist"
- 复跑 `python -m playwright install chromium` 恢复

### 反馈 4 选 1
- ✅ **OK 通过** → 阶段一收口，进入阶段二（前端工作台 UI）
- ❌ **不对** → 告诉我哪个产品的 preview.png 不对，我看 product_dir 里的 preview.html 排查
- 🔄 **方向错** → 退回重设计
- ⏭ **不渲染了，4a 就够** → 把 _render_product_preview 调用从 process_one_product 摘掉

---

## 任务 4a 验证步骤（带登录的版本，已通过，留档）

### 前提
1. 登录账号已在「账号设置」配好 DeepSeek Key（用户自带 Key 模式）
2. rembg + onnxruntime 已 pip 装好
3. 准备好测试 zip：`python scripts\make_test_batch_zip.py` 生成 `test_batch.zip`

### 一键跑通（推荐）

开两个 PowerShell 窗口：

**窗口 1：起服务**
```powershell
python app.py
```

**窗口 2：跑端到端测试脚本**
```powershell
python scripts\test_batch_login_flow.py --user 你的用户名 --pass 你的密码 --zip test_batch.zip
```

预期看到（5 步打印 + 进度）:
```
[1/5] 登录 http://localhost:5000/auth/login as XXX…
      ✓ 登录成功
[2/5] 上传 test_batch.zip…
      ✓ batch_id=batch_20260420_001_xxxx  valid=3  skipped=2
[3/5] 启动批次…
      ✓ 已提交 3 个产品；状态=queued
[4/5] 轮询 /status 每 3s…
      ⏱ pending=2 processing=1 done=0 failed=0
      ⏱ pending=0 processing=2 done=1 failed=0
      ⏱ pending=0 processing=0 done=3 failed=0
[5/5] 拉 DB 持久化结果…
      batch.status=completed  valid=3  skipped=2
      • 产品A      status=done       parsed_keys=15  cutout=OK
      • 产品B      status=done       parsed_keys=14  cutout=OK
      • 产品C      status=done       parsed_keys=15  cutout=SKIP  cutout_err=...
✅ 全部 3 个产品 done，0 个失败
```

DeepSeek ~5–15s/产品，3 并发 → 5 个产品大约 15–30s。

### 失败兜底验证（可选）

**测试 1：用户没配 Key**
- 临时把账号设置里的 Key 清空
- 跑脚本 → `[3/5] 启动批次` 那步会拿到 400：
  ```
  ✗ start 失败 status=400
  {"error": "请先在「账号设置」中配置 DeepSeek API Key 后再启动批次"}
  ```

**测试 2：跨用户启动**
- 用 A 账号上传批次，记下 batch_id
- 用 B 账号登录，POST /api/batch/<batch_id>/start
- 预期：`403 {"error": "只有批次的上传者可以启动该批次"}`

**测试 3：DeepSeek Key 失效**
- 用真实账号登录但把 Key 改成无效字符串
- 跑脚本 → 所有 item `status=failed`，`error` 含 401 信息

### 看落盘文件
```powershell
$batchId = "batch_20260420_001_xxxx"  # 替换成实际值
ls "uploads\batches\$batchId\产品A"
# 应看到：product.jpg  desc.txt  parsed.json  product_cut.png

Get-Content "uploads\batches\$batchId\产品A\parsed.json" -Raw | python -m json.tool
```

### 反馈 4 选 1
- ✅ **OK 通过** → 我做任务 4b（Playwright 渲染落 PNG）
- ❌ **不对** → 告诉我哪步、哪个字段不符合预期
- 🔄 **方向错** → 退回重设计
- ⏭ **跳过 4b 直接交付 4a** → 阶段一就此收口

---

## 恢复指引
新对话续做时按以下顺序操作：
1. 读本文件了解进度（重点看"任务进度"+"技术债/经验教训"两节）
2. 读 `PRD_批量生成.md` 了解目标
3. 当前任务 = **阶段五 · 任务 1 清理 Claude Code plugin/skill/agent**

### 阶段五接续点（下一轮启动点）

**优先做任务 1：清理 plugin/skill/agent**
- 动机：当前 `.claude/` 加载 190+ agents，子代理选型时决策噪音大、加载慢
- 策略：先列出"过去一周真正用到的 agent/skill"，再裁剪到常用子集
- 保留最小集：阶段五开始时再盘点决定（基于真实使用数据，不提前写死）
- 裁剪前先把当前 `.claude/` 备份到 `.claude.backup.<date>/`

**后续顺序**：任务 2（旧批次重跑精修）→ 任务 3（磁盘孤儿清理）→ 任务 4（部署文档整理）

### 核心只读铁律（无论做到哪一步都要遵守）
- **Flask context 铁律**：所有 worker 线程碰 Flask API 必须 `test_request_context()`，不是 `app_context()`
- **修 bug 后必问同类问题**：修完立刻 grep 全局同类模式，别让同一 bug 二次爆炸
- **烧钱 API 三层防护**：前端按钮锁 + 后端 Key/上限 + 失败提示可操作
- 详见"技术债/经验教训"章节
