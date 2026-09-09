# -*- coding: utf-8 -*-
"""
墨白云 (Mobaiyun) Web 应用 - 主后端入口
- 登录页面与 AI 对话页面
- 支持 DeepSeek API、角色设定、Azure TTS、对话历史持久化 (SQLite)
- 兼容 Windows，可打包为 exe
"""

import os
import sys

# 确保项目根目录在 path 中，便于打包 exe 后加载资源
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

# 从 .env 文件加载配置（exe 打包后在 exe 同级目录，开发时在项目根目录）
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

ENV_PATH = os.path.join(BASE_DIR, ".env")
if not os.path.isfile(ENV_PATH) and getattr(sys, "frozen", False):
    # 打包后 .env 可能在 _internal 里，第一次运行时复制到 exe 同级目录
    internal_env = os.path.join(sys._MEIPASS, ".env") if hasattr(sys, '_MEIPASS') else None
    if internal_env and os.path.isfile(internal_env):
        import shutil
        shutil.copy(internal_env, ENV_PATH)

if load_dotenv and os.path.isfile(ENV_PATH):
    load_dotenv(ENV_PATH)


# 环境变量：API Keys（load_dotenv 已加载，这里补默认值）
os.environ.setdefault("DEEPSEEK_API_KEY", "")
os.environ.setdefault("DEEPSEEK_BASE_URL", "")
os.environ.setdefault("DEEPSEEK_MODEL", "")
os.environ.setdefault("AZURE_SPEECH_KEY", "")
os.environ.setdefault("AZURE_SPEECH_REGION", "")
os.environ.setdefault("FLASK_SECRET_KEY", "mobaiyun-dev-secret-change-me")

# 数据库路径（运行时生成）
DB_PATH = os.path.join(BASE_DIR, "users.db")

# ---------------------------------------------------------------------------
# 第三方库导入
# ---------------------------------------------------------------------------
import json
import xml.sax.saxutils
import sqlite3
import threading, glob
import time
import uuid
import re
import logging
from flask import Flask, request, redirect, url_for, render_template, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash

from openai import OpenAI  # DeepSeek 使用 OpenAI 兼容接口
from azure.cognitiveservices.speech import (
    SpeechConfig,
    SpeechSynthesizer,
    AudioConfig,
    SpeechSynthesisOutputFormat,
    ResultReason,
    CancellationReason,
    CancellationDetails,
)

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ---------------------------------------------------------------------------
# 应用初始化
# ---------------------------------------------------------------------------
# 确定模板和静态文件夹路径（处理 PyInstaller 打包环境）
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    # PyInstaller 打包环境，资源在 _MEIPASS 目录
    resource_path = sys._MEIPASS
else:
    # 开发环境，使用项目根目录
    resource_path = BASE_DIR

app = Flask(
    __name__,
    template_folder=os.path.join(resource_path, "templates"),
    static_folder=os.path.join(resource_path, "static"),
    static_url_path="/static",
)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY") or "mobaiyun-dev-secret-change-me"

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')


# ---------------------------------------------------------------------------
# Flask-Login 用户模型与加载
# ---------------------------------------------------------------------------
class User(UserMixin):
    def __init__(self, id_, username):
        self.id = id_
        self.username = username

    def get_id(self):
        return str(self.id)


def get_user_by_id(user_id):
    """根据 user_id 从数据库加载用户，供 Flask-Login 使用。"""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    with _db_lock:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "SELECT id, username FROM users WHERE id = ?", (uid,)
            )
            row = cursor.fetchone()
            return User(row[0], row[1]) if row else None
        finally:
            conn.close()


def get_user_by_username(username):
    """根据用户名从数据库加载用户（用于登录验证）。"""
    if not username or not username.strip():
        return None
    with _db_lock:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "SELECT id, username, password FROM users WHERE username = ?",
                (username.strip(),),
            )
            row = cursor.fetchone()
            return (row[0], row[1], row[2]) if row else None
        finally:
            conn.close()


@login_manager.user_loader
def load_user(user_id):
    return get_user_by_id(user_id)


# ---------------------------------------------------------------------------
# 数据库与持久化（SQLite，线程安全）
# ---------------------------------------------------------------------------
_db_lock = threading.Lock()


def get_connection():
    """获取线程本地的 SQLite 连接（每次调用新建，配合锁使用）。"""
    return sqlite3.connect(DB_PATH)


def init_db():
    """初始化数据库：创建 users / roles / history 表，并添加默认用户 DAWN/YYICLY。"""
    with _db_lock:
        conn = get_connection()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL
                );
            """)
            # 迁移：为已有 users 表添加 has_tts 列（如果不存在）
            try:
                conn.execute("ALTER TABLE users ADD COLUMN has_tts INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS roles (
                    user_id INTEGER NOT NULL,
                    role_name TEXT NOT NULL,
                    prompt TEXT,
                    PRIMARY KEY (user_id, role_name),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
            """)
            # 迁移：为已有 roles 表添加记忆列
            for col in [
                "ALTER TABLE roles ADD COLUMN memory TEXT DEFAULT ''",
                "ALTER TABLE roles ADD COLUMN user_memory TEXT DEFAULT ''",
                "ALTER TABLE roles ADD COLUMN memory_round INTEGER DEFAULT 0",
            ]:
                try:
                    conn.execute(col)
                except sqlite3.OperationalError:
                    pass
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS history (
                    user_id INTEGER NOT NULL,
                    role_name TEXT NOT NULL,
                    ai TEXT,
                    messages TEXT,
                    PRIMARY KEY (user_id, role_name),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
            """)
            # 迁移旧数据（如果存在旧表结构）
            cursor = conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='history' 
                AND sql LIKE '%user_id INTEGER PRIMARY KEY%'
            """)
            if cursor.fetchone() is not None:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS history_new (
                        user_id INTEGER NOT NULL,
                        role_name TEXT NOT NULL,
                        ai TEXT,
                        messages TEXT,
                        PRIMARY KEY (user_id, role_name),
                        FOREIGN KEY (user_id) REFERENCES users(id)
                    )
                """)
                conn.execute("""
                    INSERT OR IGNORE INTO history_new (user_id, role_name, ai, messages)
                    SELECT user_id, role, ai, messages FROM history
                    WHERE user_id IS NOT NULL AND role IS NOT NULL
                """)
                conn.execute("DROP TABLE history")
                conn.execute("ALTER TABLE history_new RENAME TO history")
            cursor = conn.execute(
                "SELECT id, has_tts FROM users WHERE username = ?", ("DAWN",)
            )
            row = cursor.fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO users (username, password, has_tts) VALUES (?, ?, 1)",
                    ("DAWN", generate_password_hash("YYICLY")),
                )
            elif row[1] != 1:
                conn.execute(
                    "UPDATE users SET has_tts = 1 WHERE username = ?", ("DAWN",)
                )
            # 创建管理员账号
            cursor = conn.execute(
                "SELECT id FROM users WHERE username = ?", ("Dawnlarism",)
            )
            if cursor.fetchone() is None:
                conn.execute(
                    "INSERT INTO users (username, password, has_tts) VALUES (?, ?, 0)",
                    ("Dawnlarism", generate_password_hash("DAWN")),
                )
            conn.commit()
        finally:
            conn.close()

def load_roles(user_id):
    """加载用户角色，返回 {role_name: prompt} 字典。"""
    with _db_lock:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "SELECT role_name, prompt FROM roles WHERE user_id = ?",
                (user_id,),
            )
            return {row[0]: row[1] for row in cursor.fetchall()}
        finally:
            conn.close()




def user_has_tts(user_id):
    """查询用户是否有 TTS 权限"""
    with _db_lock:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT has_tts FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return bool(row[0]) if row else False
        finally:
            conn.close()

def save_role(user_id, role_name, prompt):
    """保存或更新用户的一个角色。"""
    with _db_lock:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO roles (user_id, role_name, prompt) VALUES (?, ?, ?)",
                (user_id, role_name, prompt),
            )
            conn.commit()
        finally:
            conn.close()


def load_history(user_id, role_name):
    """加载用户特定角色的对话历史，返回 {'role': str, 'ai': str, 'history': list}。"""
    with _db_lock:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "SELECT ai, messages FROM history WHERE user_id = ? AND role_name = ?",
                (user_id, role_name),
            )
            row = cursor.fetchone()
            if row is None:
                return {"role": role_name, "ai": "", "history": []}
            ai, messages = row
            history = json.loads(messages) if messages else []
            return {
                "role": role_name,
                "ai": ai or "",
                "history": history,
            }
        finally:
            conn.close()


def save_history(user_id, role_name, ai, history):
    """保存用户特定角色的对话历史（history 为 list，会序列化为 JSON）。"""
    with _db_lock:
        conn = get_connection()
        try:
            messages = json.dumps(history, ensure_ascii=False)
            conn.execute(
                "INSERT OR REPLACE INTO history (user_id, role_name, ai, messages) VALUES (?, ?, ?, ?)",
                (user_id, role_name, ai or "", messages),
            )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# AI 响应生成（从环境变量获取 API Key 与 SDK）
# ---------------------------------------------------------------------------

def get_ai_response(prompt, history, provider=None):
    """
    调用 DeepSeek API，返回助手回复文本。
    :param prompt: 当前用户输入
    :param history: 消息列表
    :param provider: 保留参数，固定使用 deepseek
    :return: 助手回复内容字符串；失败时返回错误信息字符串
    """
    messages = list(history) if history else []
    messages.append({"role": "user", "content": prompt})

    openai_messages = []
    for m in messages:
        role = (m.get("role") or "user").strip().lower()
        if role not in ("system", "user", "assistant"):
            role = "user"
        openai_messages.append({"role": role, "content": (m.get("content") or "")})

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "")
    model = os.environ.get("DEEPSEEK_MODEL", "")
    if not api_key:
        return "未配置 DEEPSEEK_API_KEY。"
    if not base_url:
        return "未配置 DEEPSEEK_BASE_URL。"
    if not model:
        return "未配置 DEEPSEEK_MODEL。"

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.chat.completions.create(model=model, messages=openai_messages)
        choice = resp.choices[0] if resp.choices else None
        return (choice.message.content if choice and choice.message else "").strip() or ""
    except Exception as e:
        return f"AI 调用失败: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Azure TTS：文本转语音并输出为 MP3 文件（支持中文）
# ---------------------------------------------------------------------------

# 音频文件管理（FIFO，上限5个文件）
MAX_AUDIO_FILES = 5

def _cleanup_old_audio_files():
    """清理旧的音频文件，保留最近 MAX_AUDIO_FILES 个"""
    audio_dir = os.path.join(BASE_DIR, "static")
    pattern = os.path.join(audio_dir, "audio_*.mp3")
    audio_files = glob.glob(pattern)
    if len(audio_files) > MAX_AUDIO_FILES:
        audio_files.sort(key=os.path.getmtime)
        for old_file in audio_files[:len(audio_files) - MAX_AUDIO_FILES]:
            try:
                os.remove(old_file)
            except Exception as e:
                logging.warning(f"音频清理失败 {os.path.basename(old_file)}: {e}")


MEMORY_EXTRACT_INTERVAL = 10

def extract_memory(history_slice, existing_memory, target):
    """调用 DeepSeek 从对话中提取记忆
    target: 'user' 或 'role'
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "")
    model = os.environ.get("DEEPSEEK_MODEL", "")
    if not api_key or not base_url or not model:
        return existing_memory

    if target == "user":
        instruction = "从以下对话和现有记忆中，汇总关于用户的完整个人信息。用简短的短句列出（如：'姓名:小明 | 年龄:25 | 喜欢喝茶'）。只记录用户明确说出的，不要编造，不要加前缀/解释/问候语。如果有新信息，合并到现有记忆中。如果无新信息，仅回复'无'。不要加前缀/解释/问候语。"
    else:
        instruction = "从以下对话和现有记忆中，汇总角色关于自己的完整信息。用简短的短句列出（如：'咖啡店名:墨白 | 养猫'）。只记录角色明确说出的，不要编造，不要加前缀/解释/问候语。如果有新信息，合并到现有记忆中。如果无新信息，仅回复'无'。不要加前缀/解释/问候语。"

    ask = "[现有记忆] " + (existing_memory or "空") + "\n\n[对话内容]\n" + history_slice

    messages = [
        {"role": "system", "content": instruction},
        {"role": "user", "content": ask},
    ]

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.chat.completions.create(
            model=model, messages=messages,
            max_tokens=200, temperature=0.3
        )
        result = (resp.choices[0].message.content or "").strip()
        # 如果结果为空或"无"的近义词，保留原有记忆
        no_new = {"无", "无。", "（无）", "无\n", "无\n", "无新信息", "没有新信息", "暂无", "没有", "暂无新信息", "无新内容"}
        if not result or result in no_new or result.startswith("无"):
            return existing_memory
        # 防止过长
        if len(result) > 500:
            result = result[:500]
        return result
    except Exception as e:
        logging.warning(f"记忆提取失败 ({target}): {e}")
        return existing_memory


def try_extract_memories(user_id, role_name, new_user_msg, new_assistant_msg):
    """每 MEMORY_EXTRACT_INTERVAL 轮提取一次记忆（用户记忆和角色记忆均按对话独立）"""
    with _db_lock:
        conn = get_connection()
        try:
            # 读取当前对话的计数器和记忆
            row = conn.execute(
                "SELECT memory, user_memory, memory_round FROM roles WHERE user_id = ? AND role_name = ?",
                (user_id, role_name),
            ).fetchone()
            if not row:
                return
            role_memory, user_memory, rnd = (row[0] or ""), (row[1] or ""), (row[2] or 0)
            rnd += 1
            conn.execute(
                "UPDATE roles SET memory_round = ? WHERE user_id = ? AND role_name = ?",
                (rnd, user_id, role_name),
            )
            conn.commit()

            if rnd % MEMORY_EXTRACT_INTERVAL != 0:
                return  # 未到提取轮次

            # 读取当前对话历史
            hist_row = conn.execute(
                "SELECT messages FROM history WHERE user_id = ? AND role_name = ?",
                (user_id, role_name),
            ).fetchone()
            if not hist_row:
                return
            messages = json.loads(hist_row[0]) if hist_row[0] else []
            slice_msgs = messages[-20:]
            if len(slice_msgs) < 2:
                return
            history_slice = "\n".join(
                ("用户: " if m["role"] == "user" else "角色: ") + m["content"]
                for m in slice_msgs
            )

            # 提取用户记忆（本次对话中用户透露的信息）
            new_user_memory = extract_memory(history_slice, user_memory, "user")
            if new_user_memory != user_memory:
                conn.execute(
                    "UPDATE roles SET user_memory = ? WHERE user_id = ? AND role_name = ?",
                    (new_user_memory, user_id, role_name),
                )
                conn.commit()
                logging.info(f"用户记忆已更新 [{role_name}]")

            # 提取角色记忆
            new_role_memory = extract_memory(history_slice, role_memory, "role")
            if new_role_memory != role_memory:
                conn.execute(
                    "UPDATE roles SET memory = ? WHERE user_id = ? AND role_name = ?",
                    (new_role_memory, user_id, role_name),
                )
                conn.commit()
                logging.info(f"角色记忆已更新 [{role_name}]")
        except Exception as e:
            logging.error(f"记忆处理异常: {e}")
        finally:
            conn.close()


def load_memories(user_id, role_name):
    """加载当前对话的用户记忆和角色记忆"""
    with _db_lock:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT user_memory, memory FROM roles WHERE user_id = ? AND role_name = ?",
                (user_id, role_name),
            ).fetchone()
            if row:
                return (row[0] or "").strip(), (row[1] or "").strip()
            return "", ""
        finally:
            conn.close()


def speak_text_to_file(text, filename, options=None):
    """
    使用 Azure 认知服务将文本合成为语音并保存为 MP3 文件。
    支持 SSML 格式，可配置语言、语音、风格、角色、语速、语调等参数。
    :param text: 要合成的文本（支持中文）
    :param filename: 输出文件路径（.mp3）
    :param options: 字典，包含以下可选键：
        - enable: bool，是否启用语音合成（默认为 True）
        - language: str，语言代码（如 "zh-CN"），已弃用，请使用locale
        - locale: str，区域设置代码（如 "zh-CN", "zh-CN-sichuan"）
        - voice: str，语音名称（如 "zh-CN-XiaoxiaoNeural"）
        - style: str，说话风格（如 "general", "calm"）
        - role: str，角色扮演（如 "Narrator", "Girl"）
        - rate: float，语速倍数（如 1.0）
        - pitch: str，语调（如 "default", "medium", "high"）
    :return: 成功返回 True，失败返回 False（并记录错误）
    """
    if options is None:
        options = {}
    enable = options.get("enable", True)
    if not enable:
        return False
    key = os.environ.get("AZURE_SPEECH_KEY", "").strip()
    region = os.environ.get("AZURE_SPEECH_REGION", "").strip()
    if not key or not region:
        return False
    try:
        speech_config = SpeechConfig(subscription=key, region=region)
        speech_config.set_speech_synthesis_output_format(
            SpeechSynthesisOutputFormat.Audio16Khz128KBitRateMonoMp3
        )
        voice = options.get("voice", "zh-CN-XiaoxiaoNeural")
        # 只允许 azureVoices 中定义的合法语音名称
        VALID_VOICES = {
            "zh-CN-XiaoxiaoNeural","zh-CN-YunxiNeural","zh-CN-YunjianNeural",
            "zh-CN-XiaoyiNeural","zh-CN-YunyangNeural","zh-CN-XiaochenNeural",
            "zh-CN-XiaohanNeural","zh-CN-XiaomengNeural","zh-CN-XiaomoNeural",
            "zh-CN-XiaoqiuNeural","zh-CN-XiaorouNeural","zh-CN-XiaoruiNeural",
            "zh-CN-XiaoshuangNeural","zh-CN-XiaoyanNeural","zh-CN-XiaoyuNeural",
            "zh-CN-XiaozhenNeural","zh-CN-YunfanNeural","zh-CN-YunfengNeural",
            "zh-CN-YunhaoNeural","zh-CN-YunjieNeural","zh-CN-YunxiaNeural",
            "zh-CN-YunxiaoNeural","zh-CN-YunyeNeural","zh-CN-YunyiNeural",
            "zh-CN-YunzeNeural","zh-CN-XiaoxiaoDialectsNeural",
            "zh-CN-sichuan-YunxiNeural","zh-CN-shandong-YunxiangNeural",
            "zh-CN-henan-YundengNeural","zh-CN-liaoning-XiaobeiNeural",
            "zh-CN-liaoning-YunbiaoNeural","zh-CN-shaanxi-XiaoniNeural",
            "zh-CN-guangxi-YunqiNeural","zh-TW-HsiaoChenNeural",
            "zh-TW-HsiaoYuNeural","zh-TW-YunJheNeural","zh-HK-HiuMaanNeural",
            "zh-HK-HiuGaaiNeural","zh-HK-WanLungNeural",
            "en-US-AriaNeural","en-US-GuyNeural","en-US-JennyNeural",
            "ja-JP-NanamiNeural","ja-JP-KeitaNeural",
            "ko-KR-SunHiNeural","ko-KR-InJoonNeural",
            "de-DE-KatjaNeural","de-DE-ConradNeural",
            "fr-FR-DeniseNeural","fr-FR-HenriNeural",
            "es-ES-ElviraNeural","es-ES-AlvaroNeural",
        }
        if voice not in VALID_VOICES:
            voice = "zh-CN-XiaoxiaoNeural"
        speech_config.speech_synthesis_voice_name = voice
        
        # 构建 SSML
        # TTS 过滤括号内的动作/情绪描述
        text = re.sub(r"（[^）]*）", "", text)
        escaped_text = xml.sax.saxutils.escape(text)
        rate = float(options.get("rate", 1.0))
        pitch = options.get("pitch", "default")
        style = options.get("style", "")
        role = options.get("role", "")
        locale = options.get("locale", options.get("language", "zh-CN"))

        # 白名单校验
        VALID_LOCALES = {"zh-CN","zh-CN-sichuan","zh-CN-shandong","zh-CN-henan","zh-CN-liaoning","zh-CN-shaanxi","zh-CN-guangxi","zh-TW","zh-HK","en-US","ja-JP","ko-KR","de-DE","fr-FR","es-ES"}
        VALID_PITCHES = {"default","x-low","low","medium","high","x-high"}
        if locale not in VALID_LOCALES:
            locale = "zh-CN"
        if pitch not in VALID_PITCHES:
            pitch = "default"
        if style and not style.isalnum():
            style = ""
        if role and not role.replace("-","").replace("_","").isalnum():
            role = ""
        rate = max(0.5, min(3.0, rate))
        ssml_parts = ['<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="http://www.w3.org/2001/mstts" xml:lang="{}">'.format(locale)]
        ssml_parts.append('<voice name="{}">'.format(voice))
        
        # 语速和语调
        prosody_attrs = []
        if rate != 1.0:
            prosody_attrs.append('rate="{:.1f}"'.format(rate))
        if pitch != "default":
            prosody_attrs.append('pitch="{}"'.format(pitch))
        
        if prosody_attrs:
            ssml_parts.append('<prosody {}>'.format(' '.join(prosody_attrs)))
        
        # 风格和角色
        if style and role:
            ssml_parts.append('<mstts:express-as style="{}" role="{}">'.format(style, role))
            ssml_parts.append(escaped_text)
            ssml_parts.append('</mstts:express-as>')
        elif style:
            ssml_parts.append('<mstts:express-as style="{}">'.format(style))
            ssml_parts.append(escaped_text)
            ssml_parts.append('</mstts:express-as>')
        elif role:
            ssml_parts.append('<mstts:express-as role="{}">'.format(role))
            ssml_parts.append(escaped_text)
            ssml_parts.append('</mstts:express-as>')
        else:
            ssml_parts.append(escaped_text)
        
        # 关闭标签
        if prosody_attrs:
            ssml_parts.append('</prosody>')
        ssml_parts.append('</voice>')
        ssml_parts.append('</speak>')
        
        ssml = ''.join(ssml_parts)
        
        # 确保输出目录存在
        output_dir = os.path.dirname(filename)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        
        audio_config = AudioConfig(filename=filename)
        synthesizer = SpeechSynthesizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )
        result = synthesizer.speak_ssml_async(ssml).get()
        if result.reason == ResultReason.SynthesizingAudioCompleted:
            _cleanup_old_audio_files()
            return True
        else:
            # 尝试获取更多错误信息
            return False
    except Exception as e:
        logging.error(f"TTS 合成失败: {type(e).__name__}: {e} | text_len={len(text)} voice={voice} locale={locale}")
        return False


# ---------------------------------------------------------------------------
# 路由与业务逻辑
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        if current_user.is_authenticated:
            return redirect(url_for("chat"))
        return render_template("register.html")
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    invite_code = (request.form.get("invite_code") or "").strip()
    # 验证码校验
    if invite_code != "8237":
        return render_template("register.html", error="验证码错误")
    # 用户名校验
    if not username or len(username) < 2 or len(username) > 20:
        return render_template("register.html", error="用户名需要 2-20 个字符")
    if not password or len(password) < 4:
        return render_template("register.html", error="密码至少需要 4 个字符")
    if get_user_by_username(username):
        return render_template("register.html", error="用户名已存在")
    # 写入数据库
    with _db_lock:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO users (username, password, has_tts) VALUES (?, ?, 0)",
                (username, generate_password_hash(password)),
            )
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            logging.error(f"注册失败: {e}")
            return render_template("register.html", error="注册失败，请稍后重试")
        finally:
            conn.close()
    # 自动登录
    row = get_user_by_username(username)
    if row:
        user = User(row[0], row[1])
        login_user(user)
    return redirect(url_for("chat"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if current_user.is_authenticated:
            return redirect(url_for("chat"))
        return render_template("login.html")
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    if not username:
        return render_template("login.html", error="请输入用户名")
    row = get_user_by_username(username)
    if not row or not check_password_hash(row[2], password):
        return render_template("login.html", error="用户名或密码错误")
    user = User(row[0], row[1])
    login_user(user)
    return redirect(url_for("chat"))


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/chat")
@login_required
def chat():
    if current_user.username == "Dawnlarism":
        return redirect(url_for("admin_panel"))
    roles = load_roles(current_user.id)
    role_name = request.args.get("role", "").strip()
    if role_name not in roles:
        role_name = ""
    data = load_history(current_user.id, role_name)
    return render_template(
        "chat.html",
        roles=roles,
        current_role=data["role"],
        current_ai=data["ai"],
        history=data["history"],
        has_tts=user_has_tts(current_user.id),
    )



# ---------------------------------------------------------------------------
# 管理员面板
# ---------------------------------------------------------------------------

@app.route("/admin")
@login_required
def admin_panel():
    if current_user.username != "Dawnlarism":
        return redirect(url_for("chat"))
    with _db_lock:
        conn = get_connection()
        try:
            rows = conn.execute("""
                SELECT u.id, u.username, u.has_tts,
                       (SELECT COUNT(*) FROM roles WHERE roles.user_id = u.id),
                       (SELECT COUNT(*) FROM history WHERE history.user_id = u.id)
                FROM users u ORDER BY u.id
            """).fetchall()
            users = [{"id": r[0], "username": r[1], "has_tts": r[2],
                      "roles": r[3], "history": r[4]} for r in rows]
        finally:
            conn.close()
    return render_template("admin.html", users=users)




@app.route("/admin/toggle_tts/<int:user_id>", methods=["POST"])
@login_required
def admin_toggle_tts(user_id):
    if current_user.username != "Dawnlarism":
        return redirect(url_for("chat"))
    with _db_lock:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT username, has_tts FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if row is None:
                return redirect(url_for("admin_panel"))
            new_val = 1 if row[1] == 0 else 0
            conn.execute("UPDATE users SET has_tts = ? WHERE id = ?", (new_val, user_id))
            conn.commit()
        finally:
            conn.close()
    return redirect(url_for("admin_panel"))

@app.route("/admin/delete/<int:user_id>", methods=["POST"])
@login_required
def admin_delete_user(user_id):
    if current_user.username != "Dawnlarism":
        return redirect(url_for("chat"))
    with _db_lock:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT username FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if row is None:
                return redirect(url_for("admin_panel"))
            username = row[0]
            if username in ("Dawnlarism", "DAWN"):
                return redirect(url_for("admin_panel"))
            conn.execute("DELETE FROM roles WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM history WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
        finally:
            conn.close()
    return redirect(url_for("admin_panel"))

@app.route("/add_role", methods=["POST"])
@login_required
def add_role():
    data = request.get_json(silent=True) or request.form
    role_name = (data.get("role_name") or "").strip()
    prompt = (data.get("prompt") or "").strip()
    if not role_name:
        return {"ok": False, "success": False, "error": "角色名不能为空"}, 400
    if len(role_name) > 50:
        return {"ok": False, "success": False, "error": "角色名不能超过50个字符"}, 400
    if len(prompt) > 5000:
        return {"ok": False, "success": False, "error": "提示词不能超过5000个字符"}, 400
    try:
        save_role(current_user.id, role_name, prompt)
    except Exception as e:
        logging.error(f"添加角色失败: {e}")
        return {"ok": False, "success": False, "error": "服务器内部错误，请稍后重试"}, 500
    return {"ok": True, "success": True}


@app.route("/get_roles", methods=["GET"])
@login_required
def get_roles():
    roles = load_roles(current_user.id)
    return {"roles": roles}


@app.route("/edit_role", methods=["POST"])
@login_required
def edit_role():
    data = request.get_json(silent=True) or request.form
    role_name = (data.get("role_name") or "").strip()
    new_prompt = (data.get("new_prompt") or "").strip()
    if not role_name:
        return {"ok": False, "success": False, "error": "角色名不能为空"}, 400
    if len(new_prompt) > 5000:
        return {"ok": False, "success": False, "error": "提示词不能超过5000个字符"}, 400
    try:
        save_role(current_user.id, role_name, new_prompt)
    except Exception as e:
        logging.error(f"编辑角色失败: {e}")
        return {"ok": False, "success": False, "error": "服务器内部错误，请稍后重试"}, 500
    return {"ok": True, "success": True}


@app.route("/delete_role", methods=["POST"])
@login_required
def delete_role():
    data = request.get_json(silent=True) or request.form
    role_name = (data.get("role_name") or "").strip()
    if not role_name:
        return {"ok": False, "success": False, "error": "角色名不能为空"}, 400
    user_id = current_user.id
    with _db_lock:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM roles WHERE user_id = ? AND role_name = ?",
                (user_id, role_name),
            )
            rows_deleted = cursor.rowcount
            conn.execute(
                "DELETE FROM history WHERE user_id = ? AND role_name = ?",
                (user_id, role_name),
            )
            # 清理空角色名的历史记录（"无"角色对话）
            conn.execute(
                "DELETE FROM history WHERE user_id = ? AND role_name = ''",
                (user_id,),
            )
            conn.commit()
            if rows_deleted == 0:
                return {"ok": True, "success": True, "msg": "角色不存在或已被删除"}
            return {"ok": True, "success": True, "msg": "角色删除成功"}
        except sqlite3.Error as e:
            conn.rollback()
            logging.error(f"数据库错误: {e}")
            return {"ok": False, "success": False, "error": "服务器内部错误，请稍后重试"}, 500
        except Exception as e:
            conn.rollback()
            logging.error(f"服务器错误: {e}")
            return {"ok": False, "success": False, "error": "服务器内部错误，请稍后重试"}, 500
        finally:
            conn.close()


@app.route("/audio/<filename>")
def get_audio(filename):
    """提供生成的音频文件"""
    static_dir = os.path.join(BASE_DIR, "static")
    return send_from_directory(static_dir, filename)



# ---------------------------------------------------------------------------
# SocketIO：实时对话
# ---------------------------------------------------------------------------

@socketio.on("send_message")
def handle_send_message(data):
    """处理用户发送的消息：调用 AI、更新历史、生成 TTS，并返回回复与音频 URL。"""
    user_id = getattr(current_user, "id", None) if current_user.is_authenticated else None
    if not user_id:
        emit("receive_message", {"response": "请先登录。", "audio_url": None})
        return
    prompt = (data.get("message") or data.get("prompt") or "").strip()
    if not prompt:
        emit("receive_message", {"response": "请输入内容。", "audio_url": None})
        return
    if len(prompt) > 10000:
        emit("receive_message", {"response": "消息过长，请限制在 10000 字符以内。", "audio_url": None})
        return
    # 获取当前角色和AI（前端传递）
    current_role = (data.get("role") or "").strip()
    current_ai = (data.get("ai") or "deepseek").strip().lower()
    if current_ai != "deepseek":
        current_ai = "deepseek"
    # 加载当前角色的历史
    hist_data = load_history(user_id, current_role)
    history = list(hist_data["history"])
    # 如果历史中有保存的AI设置且前端未指定，则使用历史中的AI
    if not data.get("ai") and hist_data["ai"]:
        current_ai = hist_data["ai"]
    roles = load_roles(user_id)
    # 加载记忆并插入
    user_memory, role_memory = load_memories(user_id, current_role)
    # 角色记忆插在角色设定之后
    if role_memory:
        history.insert(1, {"role": "system", "content": "[角色记忆] " + role_memory})
    # 用户记忆插在最后
    if user_memory:
        history.insert(1 if not role_memory else 2, {"role": "system", "content": "[用户信息] " + user_memory})

    # 管理系统消息：确保系统消息与当前角色匹配
    system_message_index = None
    for i, msg in enumerate(history):
        if (msg.get("role") or "").strip().lower() == "system":
            system_message_index = i
            break
    
    if current_role and roles.get(current_role):
        system_content = roles[current_role]
        if system_message_index is not None:
            # 更新现有系统消息内容
            if history[system_message_index].get("content") != system_content:
                history[system_message_index]["content"] = system_content
        else:
            # 插入新的系统消息
            history.insert(0, {"role": "system", "content": system_content})
    else:
        # 当前角色为空或无prompt，移除系统消息
        if system_message_index is not None:
            history.pop(system_message_index)
    # 调用 AI（传入当前选择的 current_ai）
    response = get_ai_response(prompt, history, provider=current_ai)
    # 更新历史并持久化
    history.append({"role": "user", "content": prompt})
    history.append({"role": "assistant", "content": response})
    save_history(user_id, current_role, current_ai, history)
    # 生成 TTS 音频文件（仅 DAWN 可用）
    audio_url = None
    tts_options = data.get("tts_options", {})
    if not user_has_tts(user_id):
        tts_options["enable"] = False
    if tts_options.get("enable", True):
        unique = uuid.uuid4().hex[:12]
        audio_filename = os.path.join(BASE_DIR, "static", f"audio_{unique}.mp3")
        if speak_text_to_file(response, audio_filename, tts_options):
            audio_url = url_for("get_audio", filename=f"audio_{unique}.mp3")
    emit("receive_message", {"response": response, "audio_url": audio_url})

    # 后台提取记忆（不阻塞）
    try:
        try_extract_memories(user_id, current_role, prompt, response)
    except Exception as e:
        logging.warning(f"记忆提取调度失败: {e}")


@socketio.on("switch_role")
def handle_switch_role(data):
    """处理角色切换事件：加载新角色的历史。"""
    user_id = getattr(current_user, "id", None) if current_user.is_authenticated else None
    if not user_id:
        emit("switch_role_error", {"error": "请先登录。"})
        return
    new_role = (data.get("role") or "").strip()
    
    # 加载新角色的历史
    hist_data = load_history(user_id, new_role)
    
    emit("update_history", {
        "role": hist_data["role"],
        "ai": hist_data["ai"],
        "history": hist_data["history"]
    })


# ---------------------------------------------------------------------------
# 应用启动时初始化数据库
# ---------------------------------------------------------------------------
init_db()

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    host = "0.0.0.0"
    if debug and host == "0.0.0.0":
        logging.warning("FLASK_DEBUG=1 且 host=0.0.0.0，存在安全风险，已自动改为 127.0.0.1")
        host = "127.0.0.1"
    socketio.run(app, host=host, port=5000, debug=debug)


