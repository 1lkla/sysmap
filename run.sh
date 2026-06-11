#!/usr/bin/env bash
# 便捷入口。等价于直接调 sysmap_local.py。
#   ./run.sh build https://your-app/dashboard --max 60
#   ./run.sh query "哪些路由调用了文件处理 API?" --synthesize
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$DIR/sysmap_local.py" "$@"
