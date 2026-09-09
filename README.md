# 墨白云 (MoBaiYun)

基于 Flask + Socket.IO 的中文 AI 角色扮演对话 Web 应用。

## 功能

- **多 AI 引擎**：DeepSeek（OpenAI 兼容接口）
- **角色扮演**：创建 / 编辑 / 删除角色，每个角色有独立的 system prompt 和对话历史
- **Azure TTS 语音合成**：支持中文普通话、多种方言及英语 / 日语 / 韩语等多语种
- **用户系统**：注册登录、不同账号数据隔离、管理员面板
- **自动记忆**：每 10 轮对话自动提取并合并用户记忆与角色记忆
- **对话持久化**：SQLite 存储，移动端适配

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key（复制 .env.example 为 .env 后填写）
#    DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL
#    AZURE_SPEECH_KEY / AZURE_SPEECH_REGION (可选)

# 3. 启动开发服务器
python mobaiyun_app.py

# 4. 浏览器访问 http://localhost:5000
```

首次启动会自动创建默认账号 `DAWN` / `YYICLY` 和管理员 `Dawnlarism` / `DAWN`。**上线前请修改默认密码。**

## 生产部署

使用 gunicorn + gevent：

```bash
gunicorn -k gevent -w 1 -b 127.0.0.1:5000 wsgi:app
```

Nginx 配置示例见 `dawnlarism.cn`。

## 项目结构

```
mobaiyun/
├── mobaiyun_app.py      # 后端主入口
├── wsgi.py              # gunicorn 入口
├── requirements.txt     # 依赖
├── templates/           # 页面模板
├── static/              # 静态资源
├── mobaiyun_app.spec    # PyInstaller 打包配置
└── dawnlarism.cn        # Nginx 配置示例
```

## 安全提示

- `.env` 已被 `.gitignore` 排除，请勿将真实 API Key 提交到仓库
- 生产环境务必设置强 `FLASK_SECRET_KEY`（通过环境变量或 `.env`）
- 首次部署后请修改默认账号密码
