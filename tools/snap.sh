#!/bin/bash
# snap.sh <name>: one 4K frame from the BRIO into cam/<name>.jpg (the camera's own JPEG, no re-encode, after 4 s of focus settling) plus a 1920-wide copy
S=$(dirname "$0"); timeout -s KILL 30 ffmpeg -loglevel error -y -f v4l2 -input_format mjpeg -video_size 3840x2160 -i /dev/video0 -ss 4 -frames:v 1 -c:v copy -f image2 "$S/$1.jpg" && ffmpeg -loglevel error -y -i "$S/$1.jpg" -vf "scale=1920:-1" -q:v 2 "$S/$1-small.jpg"
