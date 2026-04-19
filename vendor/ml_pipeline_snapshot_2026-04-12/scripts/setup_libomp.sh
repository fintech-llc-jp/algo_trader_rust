#!/bin/bash
# LightGBM用のlibompライブラリのセットアップスクリプト

set -e

echo "Setting up libomp for LightGBM..."

# libompがインストールされているか確認
if ! brew list libomp &>/dev/null; then
    echo "Installing libomp..."
    brew install libomp
else
    echo "libomp is already installed"
fi

# libompのパスを確認
LIBOMP_PATH="/opt/homebrew/opt/libomp/lib/libomp.dylib"
if [ ! -f "$LIBOMP_PATH" ]; then
    # Intel Macの場合
    LIBOMP_PATH="/usr/local/opt/libomp/lib/libomp.dylib"
fi

if [ ! -f "$LIBOMP_PATH" ]; then
    echo "Error: libomp.dylib not found"
    exit 1
fi

echo "Found libomp at: $LIBOMP_PATH"

# シンボリックリンクの作成（sudoが必要な場合）
TARGET_DIR="/usr/local/opt/libomp/lib"
if [ ! -f "$TARGET_DIR/libomp.dylib" ]; then
    echo "Creating symlink for libomp..."
    sudo mkdir -p "$TARGET_DIR"
    sudo ln -sf "$LIBOMP_PATH" "$TARGET_DIR/libomp.dylib"
    echo "Symlink created: $TARGET_DIR/libomp.dylib -> $LIBOMP_PATH"
else
    echo "Symlink already exists: $TARGET_DIR/libomp.dylib"
fi

echo ""
echo "Setup complete!"
echo ""
echo "If you still get errors, you can also set the environment variable:"
echo "  export DYLD_LIBRARY_PATH=/opt/homebrew/opt/libomp/lib:\$DYLD_LIBRARY_PATH"
echo ""
echo "Or for Anaconda environments:"
echo "  export DYLD_LIBRARY_PATH=/opt/homebrew/opt/libomp/lib:\$DYLD_LIBRARY_PATH"
echo "  source activate your_conda_env  # if using conda"
