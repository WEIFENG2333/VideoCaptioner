#!/usr/bin/env bash
# 编译 macsysaudio（ScreenCaptureKit 系统声音捕获 helper）到 resource/bin/macsysaudio。
# 仅 macOS（需 swiftc + ScreenCaptureKit，macOS 13+ SDK）。出 arm64 + x86_64 universal 二进制，
# 一份同时覆盖 Apple Silicon 与 Intel；产物连同源码一起入库（见 .gitignore 放行）。
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
out="$repo/resource/bin/macsysaudio"
mkdir -p "$repo/resource/bin"

frameworks=(-framework ScreenCaptureKit -framework AVFoundation -framework CoreMedia -framework Foundation)
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# 逐架构编译（min target macOS 13 = ScreenCaptureKit 起始版本），再 lipo 合并成 universal。
# 某架构缺 SDK slice 时降级跳过（至少出当前架构），不让整体失败。
slices=()
for arch in arm64 x86_64; do
  if swiftc -O -target "${arch}-apple-macos13.0" "${frameworks[@]}" \
      -o "$tmp/macsysaudio.$arch" "$here/main.swift" 2>"$tmp/err.$arch"; then
    slices+=("$tmp/macsysaudio.$arch")
  else
    echo "WARNING: $arch 构建失败（缺对应 SDK slice?），跳过：" >&2
    sed 's/^/  /' "$tmp/err.$arch" >&2
  fi
done

if [ ${#slices[@]} -eq 0 ]; then
  echo "ERROR: arm64 与 x86_64 均构建失败" >&2
  exit 1
fi

lipo -create "${slices[@]}" -output "$out"
echo "built: $out ($(lipo -archs "$out"))"
