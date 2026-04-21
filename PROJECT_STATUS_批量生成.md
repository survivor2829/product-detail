# 批量生成功能 项目状态

> 最后更新：2026-04-21（晚间，阶段六生产上线完成）
> 当前进度：**阶段六生产上线完成**（腾讯云 http://124.221.23.173:5000/），阶段七（硬件升级 + PG/Redis）待启动
> 生产环境：SQLite 单机 + gunicorn 2×gthread，镜像国内化 full-chain，详见 `docs/2026-04-21_踩坑复盘_生产上线.md`

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

### 阶段六：生产化收尾 ✅ 完成（2026-04-21 晚间生产上线 http://124.221.23.173:5000/）
> 目标：腾讯云生产部署前把所有"临时绕过"闭环。用户 D4 指令（2026-04-21）：
> **"文档先锁住技术债范围，不让它扩大。排期可以延后，但不能当成'不要做'。"**

**已完成 (2026-04-21)**：
- [x] SQLAlchemy 连接池参数 env 化（`DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_RECYCLE` / `DB_POOL_PRE_PING`），仅 Postgres 生效
- [x] 启动恢复钩子：`pending` / `processing` / `queued` / `running` 中断批次在启动时标 `failed`（不自动重试，避免烧钱 API 重复扣）
- [x] DB 级重入检查：
  - 批次启动走 `UPDATE ... WHERE status IN (uploaded, failed)` 原子抢占（跨 worker 安全）
  - 精修启动走 `with_for_update(skip_locked=True)` 行锁（跨 worker 原子 claim）
- [x] `pubsub/` 抽象层：内存 backend（单 worker dev）/ Redis backend（多 worker prod，pattern-subscribe）
- [x] Alembic 接入：`flask db upgrade` 维护 schema；`create_all()` 保留为 SQLite 开发兜底
- [x] SQLite → Postgres 迁移脚本 `scripts/migrate_sqlite_to_pg.py`（dry-run 默认 + `--commit` 实际执行，幂等，可重跑）
- [x] `/batch/history` 最简历史页：按 created_at 倒序，LIMIT 50，分页 v2 加
- [x] `/api/batches` 跨用户泄露修复（之前 `SELECT *` 无 user_id 过滤，任意登录用户可见全库批次元数据）

**CSRF 豁免审计（14 条 `@csrf.exempt`）**：

| 路由 | 方法 | 风险等级 | 本轮动作 | 原因 |
|---|---|---|---|---|
| `/api/batch/upload` | POST | 🔴 高 | 今日收紧 | 创建批次 + 写文件 |
| `/api/batch/<id>/start` | POST | 🔴 高 | 今日收紧 | 启动付费 API 任务 |
| `/api/batch/<id>/ai-refine-start` | POST | 🔴 高 | 今日收紧 | 启动付费精修 API |
| `/api/batches/<id>/items/<name>` | PATCH | 🟠 中 | 今日收紧 | 改 DB（want_ai_refine 标志） |
| `/api/generate-ai-detail` | POST | 🟠 中 | 今日收紧 | 烧图片 API 配额 |
| `/api/generate-ai-detail-html` | POST | 🟠 中 | 今日收紧 | 烧 Seedream API |
| `/api/generate-ai-images` | POST | 🟠 中 | 今日收紧 | 烧图片 API 配额 |
| `/api/build/<type>/parse-text` | POST | 🟠 中 | 今日收紧 | 烧 DeepSeek 配额 |
| `/api/build/<type>/render-main-images` | POST | 🟠 中 | 今日收紧 | 烧 AI + 落盘 |
| `/api/build/<type>/render-preview` | POST | 🟢 低 | 今日收紧 | workspace.html 已送 token，顺手 |
| `/api/build/<type>/render-block` | POST | 🟢 低 | 今日收紧 | 同上 |
| `/api/build/<type>/regenerate-block` | POST | 🟢 低 | 今日收紧 | 同上 |
| `/api/batch/<id>/start-mock` | POST | ⚪ dev only | 保留豁免 + 生产拒绝 | 仅开发 mock，生产路径不暴露 |
| `/api/single/_mock-task` | POST | ⚪ dev only | 保留豁免 + 生产拒绝 | 同上 |

**Legacy 权限策略**（`batches.user_id IS NULL` 的老数据）：
- 现状：`batches_detail` / `batches_list` / `/batch/history` 三处策略不统一 — 前两者"legacy 对所有人可见"，我的新列表页先对齐了 API，但这是临时方案
- **阶段六-收尾动作**：跑 `UPDATE batches SET user_id = 1 WHERE user_id IS NULL`（绑定到 admin），然后把所有 legacy-visible 分支删掉，只留 `user_id == current_user.id` 单一判定
- 决策依赖：用户确认生产 DB 里 `user_id IS NULL` 的行是哪些（0 条 / 有历史 / 属于哪个早期 admin），本地 dry-run 通过后再跑

**其他阶段六待办**：
- [x] ~~生产环境 secrets 生成~~（2026-04-21 部署时直接 admin 改密 + 生成 FERNET_KEY/SECRET_KEY 填 .env）
- [x] ~~`docker-compose.yml`（prod）首次启动 smoke~~（2026-04-21 web 容器 Up，HTTP 200，logs 无 traceback）
- [ ] 多用户并发 E2E：两账号同时跑 HTML 批次 + 精修，验证无跨用户污染 + 跨 worker WS 推送（**单机 SQLite 下跨 worker 部分推迟到 PG/Redis 上线**）
- [ ] `DEPLOYMENT.md`：腾讯云首次部署 + 滚动升级 + 回滚流程（**已先落在 `docs/2026-04-21_踩坑复盘_生产上线.md`，后续整理成正式 DEPLOYMENT.md**）

**2026-04-21 上线补充**：
- [x] 镜像构建国内化全链路：apt 腾讯云 + pip 腾讯云 + playwright npmmirror CfT + rembg ghfast.top（4 次 Dockerfile 迭代才稳，见踩坑文档）
- [x] SSH 免密 + `~/.ssh/config` 别名 `tencent-prod`（踩坑：authorized_keys 前缀注释导致整行失效，已立"SSH 排查三板斧"铁律）
- [x] Alembic 接管老 SQLite：`flask db stamp a73747e2b475`（`db.create_all` 已建表 + `alembic_version` 空 → stamp 而非 upgrade）
- [x] admin 密码重置为 20 字符随机强密码，only-show-once 已交付用户入密码管理器
- [x] 生产 `.env` 配置：`DATABASE_URL=sqlite:///wubaoyun.db` / `FLASK_ENV=production` / `PUBSUB_BACKEND=memory` / `AI_BG_MODE=cache`

### 阶段七：硬件升级 + PG/Redis 全栈 🔜 待启动

触发条件：用户数/并发需求上来、或 2C2G 出现明显 OOM / 响应变慢。

#### 性能扩展性分析 (2026-04-21 生产第二批观察后补, 对应问题3)

**单产品耗时模型** (冷启 → 稳态):
- DeepSeek 解析: 5–15s (API IO-bound, 不吃本地 CPU/内存)
- rembg 抠图: 首载模型 ~30s, 之后 ~3–5s/图 (CPU-bound, 吃满 1 核)
- Playwright 渲染 + 截图: Chromium ~600MB/实例, ~15–30s/产品 (冷启 ~60s)
- **单产品合计**: 首产品冷启 90–120s, 热批 30–50s/产品

**三档硬件吞吐对照表**:

| 配置 | 并发上限 | 30 产品 ETA | 安全批量上限 | 适用场景 |
|---|---|---|---|---|
| **2C2G** (当前) | 1 (≥2 必 OOM) | 30 × 40s ≈ 20–50 分钟 (swap 抖动时更慢) | **5 产品/批** | 内部测试 / 个人演示 |
| **4C8G** | 3 worker | 10–15 分钟 | **10 产品/批** | 团队共用 / 小客户 |
| **8C16G** | 6 worker | 3–5 分钟 | **30+ 产品/批** (PRD F3 的 50 上限真跑得动) | 多客户并发 |

**升级触发阈值** (任一命中就升):
- 2C2G → 4C8G: (a) 单批 ≥ 5 产品 实测 > 10 分钟; (b) `free -h` swap used > 500MB 持续 > 5 分钟; (c) 用户主观说"卡"≥ 2 次
- 4C8G → 8C16G: (a) 单批 50 产品 > 20 分钟; (b) 多用户并发 ≥ 3 导致排队 > 5 分钟

**OOM 风险推导 (2C2G)**:
- 系统 + docker 常驻 ~400MB
- gunicorn 2 gthread workers ~500MB
- rembg onnx 模型加载 ~300MB
- Playwright Chromium (首产品时) ~600MB → 峰值 ~1.8GB 接近 2GB 顶
- 如果 gunicorn 再多起一个 Chromium (并发 2), 必 swap, 90% 概率 OOM kill

**当前状态** (2026-04-21): 2C2G 单用户小批 (3 产品) 已实测 ~10 分钟内完成, 未触发升级条件; 但第二批跑慢已踩到心理阈值边缘, 下次 ≥ 5 产品批就要上 4C8G。

- [ ] **机器升级 4C8G 起** (触发条件见上表; 2026-04-21 OOM 事故后硬需求)
  1. **升配前备份** (SQLite + uploads + outputs + instance):
     ```bash
     ssh tencent-prod 'cd /root/clean-industry-ai-assistant && tar czf /tmp/backup_pre_upgrade_$(date +%Y%m%d).tar.gz instance/ static/uploads/batches/ static/outputs/ 2>&1 | tail'
     scp tencent-prod:/tmp/backup_pre_upgrade_*.tar.gz ./prod_backups/
     ```
  2. **腾讯云控制台升配 2C2G → 4C8G** (停服 10–30 分钟, IP 不变)
     - 实例 → 更改实例规格 → 4C8G → 确认重启
     - 验证: `ssh tencent-prod 'free -h; nproc'` → RAM ~7.5GB, CPU=4
  3. **调 `docker-compose.yml` 资源限额** (和并发池同步):
     ```yaml
     web:
       mem_limit: 6500m        # 8GB 主机留 1.5GB 给 sshd/journald/docker
       memswap_limit: 9500m    # +3GB swap buffer
       environment:
         BATCH_POOL_SIZE: "3"  # 恢复默认 (单实例峰值 ~1.8GB × 3 = 5.4GB < 6.5GB)
         SINGLE_POOL_SIZE: "2"
         REFINE_POOL_SIZE: "2"
     ```
     `git commit` + `git push` + `ssh tencent-prod 'git pull && docker compose up -d'` (必须 `up -d` 不是 `restart`, mem_limit 改动需 recreate)
  4. **验证升级生效** (对照 2C2G Block 1 7 项清单):
     - `docker stats --no-stream` MEM LIMIT ≈ 6.34GiB
     - `docker inspect ...HostConfig.Memory` = 6815744000
     - `docker compose exec printenv BATCH_POOL_SIZE` = 3
     - `curl http://localhost:5000/` = 200/302
     - 日志 clean
  5. **真实并发验证** (升配的核心目的):
     - 用户发 5–10 产品批次, `docker stats` 峰值 MEM USAGE 应 < 5GB
     - `dmesg | grep oom` 无新增
     - 单产品均耗时 40s → ~20s (3 并发 + CPU 不再是瓶颈)
  6. **观察 2 周**无 OOM + swap 使用 < 500MB → 收工; 出问题腾讯云控制台再降配回 2C2G
  7. **4C8G 稳后才开始阶段八 UX** (否则性能/UX 改动混在一起难 debug)
- [ ] **僵尸批次自愈** (2026-04-21 OOM 事故暴露, 详见"技术债 / 经验教训 → 容器资源限额 + 僵尸批次自愈"):
  - `batch_processor.process_one_product` 顶层 try/except → try/finally (status update 放 finally)
  - 新增 `POST /api/batch/<id>/reset-stuck-items` 端点, 刷 > N 分钟未动的 processing → failed
  - `batch/history.html` 显示"有卡住 item"提示 + reset 按钮
- [ ] **Postgres 接入**：
  - `.env` 改 `DATABASE_URL=postgresql://xiaoxi:<pwd>@db:5432/xiaoxi`
  - `docker compose --profile full up -d`
  - `python scripts/migrate_sqlite_to_pg.py --commit` 把现有 SQLite 数据迁移
  - `flask db upgrade`（`with_for_update(skip_locked=True)` 这时才真正跨 worker 生效）
- [ ] **Redis 接入**：
  - `.env` 改 `PUBSUB_BACKEND=redis` + `REDIS_URL=redis://:<pwd>@redis:6379/0`
  - 跨 worker WebSocket pub/sub 打通（当前 memory backend 单 worker 可用，多 worker 推送会丢）
- [ ] **sshd 安全收紧** ⚠️：
  - `PasswordAuthentication no` + `PermitRootLogin prohibit-password`
  - 操作风险：改完重启 ssh 可能把自己锁门外。规程：保持一个活 ssh 会话不关，在另一个会话里改 + 重启 + 新开验证，失败就回改
  - 当前状态：密钥登录已 work，密码通道仍开着，属"不紧急但必须做"
- [ ] **`db.create_all()` 生产环境兜底精简**：
  - app.py 启动时的 `db.create_all()` 仅保留 `FLASK_ENV=development` 分支
  - 生产走纯 Alembic，防止未来加字段时两边都想创建导致冲突
- [ ] **备份自动化**：cron daily SQLite/PG + uploads tar.gz → 腾讯云 COS（当前只有 `/root/backup_20260421/` 这一次手工备份）
- [ ] **日志 + 监控**：至少加 logrotate（docker compose logs 不清会占磁盘），锦上添花是 promtail/loki/grafana
- [ ] **docker-compose.full.yml override**：把 `web.depends_on` 补回来（当前主 compose 文件因 Compose V2 profile gating 限制移除了 depends_on，full 部署需要再 override）

### 阶段八：用户体验打磨 🔜 待启动 (2026-04-21 生产第二批观察后新增)

**背景**: 生产二批 (3 产品 87MB) 跑通后, 用户观察到 4 类 UX 问题。阶段七聚焦硬件/性能, 阶段八聚焦"看得见的顺滑度"。今晚**只诊断不修代码**, 明天 review 优先级。

#### 8.1 上传交互丝滑化 (问题1)

**现象**: `/batch/upload` 点击文件夹图标 (📁 emoji) 不触发文件对话框, 必须点旁边蓝色 padding 区域才触发。

**代码现状** (`templates/batch/upload.html:580-585`):
```html
<label class="picker" id="picker">
  <div class="icon">📁</div>
  <div class="hint" id="pickerHint">选择产品文件夹</div>
  <div class="sub">...</div>
  <input type="file" id="folderInput" webkitdirectory directory multiple>
</label>
```

**根因分析** (已排除 + 锁定):
- ✅ 结构合法: input 嵌套在 label 内, 走"implicit association", HTML spec 规定点击 label 任何子孙都应触发 input
- ✅ 无 `preventDefault` / `stopPropagation` 干扰 (`grep preventDefault|stopPropagation templates/batch/upload.html` → 0 命中)
- ✅ JS 层只有 `folderInput.addEventListener('change', ...)` (L666), 无 click 拦截
- ✅ CSS 层 `.picker { cursor: pointer }` L89, `.picker input[type="file"] { display: none }` L98 正常
- ✅ 其他 `pointer-events:none` / `z-index` hit (L376/438/446/458) 都作用在 modal / nav / disabled 状态, 不影响 picker
- ❌ **最可能原因**: Chrome on Windows 11 下 Segoe UI Emoji 字体把 📁 渲染成彩色位图图层, 形成独立 hit target; 该图层在特定 Chrome 版本里不冒泡到 label, 配合 input 的 `display: none`, click forward 偶发失败

**修复方案** (推荐 A+B 叠加, 共 5 行代码):
- **A (CSS)**: `.picker .icon, .picker .hint, .picker .sub { pointer-events: none; }` — 点击穿透到 label 本身, label 再触发嵌套 input。对 emoji / 文字 / SVG icon 都稳
- **B (JS 兜底)**: `picker.addEventListener('click', e => { if (e.target !== folderInput) folderInput.click(); })` — 不论 CSS 或浏览器状态, 强制触发。防御性写法
- **验证方法**: Chrome + Edge 分别点击图标、文字、"蓝色空白", 三者都应弹出文件对话框
- **工作量**: 5–10 分钟, 纯前端, 零后端改动

#### 8.2 Loading 动画 / 进度视觉反馈 (问题4)

**现状盘点** (全站 loading 交互点):

| 交互点 | 现有反馈 | 评级 |
|---|---|---|
| `workspace.html` AI 长图生成 | Spinner + 进度文案 + 全屏 overlay (L584, 698, 966-973) | ★★★★ 已相对完善, 有"情绪" |
| `batch/upload.html` 上传 | `正在上传...` 纯文字 (L712) | ★★ 差: 87MB 上传 5 分钟用户以为卡死 |
| `batch/upload.html` 打包 (JSZip) | `打包中(浏览器内 JSZip 压缩)...` 纯文字 (L710) | ★★ 差: 大批量 30s+ 无进度 |
| `batch/upload.html` 费用估算弹窗 | `正在计算费用…` 纯文字 (L602) | ★★ 差 |
| `batch/upload.html` 批处理 | progress-card (0–100% 总进度) + 每行产品静态 badge (L1030-1063) | ★★★ 中: 有总进度, 缺每产品阶段感 |
| `batch/history.html` 列表 | 静态 status badges, 无 live 心跳 (L193-200) | ★★ 差: 要刷新才更新 |
| 首屏加载 | 无 skeleton | ★★★ 中: 页面够轻, 问题不突出 |

**后端抓手** (关键发现): `batch_processor.py` 的 print 埋点完整 (L243 DeepSeek 解析 / L251 parsed.json 落盘 / L270 rembg 抠图 / L274 product_cut.png 完成 / L285 渲染 / L188 截图完成), **目前只进 stdout, 没经 pubsub 推到 WebSocket**, 前端因此拿不到 per-stage 进度。要做"每产品阶段动画"只需把这些 print 点同步 publish 即可, 不重构。

**⚠ 同时发现的坑**: `batch_processor.py` 全文 `grep time.time|elapsed|耗时|duration` → **0 命中**。没有任何阶段计时埋点, 所以"剩余时间"只能靠前端粗估 (上传按 XHR.upload.loaded / total, 批处理按已完成比例线性外推), 短期不做精准 ETA。

**4 个并列方案** (明天决定优先级):

**方案 A — 进度文案 + 轻量 Lottie 图标** (统一视觉, 情绪感)
- 找 4–6 个免费 Lottie 小动画 (folder-opening / scissors / paint-brush / camera-shutter)
- 封装 Jinja macro `{% macro loading_block(variant, text) %}`
- 全站 loading 场景统一换皮
- **工作量**: 1 晚 (找 Lottie + 封装)
- **收益**: 视觉统一有"情绪", **不**解决"不知道卡在哪"的焦虑

**方案 B — 每产品阶段动画** (批处理专用, 杀"以为卡死"感)
- 产品行 pill: `解析中 🤖` → `抠图中 ✂️` → `渲染中 🎨` → `截图中 📸` → `完成 ✓`
- 后端: `batch_processor.py` 每个 print 点同步 pubsub publish `item.stage_update` 事件 (沿用现有 WS 通道)
- 前端: `openWS` 的 `handleEvent` 加 `case 'item.stage_update'` → 更新行内 pill + emoji 轻微 bounce 动画
- **工作量**: 半天 (后端 ~30 行 + 前端 ~40 行, 抓手已在)
- **收益**: **杀手级** — 直接解决批量生成时"不知道每个产品跑到哪一步"

**方案 C — Skeleton 骨架屏** (数据加载中的结构化占位)
- `batch/history.html` 列表 / admin 详情页加载期间
- 灰色色块 + subtle pulse 动画
- **工作量**: 1 晚 (CSS 封装 + 各页应用)
- **收益**: 低, 当前页面够轻, 问题不是痛点

**方案 D — 上传进度条 + 剩余时间** (解决"上传看不到进度")
- 改 `btnUpload` handler 里 `fetch('/api/batch/upload', ...)` → `new XMLHttpRequest()`
  (fetch 原生不支持 upload progress; Chrome 137+ 的 ReadableStream request body 方案仍不稳)
- `xhr.upload.onprogress` 每 200ms 更新: `上传中 37% · 2.1 MB/s · 剩余 45s`
- **工作量**: 半小时 (改 upload.html ~15 行 JS)
- **收益**: **最高性价比** — 单次改动解决 87MB 批次的用户焦虑

**推荐排期** (供明天决定):

| 优先级 | 方案 | 工作量 | 理由 |
|---|---|---|---|
| 必做 1 | D 上传进度 + ETA | 半小时 | 收益/成本最高 |
| 必做 2 | B 每产品阶段动画 | 半天 | 杀手级体验, 后端抓手已有 |
| 锦上添花 | A Lottie 统一皮肤 | 1 晚 | 视觉升级, 非紧急 |
| 可延后 | C skeleton | 1 晚 | 当前不是痛点 |

#### 8.3 其他 UX 小坑汇总

(空, 后续观察到的小问题往这里堆, 集中一个版本清)

#### 已知物理限制 (不归阶段八修复范围, 问题2 归档)

**问题2: 上传速度慢 (87MB / 3 产品)**

**分析**:
- 87MB / 3 产品 ≈ 29MB/产品 (主要来自 detail_image_paths 原始大图)
- 中国家庭宽带典型上行 2–10 Mbps = 0.25–1.25 MB/s → 理论上传 70s (10Mbps) ~ 350s (2Mbps)
- 叠加客户端 JSZip DEFLATE 压缩: 对已压缩的 JPEG/PNG 压缩率 ≈ 0, 反而多耗 5–15s CPU (grep 代码 L701: `compression: 'DEFLATE'`)

**本质**: 受限于用户本地上行带宽, 物理下限不可越。

**可选优化** (边际收益):
- **可做 (合并进方案 D)**: 显示实时 % + 预估剩余时间, 化"焦虑"为"耐心"
- **可做**: 客户端 Canvas 压缩大图 (JPEG quality 0.85–0.9, 大 PNG 转 JPG, 仅限详情图; 产品主图保原透明) — 可减 30–50% 体积, 需 opt-in 复选框
- **可做**: 跳过 ZIP → FormData 多文件并发 (浏览器限同域 ~6 并发) → 小幅收益 (省打包 CPU + RAM); 但会增加后端 unzip → 多路径拼接的复杂度, 不推荐
- **不能做**:
  - CDN inbound 上行加速: CDN 加速的是下行缓存, 对用户→源站上行无益
  - 分片上传 (TUS / S3 multipart): 87MB 不至于, 工程量过重
  - 扩服务器带宽: 瓶颈在用户端, 不在服务器

**结论**: 进度反馈先做 (方案 D), 压缩 opt-in 二期考虑, 其余不改。

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

### 中国部署铁律 (2026-04-21 生产上线踩坑 4 次后立碑)

**详细案例**见 `docs/2026-04-21_踩坑复盘_生产上线.md` → "坑 1：Playwright chromium 首次安装卡死"。

**铁律 1 — 凡是默认从 Azure/Google/AWS 下载的依赖，必须额外配国内镜像**：
pypi/npm 镜像只管 Python 包 / Node 包，**二进制资源走独立下载链路**。典型一把梭：
- `playwright install` → chromium 从 Azure CDN → 中国大陆大文件 TLS 握手 + backoff 死循环（40 分钟零字节）
- `puppeteer install` → 同理，`PUPPETEER_DOWNLOAD_HOST` 必配
- `electron-builder` → ELECTRON_MIRROR
- `chromedriver-manager` → `CHROMEDRIVER_CDNURL`
- `selenium-manager` → 现在还没好用的大陆镜像
- rembg `.onnx` model → 走 `ghfast.top` 前置（已在 Dockerfile 实装）

**判定规则**：看 pip/npm 这个包的 install 脚本里有没有"再触发第二次下载"的代码（hook / post-install script / 启动时懒加载）。有 → 必须配二级镜像。

**铁律 2 — 单 DOWNLOAD_HOST 不一定覆盖所有二进制**：
playwright 1.58+ 把 Chrome 分发改用 Chrome for Testing，URL 结构 `{HOST}/{chrome_version}/linux64/chrome-linux64.zip`；但 ffmpeg 仍是老结构 `{HOST}/builds/ffmpeg/{rev}/ffmpeg-linux.zip`。
npmmirror 把这两套东西存在不同前缀下（`/binaries/chrome-for-testing/` vs `/binaries/playwright/builds/ffmpeg/`），**单个 HOST 覆盖不了两个**。
→ 必须拆两阶段 RUN，每次改 env。顺序铁律：**先装小+独立的（ffmpeg 2MB），后装大+批量的（chromium 167MB）**。反过来大文件先跑、小文件炸掉会把大文件的 `INSTALLATION_COMPLETE` marker 一起带走，第二阶段会重下。

**铁律 3 — 失败快 > 失败慢**：
下载卡住 **90 秒没进度 + `netstat | grep ESTABLISHED` 外部 TCP=0** → 立刻 kill 换镜像。别等"可能它会好"。实测对比：
- 等 Azure 救 → 40 分钟零字节
- 换 npmmirror → 10 秒 HTTP 404（说明路径错，立刻修）
- 修好后 → 200 秒下完 167MB

失败快时间预算是正确路径的 10%，值得。

### Alembic 接管 `db.create_all()` 老 DB 铁律 (2026-04-21 生产首次 migration 踩坑)

**症状触发**：新镜像跑 `flask db upgrade` 遭遇 `sqlite3.OperationalError: table users already exists`，同时 `alembic_version` 表存在但 `version_num` 为空。

**根因**：老代码启动时 `db.create_all()` 已经把所有 model 建过表；新代码切到 Alembic 管 schema，baseline migration 又要从零 `create_table('users', ...)` → 表已存在 → 炸。`alembic_version` 表本身是 Alembic 初始化自动建的"容器"，**里面的 version_num 才是"哪个 migration 已跑"的记录**。空 = "我什么都没跑过"。

**修法 — `flask db stamp <baseline_revision>`**：
告诉 Alembic "这个版本号当作已应用、不要真跑 SQL"。补的是**记录**不是**表**。前提是：`inspect(db.engine).get_table_names()` 返回的表集合 == baseline migration 里 `op.create_table(...)` 的集合（通常成立，因为两者都从同一个 models.py 出）。

**铁律 4 — 从 `create_all` 过渡到 Alembic 的第一次部署，预检 → 决策**：
1. `inspect(db.engine).get_table_names()` → 列出所有表
2. `SELECT version_num FROM alembic_version` → 看是否为空
3. 对比 `migrations/versions/` 的 baseline migration → 两边表集合
4. 一致 → `flask db stamp baseline`；不一致 → 手工写 conditional migration 或先 ALTER

**铁律 5 — 生产分支尽快把 `db.create_all()` 从启动流程砍掉**：
未来 models 加字段时 Alembic 和 `create_all` 会打架（哪个先跑哪个赢不确定），debug 成本高。
当前 app.py 保留 `db.create_all()` 做 SQLite 开发兜底 —— 阶段七 PG 上线后，加 `FLASK_ENV != 'development'` 判断把生产路径关闭。

### SSH 免密配置排查三板斧 (2026-04-21 首次登录失败后立碑)

**详细案例**见 `docs/2026-04-21_踩坑复盘_生产上线.md` → "坑 3：SSH 免密卡在 authorized_keys 格式错误"。

**症状**：Permission denied (publickey)，但公钥已贴、`chmod 600` 到位、`sshd -T` 显示 `pubkeyauthentication yes`。
**根因**：Web 终端 heredoc 粘贴时把提示文字混进了 authorized_keys 行首 → 整行开头不是合法 key 类型 → sshd 拒识别。

**铁律 6 — 配 SSH 免密登录失败，按这三条查：**

1. **`cat authorized_keys` 看 raw bytes**：
   公钥必须**一整行**（不能折行），开头必须严格匹配 `ssh-rsa` / `ssh-ed25519` / `ecdsa-sha2-*` / `sk-ssh-*`。任何前缀（注释 / 提示文字 / BOM）都会让整行失效。**Web 终端粘贴最容易带脏字符** —— 用 `echo 'ssh-ed25519 AAAA... user@host' > ~/.ssh/authorized_keys` 单引号强制写入，绕开 heredoc 变量展开和续行问题。

2. **`sshd -T | grep -E 'publickey|authorized'`**：
   确认 sshd **当前生效值**（不是 `/etc/ssh/sshd_config` 注释掉的配置）是否启用 publickey、authorized_keys 路径是否如预期。`sshd -T` 比读 config 文件靠谱一万倍。

3. **`ls -la ~/.ssh/` + `ls -la ~/`**：
   权限必须 `700 ~/.ssh`、`600 authorized_keys`、`~/` 的 owner 必须是目标用户。任何一处 world-writable 都会被 sshd 拒绝（`StrictModes yes` 默认开）。

**铁律 7 — 第一次配完立刻写 `~/.ssh/config` 起别名**：
```
Host tencent-prod
    HostName 124.221.23.173
    User root
    IdentityFile ~/.ssh/id_ed25519
    ServerAliveInterval 60
```
之后所有命令走别名。Windows 下用 PowerShell `Out-File -Encoding ascii` 避免 UTF-8 BOM 毒化 config 文件。

### 容器资源限额 + 僵尸批次自愈 (2026-04-21 生产 OOM 事故立碑)

**详细案例**见 `docs/2026-04-21_踩坑复盘_生产上线.md` → "坑 7：生产 OOM 事故 —— Docker 默认禁 swap + 并发池未收敛"。

**铁律 8 — docker-compose 服务必显式配资源限额 + 并发池**:

`mem_limit` 默认 = 主机全 RAM; `memswap_limit` 默认 = `mem_limit` (即**禁 swap**). 两个默认值叠加 + 并发池未收敛, 2C2G 机器必 OOM。2026-04-21 晚三个产品在 rembg/Playwright 阶段被 SIGKILL, 主机 `free -h` 看到 swap 1.9GB 存在但容器根本摸不到。

**上线清单** (每条 docker-compose service 必过):
1. `mem_limit` < 主机 RAM × 0.85? (留 15% 给 sshd/journald/docker daemon)
2. `memswap_limit` ≥ `mem_limit` (一般 2× 到 3×, 给 Chromium 冷启偶发峰值兜底)?
3. 每个 CPU/RAM-bound 并发池都有 env var 控制 (不在代码里写死)?
4. 单实例峰值 RAM × 并发上限 < `mem_limit` × 0.8?

**判定工具**:
- `docker stats --no-stream` 看 MEM LIMIT (这是硬顶, 不是 MEM USAGE)
- `docker inspect <ct> --format '{{.HostConfig.Memory}} {{.HostConfig.MemorySwap}}'` 看字节级精确值
- 主机 `free -h` 查 swap 是否真存在 (存在 ≠ 容器能用)
- `sudo dmesg -T | grep -iE 'oom|memcg'` 查历史 OOM
- `sudo journalctl -k | grep oom-kill` 看 cgroup 作用域是否容器级

**已落地修复 (commit `0fa36fa`)**: `docker-compose.yml` web 服务下显式 `mem_limit: 1400m` + `memswap_limit: 3400m` + `BATCH_POOL_SIZE/SINGLE_POOL_SIZE/REFINE_POOL_SIZE: "1"`。放 compose.yml 不放 `.env` 的理由: 非机密部署参数, 进 git 方便 code review + 回滚; `.env` 只留密钥/连接串。

**僵尸批次自愈 — 阶段七 TODO**:
OOM 或其他崩溃后 items 卡 `status=processing`; `app.py:5146-5162` startup-recovery 仅在**容器完整重启**时触发, **worker 个别 SIGKILL 后 gunicorn 自动 respawn 同一 worker 不触发**。错误消息统一 "服务重启中断, 请手动重新提交", 不区分 OOM。需补:
1. `batch_processor.process_one_product` 顶层 try/except → try/finally (SIGKILL 仍无效, 但 graceful crash 能兜)
2. `POST /api/batch/<id>/reset-stuck-items` 端点, 刷 > N 分钟未动的 processing → failed
3. `batch/history.html` 显示"有卡住 item"提示 + 直达 reset 按钮

**4C8G 升级后这些参数要同步调**, 详见 阶段七 "4C8G 升级具体步骤"。

## 用户偏好
- 用户能看 JSON 字段对错，但不直接读 Python 代码 → 验证步骤要写"预期看到 X"而不是"运行什么测试"
- 用户用 curl 验证（但需要登录态时改用 requests.Session 脚本，curl + CSRF 在 PowerShell 里太啰嗦）
- 用户喜欢 4 选 1 的反馈模板（OK/不对/方向错/跳过）

## 待解决问题

### 延后到阶段七（2026-04-21 生产上线时主动延后，不属于"忘记做"）

- **sshd PasswordAuthentication 收紧**：当前 `PasswordAuthentication yes`，密钥登录已 work 但密码通道仍开着。改动窗口需要在白天 + 保持一个 ssh 会话活着防锁门。详见 `docs/2026-04-21_踩坑复盘_生产上线.md` → "坑 4 (遗留)"。
- **PG + Redis 上大机**：当前 2C2G 撑不起全栈，SQLite + memory pub/sub 单机已满足个人测试。升 4C8G 后执行 `docker compose --profile full up -d` + `scripts/migrate_sqlite_to_pg.py`。
- **`db.create_all()` 生产路径关闭**：app.py 启动时的 `db.create_all()` 仅保留 `FLASK_ENV=development` 分支，防止未来 migration 和 `create_all` 打架。
- **DEPLOYMENT.md 正式整理**：当前部署经验落在 `docs/2026-04-21_踩坑复盘_生产上线.md`，后续整理成带"首次部署 + 滚动升级 + 回滚"三部分的独立文档。
- **🆕 僵尸批次自愈** (2026-04-21 OOM 事故暴露)：OOM / worker SIGKILL 后 items 卡 `status=processing`, 当前 startup-recovery 仅在容器完整重启时跑, worker 个别被杀后 gunicorn 自动 respawn 不触发。前端用户只能等下次容器重启。详见"技术债 → 容器资源限额 + 僵尸批次自愈"; TODO: try/finally 兜底 + `/api/batch/<id>/reset-stuck-items` + UI reset 按钮。
- **🆕 升 4C8G 后同步调容器资源** (2026-04-21 OOM 事故应急已配 1400m/3400m/池=1)：升配后要把 `mem_limit` 调到 6500m / `memswap_limit` 9500m / 并发池回 3，详见阶段七 "4C8G 升级具体步骤" 第 3 步。

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
