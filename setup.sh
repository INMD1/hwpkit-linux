#!/usr/bin/env bash
set -euo pipefail
package_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
package_version="$(cat "$package_dir/VERSION")"
runtime_dir="${HWPKIT_LINUX_VENV:-${XDG_DATA_HOME:-$HOME/.local/share}/hwpkit-linux/venv-$package_version}"
python3 -m venv "$runtime_dir"
"$runtime_dir/bin/python" -m pip install --disable-pip-version-check -r "$package_dir/requirements.txt"
echo "PDF 비교 환경 설치 완료: $runtime_dir"
echo "실행: $package_dir/bin/hwpkit-linux doctor"
