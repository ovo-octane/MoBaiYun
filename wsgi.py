# -*- coding: utf-8 -*-
"""Gunicorn 入口：使用 gevent 支持 Socket.IO"""

from gevent import monkey
monkey.patch_all()

from mobaiyun_app import app, socketio

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000)
