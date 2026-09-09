# 墨白云 - 测试与打包指南

本文档说明如何本地测试墨白云应用、打包为 Windows 单文件 exe，以及 API 错误处理建议。

---

## 一、环境准备

- Python 3.8+
- 已安装依赖：`pip install -r requirements.txt`
- （可选）配置环境变量：AI 与 TTS 所需 API Key，见项目根目录或 `.env` 说明

---

## 二、本地测试

### 2.1 启动应用

在项目根目录执行：

```bash
python mobaiyun_app.py
```

默认在 `http://0.0.0.0:5000` 启动，本地浏览器访问：

**http://localhost:5000**

### 2.2 测试步骤

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1. 登录 | 打开 localhost:5000，输入用户名 `DAWN`、密码 `YYICLY`，点击「登录」 | 跳转到 AI 对话页 `/chat` |
| 2. 角色管理 | 在聊天页面，使用角色管理面板进行角色添加、编辑、删除操作 | 角色列表实时更新，操作有成功提示；删除角色后相关对话历史被清理 |
| 3. TTS 设置 | 在 TTS 设置面板中调整语言、语音、说话风格、角色扮演、语速、语调等参数 | 设置自动保存到 localStorage，语音合成使用新参数生成音频 |
| 4. 对话测试 | 在输入框输入一条消息，点击「发送」或按回车 | 历史区先出现用户消息，再出现助手回复；若已配置 AI Key，应收到正常回复 |
| 5. 语音播放 | 发送消息后等待回复；若已配置 Azure TTS | 助手回复下方出现音频条，并自动播放（或可点击播放） |
| 6. 移动端适配 | 在手机浏览器或开发者工具中模拟移动端视图，测试角色管理面板和 TTS 设置的展开/收起功能 | 移动端界面正常显示，滑动功能正常，控制面板展开时覆盖聊天框 |

### 2.3 测试要点

- **登录**：错误密码应提示「用户名或密码错误」；未登录直接访问 `/chat` 应重定向到 `/login`。
- **对话**：未配置任一 AI Key 时，助手会返回配置提示类文案；已配置则按当前选择的 AI（kimi/glm/doubao）调用并返回内容。
- **角色**：选择不同角色后发送，回复应体现该角色的 system prompt；角色管理（添加、编辑、删除）功能正常，删除角色后相关对话历史被清理。
- **TTS 设置**：语音设置面板可调整语言、语音、风格、角色、语速、语调等参数，设置自动保存到 localStorage 并在刷新后保持。
- **语音**：未配置 `AZURE_SPEECH_KEY` / `AZURE_SPEECH_REGION` 时无音频；配置正确时应生成 MP3 并返回可播放的 `audio_url`；TTS 参数变化影响语音效果。
- **移动端适配**：在移动设备上界面正常显示，角色管理和 TTS 设置面板可展开/收起，滑动功能正常，控制面板展开时覆盖聊天框避免内容显示不全。

---

## 三、打包成 Windows exe（PyInstaller）

### 3.1 安装 PyInstaller

```bash
pip install pyinstaller
```

### 3.2 打包命令

在项目根目录（与 `mobaiyun_app.py` 同级）执行：

```bash
pyinstaller --onefile --add-data "templates;templates" --add-data "static;static" mobaiyun_app.py
```

- **Windows**：`--add-data` 使用分号 `;` 分隔「源路径;目标路径」。
- **Linux/macOS**：若需在同一命令中指定多资源，使用冒号 `:`，例如：  
  `--add-data "templates:templates" --add-data "static:static"`。

### 3.3 输出与运行

- 生成的 exe 位于：`dist/mobaiyun_app.exe`。
- 将 exe 拷贝到任意目录即可运行；**首次运行会在 exe 所在目录生成 `users.db`**。
- 模板与静态资源已打包进 exe，无需单独携带 `templates`、`static` 文件夹（PyInstaller 会解压到临时目录供程序使用）。

### 3.4 注意事项

- 打包前请在本机先执行一遍完整测试，确保 `python mobaiyun_app.py` 行为正常。
- 若使用虚拟环境，建议在虚拟环境中安装依赖并执行上述 `pyinstaller` 命令。
- 杀毒软件可能误报，可添加排除或从可信任目录运行。

---

## 四、错误处理建议

### 4.1 API 调用侧（后端）

- 在 **AI 调用**（如 `get_ai_response`）外已有 `try-except` 时，建议将异常信息以**可读文案**返回给前端，而不是仅记录日志。例如在 SocketIO 的 `send_message` 处理中，若 `get_ai_response` 抛出异常，可 `except Exception as e` 后 `emit("receive_message", {"response": f"AI 调用失败: {e}", "audio_url": None})`。
- 在 **TTS（speak_text_to_file）** 等可能失败的操作外，建议使用 try-except，失败时仍正常返回文字回复，仅将 `audio_url` 置为 `None`，并在服务端记录错误便于排查。
- **路由**（如 `/add_role`）：对无效参数或数据库错误使用 try-except，返回明确 HTTP 状态码和 JSON 错误信息（如 `{"ok": false, "error": "原因"}`），便于前端统一提示。

### 4.2 前端

- 对 SocketIO 的 `receive_message`：若 `data.response` 为错误提示文案，可识别并高亮或单独样式展示（例如以「错误」标签显示）。
- 对 `fetch("/add_role")`：根据返回的 `ok` 与 `error` 字段给出成功或失败提示，并在失败时不要执行 `reload`。

在 API 调用中补充上述 try-except 并将错误返回前端，可让用户在界面直接看到失败原因，便于测试与排错。

---

## 五、快速检查清单

- [ ] `python mobaiyun_app.py` 能正常启动
- [ ] 浏览器访问 http://localhost:5000 能打开登录页
- [ ] 使用 DAWN/YYICLY 能登录并进入对话页
- [ ] 发送消息能收到助手回复（或明确配置错误提示）
- [ ] 角色管理（添加、编辑、删除）功能正常
- [ ] TTS 设置面板配置后语音效果变化
- [ ] 移动端界面适配正常，控制面板展开/收起功能正常
- [ ] PyInstaller 打包命令在项目根目录执行成功
- [ ] 运行 `dist/mobaiyun_app.exe` 后访问 localhost:5000 行为与开发环境一致
