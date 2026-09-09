# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from PyInstaller.utils.hooks import collect_all

# 获取当前工作目录作为项目根目录
project_root = os.path.dirname(os.path.abspath(__file__))

# 数据文件和隐藏导入
datas = []
binaries = []
hiddenimports = []

# 添加模板文件夹（包含所有文件）
templates_dir = os.path.join(project_root, 'templates')
if os.path.exists(templates_dir):
    for root, dirs, files in os.walk(templates_dir):
        for file in files:
            src = os.path.join(root, file)
            # 计算相对于templates目录的相对路径
            rel_path = os.path.relpath(root, templates_dir)
            if rel_path == '.':
                dst = 'templates'
            else:
                dst = os.path.join('templates', rel_path)
            datas.append((src, dst))

# 添加静态文件夹（包含所有文件）
static_dir = os.path.join(project_root, 'static')
if os.path.exists(static_dir):
    for root, dirs, files in os.walk(static_dir):
        for file in files:
            src = os.path.join(root, file)
            # 计算相对于static目录的相对路径
            rel_path = os.path.relpath(root, static_dir)
            if rel_path == '.':
                dst = 'static'
            else:
                dst = os.path.join('static', rel_path)
            datas.append((src, dst))

# 添加数据库文件
db_file = os.path.join(project_root, 'users.db')
if os.path.exists(db_file):
    datas.append((db_file, '.'))

# 添加.env文件（如果存在）
env_file = os.path.join(project_root, '.env')
if os.path.exists(env_file):
    datas.append((env_file, '.'))

# 基础隐藏导入
hiddenimports = [
    'flask',
    'flask_socketio',
    'flask_login',
    'engineio.async_drivers.threading',
    'jinja2',
    'jinja2.ext',
    'werkzeug.security',
    'werkzeug.middleware.proxy_fix',
    'sqlite3',
    'xml.sax.saxutils',
    'uuid',
    'threading',
    'glob',
    'time',
    'openai',
    'dotenv',
]

# 收集 Azure SDK 依赖
try:
    data, bin, hidden = collect_all('azure.cognitiveservices.speech')
    datas.extend(data)
    binaries.extend(bin)
    hiddenimports.extend(hidden)
except Exception as e:
    print(f"Warning: Failed to collect azure.cognitiveservices.speech: {e}")

a = Analysis(
    ['mobaiyun_app.py'],
    pathex=[project_root],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='mobaiyun_app',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # 显示控制台以便调试
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    onefile=False,  # 单文件夹模式
)

# 创建单文件夹分发
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='mobaiyun_app',
)
