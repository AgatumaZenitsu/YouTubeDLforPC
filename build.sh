#!/bin/bash

# Update package lists
apt-get update

# Install FFmpeg and Node.js for yt-dlp JavaScript extraction
apt-get install -y ffmpeg nodejs

# Install Python dependencies
pip install -r requirements.txt
