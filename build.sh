#!/bin/bash

# Update package lists
apt-get update

# Install FFmpeg
apt-get install -y ffmpeg

# Install Python dependencies
pip install -r requirements.txt
