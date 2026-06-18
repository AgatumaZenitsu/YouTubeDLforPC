#!/bin/bash

# Render の Python Web Service では apt-get は使えない
# FFmpeg は標準で入っているのでインストール不要

# Python 依存をインストール
pip install --upgrade pip
pip install -r requirements.txt
