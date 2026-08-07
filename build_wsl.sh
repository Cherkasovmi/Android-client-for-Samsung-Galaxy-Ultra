#!/usr/bin/env bash
# Локальная сборка APK через WSL2 (Ubuntu)
# Запуск из папки client_android внутри WSL:
#   wsl bash client_android/build_wsl.sh
#
# Предварительно в WSL:
#   sudo apt update && sudo apt install -y git zip unzip openjdk-17-jdk autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev
#   pip install buildozer cython

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Building APK in $(pwd) ==="
buildozer -v android debug

echo "=== APK(s) created: ==="
ls -la bin/*.apk 2>/dev/null || echo "No APK found"