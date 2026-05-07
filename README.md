# 小玺AI — 产品详情页自动生成器

> 上传产品图 + 粘贴文案，AI 自动生成电商详情页长图，一键导出高清 PNG。

---

## 核心亮点

- **AI 智能识别** — 粘贴产品文案，DeepSeek 自动提取参数、生成营销卖点
- **积木式模板** — 英雄屏、优势网格、清洁故事、VS 对比、参数表等 20+ 模块自由组合
- **一键导出** — Playwright 截图，直接输出 750px 宽电商详情页长图
- **自动抠图** — rembg 智能去背景，产品图自动处理为白底/透明
- **多品类支持** — 设备类、配件类、耗材类、工具类，各有专属模板和 AI 提示词
- **多用户系统** — 注册登录、管理后台、用量统计、API Key 各自独立

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，填写必要配置：

```bash
cp .env.example .env
```

> 每位用户在网页「账号设置」中自行配置 DeepSeek API Key，无需在服务端设置。

### 3. 启动

```bash
python app.py
```

访问 **http://localhost:5000**

---

## 使用流程

```
选择品类 → 上传产品图/场景图 → 粘贴产品文案 → 点击"AI识别"自动填表
                                                      ↓
                                 导出高清 PNG ← 预览详情页 ← 生成预览
```

---

## Docker 部署

```bash
docker build -t clean-ai .
docker run -d --name clean-ai \
  -p 5000:5000 \
  -e SECRET_KEY="你的密钥" \
  -e FERNET_KEY="你的加密key" \
  --restart unless-stopped \
  clean-ai
```

---

## 技术栈

| 组件 | 说明 |
|------|------|
| Flask | Web 框架 + 用户系统 |
| DeepSeek API | AI 文案解析与卖点生成 |
| Playwright | 详情页截图导出 |
| rembg | 产品图自动抠图 |
| SQLite | 用户数据与使用日志 |

---

## 项目结构

```
app.py                  主应用
admin.py                管理后台
auth.py                 登录注册
models.py               数据模型
crypto_utils.py         API Key 加解密
templates/
  build_form.html       产品填表页
  blocks/               20+ 积木模块
  设备类/                设备类模板配置
  配件类/                配件类模板配置
  耗材类/                耗材类模板配置
  工具类/                工具类模板配置
static/
  scenes/               通用场景图
  设备类/                设备类固定卖点图
```

---

## 许可

仅供内部使用。
