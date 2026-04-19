#!/bin/bash
# ARM64ネイティブ用のPython仮想環境セットアップスクリプト
# LightGBMをARM64版でビルドするための環境を構築

set -e

echo "=========================================="
echo "ARM64 Native Python Environment Setup"
echo "=========================================="
echo ""

# 現在のアーキテクチャを確認
ARCH=$(arch)
echo "Current architecture: $ARCH"

if [ "$ARCH" != "arm64" ]; then
    echo "Warning: Current architecture is $ARCH, not arm64."
    echo "Please run this script in an ARM64 terminal."
    echo "You may need to restart your terminal or run: arch -arm64 zsh"
    exit 1
fi

# プロジェクトのルートディレクトリを取得
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$PROJECT_ROOT/venv_arm64"

echo "Project root: $PROJECT_ROOT"
echo "Virtual environment directory: $VENV_DIR"
echo ""

# ARM64版のPython3を検索（Anaconda環境がアクティブでもシステムのPython3を使用）
# 優先順位: /usr/local/bin/python3 > /usr/bin/python3 > which python3
PYTHON3=""
for PYTHON_CANDIDATE in /usr/local/bin/python3 /usr/bin/python3 $(which python3 2>/dev/null); do
    if [ -n "$PYTHON_CANDIDATE" ] && [ -x "$PYTHON_CANDIDATE" ]; then
        PYTHON_ARCH_CANDIDATE=$($PYTHON_CANDIDATE -c "import platform; print(platform.machine())" 2>/dev/null || echo "")
        if [ "$PYTHON_ARCH_CANDIDATE" == "arm64" ]; then
            PYTHON3="$PYTHON_CANDIDATE"
            break
        fi
    fi
done

if [ -z "$PYTHON3" ]; then
    echo "Error: ARM64 native Python3 not found."
    echo "Please install ARM64 native Python3 or use: /usr/local/bin/python3 or /usr/bin/python3"
    exit 1
fi

# Python3のバージョンとアーキテクチャを確認
PYTHON_VERSION=$($PYTHON3 --version)
PYTHON_ARCH=$($PYTHON3 -c "import platform; print(platform.machine())")

echo "Python3 path: $PYTHON3"
echo "Python version: $PYTHON_VERSION"
echo "Python architecture: $PYTHON_ARCH"
echo ""

if [ "$PYTHON_ARCH" != "arm64" ]; then
    echo "Error: Selected Python3 is not ARM64 architecture (current: $PYTHON_ARCH)"
    echo "Please use ARM64 native Python3."
    exit 1
fi

# libompがインストールされているか確認
if ! brew list libomp &>/dev/null; then
    echo "Installing libomp (ARM64)..."
    brew install libomp
else
    echo "libomp (ARM64) is already installed"
fi

# libompのパスを確認
LIBOMP_PATH="/opt/homebrew/opt/libomp/lib/libomp.dylib"
if [ ! -f "$LIBOMP_PATH" ]; then
    echo "Error: libomp.dylib not found at $LIBOMP_PATH"
    exit 1
fi

echo "Found libomp at: $LIBOMP_PATH"
echo ""

# 既存の仮想環境があれば削除
if [ -d "$VENV_DIR" ]; then
    echo "Removing existing virtual environment..."
    rm -rf "$VENV_DIR"
fi

# 仮想環境を作成（明示的にARM64版Python3を使用）
echo "Creating ARM64 virtual environment using: $PYTHON3"
"$PYTHON3" -m venv "$VENV_DIR"

# 仮想環境を有効化
echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# 仮想環境内のPython3とpipを使用
VENV_PYTHON="$VENV_DIR/bin/python3"
VENV_PIP="$VENV_DIR/bin/pip"

# pipをアップグレード
echo "Upgrading pip..."
"$VENV_PIP" install --upgrade pip

# 必要なビルドツールをインストール
echo "Installing build tools..."
"$VENV_PIP" install wheel setuptools cmake

# OpenMP環境変数を設定してLightGBMをビルド
echo ""
echo "Installing dependencies (excluding LightGBM)..."
cd "$PROJECT_ROOT"

# LightGBM以外の依存関係をインストール
"$VENV_PIP" install $(grep -v "^lightgbm" requirements.txt | grep -v "^#" | grep -v "^$")

# LightGBMをARM64版でビルド
echo ""
echo "Building LightGBM for ARM64..."
echo "This may take several minutes..."

# OpenMPのパスを設定
export LDFLAGS="-L/opt/homebrew/opt/libomp/lib"
export CPPFLAGS="-I/opt/homebrew/opt/libomp/include"
export DYLD_LIBRARY_PATH="/opt/homebrew/opt/libomp/lib:$DYLD_LIBRARY_PATH"

# LightGBMをソースからビルド
"$VENV_PIP" install --no-binary lightgbm lightgbm==4.1.0

# インストールを確認
echo ""
echo "Verifying LightGBM installation..."
"$VENV_PYTHON" -c "import lightgbm as lgb; print('LightGBM imported successfully'); print('LightGBM version:', lgb.__version__)"

# アーキテクチャを確認
echo ""
echo "Checking LightGBM library architecture..."
LIGHTGBM_LIB=$("$VENV_PYTHON" -c "import lightgbm; import os; print(os.path.join(os.path.dirname(lightgbm.__file__), 'lib', 'lib_lightgbm.so'))")
if [ -f "$LIGHTGBM_LIB" ]; then
    file "$LIGHTGBM_LIB"
else
    echo "Warning: Could not find LightGBM library file"
fi

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "To activate this environment:"
echo "  source $VENV_DIR/bin/activate"
echo ""
echo "To verify the installation:"
echo "  python3 -c 'import lightgbm as lgb; print(lgb.__version__)'"
echo "  python3 -c 'import platform; print(platform.machine())'"
echo ""
