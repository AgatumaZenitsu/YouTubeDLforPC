#!/bin/bash

# Update package lists
apt-get update

# Install FFmpeg and Node.js for yt-dlp JavaScript extraction
apt-get install -y ffmpeg nodejs npm

# Ensure node binary is available for yt-dlp
if [ ! -x "/usr/bin/node" ] && [ -x "/usr/bin/nodejs" ]; then
  ln -sf /usr/bin/nodejs /usr/bin/node
fi

# Install Python dependencies
pip install -r requirements.txt
