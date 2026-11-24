#!/usr/bin/env bash
# Set up the clipping kit: a Python venv with pinned packages, plus the three models.
#   bash scripts/setup.sh            # installs into $CLIPKIT_HOME (default ~/.cache/clipkit)
#   CLIPKIT_HOME=/data/clipkit bash scripts/setup.sh
# Needs: python3 (3.10+), ffmpeg + ffprobe on PATH, internet to pypi.org and github.com.
# Safe to re-run: finished steps are skipped. Nothing is written inside the kit folder.
set -euo pipefail

HOME_DIR="${CLIPKIT_HOME:-$HOME/.cache/clipkit}"
VENV="$HOME_DIR/venv"
MODELS="$HOME_DIR/models"
PY="${PYTHON:-python3}"

PARAKEET_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2"
SILERO_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
YUNET_URL="https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"

say() { printf '\n== %s\n' "$*"; }

say "checking tools"
for t in ffmpeg ffprobe "$PY" curl tar; do
  command -v "$t" >/dev/null || { echo "missing: $t (install it first, e.g. apt-get install -y ffmpeg)"; exit 1; }
done
ffmpeg -hide_banner -filters 2>/dev/null | grep ' ebur128 ' >/dev/null || { echo "this ffmpeg has no ebur128 filter"; exit 1; }
ffmpeg -hide_banner -encoders 2>/dev/null | grep libx264 >/dev/null || { echo "this ffmpeg has no libx264 encoder"; exit 1; }
"$PY" -c 'import sys; assert sys.version_info >= (3, 10), sys.version' || { echo "need Python 3.10 or newer"; exit 1; }

say "python venv at $VENV"
mkdir -p "$HOME_DIR" "$MODELS"
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet \
  numpy==2.5.3 scipy==1.18.1 soundfile==0.14.0 \
  sherpa-onnx==2.0.1 onnxruntime==1.29.0 \
  opencv-python-headless==5.0.0.93 pillow==12.3.0
"$VENV/bin/python" -c 'import numpy, scipy, soundfile, sherpa_onnx, onnxruntime, cv2, PIL; print("packages OK")'

fetch() {  # url dest
  local tmp="$2.part"
  curl -fL --retry 3 --retry-delay 2 -o "$tmp" "$1"
  mv "$tmp" "$2"
}

say "models in $MODELS"
P="$MODELS/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
if [ ! -f "$P/tokens.txt" ]; then
  fetch "$PARAKEET_URL" "$MODELS/parakeet.tar.bz2"
  tar -xjf "$MODELS/parakeet.tar.bz2" -C "$MODELS"
  rm -f "$MODELS/parakeet.tar.bz2"
fi
for f in encoder.int8.onnx decoder.int8.onnx joiner.int8.onnx tokens.txt; do
  [ -s "$P/$f" ] || { echo "parakeet model is missing $f"; exit 1; }
done
[ -s "$MODELS/silero_vad.onnx" ] || fetch "$SILERO_URL" "$MODELS/silero_vad.onnx"
[ -s "$MODELS/yunet.onnx" ] || fetch "$YUNET_URL" "$MODELS/yunet.onnx"
# a git-LFS pointer instead of the model is a few hundred bytes: catch that here
[ "$(wc -c < "$MODELS/yunet.onnx")" -gt 100000 ] || { echo "yunet.onnx looks wrong (too small)"; rm -f "$MODELS/yunet.onnx"; exit 1; }

"$VENV/bin/python" - "$MODELS" <<'EOF'
import sys, cv2, onnxruntime as ort
m = sys.argv[1]
cv2.FaceDetectorYN.create(f'{m}/yunet.onnx', '', (320, 320))
ort.InferenceSession(f'{m}/silero_vad.onnx', providers=['CPUExecutionProvider'])
print('models load OK')
EOF

say "done"
echo "venv:   $VENV"
echo "models: $MODELS"
echo "The scripts find both by themselves (or set CLIPKIT_PY / CLIPKIT_MODELS)."
echo "Caption font: pass --font /path/to/a-bold-sans.ttf or set CLIPKIT_FONT (no font is included; see README)."
