#!/usr/bin/env python3
"""把 docs/dev 设计稿 HTML 里的每个 .client 状态截成基准图。

用系统 Chrome（playwright channel=chrome）逐元素截图，输出：

    <out>/<state-id>.png          整个 1440x900 client（含标题栏/侧边栏）
    <out>/<state-id>-split.png    仅工作区（.split / .work 元素本身），
                                  与应用页面 widget 截图同尺寸，可直接对比

状态 id 取自 .client 之前最近的 .state-label / .version-title 的 id；
没有 id 时按序号 s1、s2... 命名。

用法：
    .venv/bin/python scripts/design_reference_shots.py \
        docs/dev/design-transcription.html /tmp/vc-design-shots
    .venv/bin/python scripts/design_reference_shots.py \
        docs/dev/design-subtitle.html /tmp/vc-sub-design-shots
    # 第三个参数可覆盖工作区选择器（如批量处理设计稿整个 .app 区域）：
    .venv/bin/python scripts/design_reference_shots.py \
        docs/dev/design-batch.html /tmp/vc-batch-design .app
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

CONTENT_SELECTOR = ".split, .work"


def main() -> int:
    if len(sys.argv) not in (3, 4):
        raise SystemExit(__doc__)
    html_path = Path(sys.argv[1]).resolve()
    out_dir = Path(sys.argv[2])
    content_selector = sys.argv[3] if len(sys.argv) == 4 else CONTENT_SELECTOR
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1560, "height": 1200})
        page.goto(html_path.as_uri())
        page.wait_for_timeout(600)  # 等图标 SVG 加载

        clients = page.query_selector_all(".client")
        labels = page.query_selector_all(".state-label, .version-title")
        for index, client in enumerate(clients):
            state_id = None
            if index < len(labels):
                state_id = labels[index].get_attribute("id")
                if not state_id:
                    # 从标题文本提取状态字母，如“状态 C：处理中” -> c
                    text = labels[index].inner_text()
                    match = re.search(r"状态\s*([A-Z])", text)
                    if match:
                        state_id = f"v1{match.group(1).lower()}"
            state_id = state_id or f"s{index + 1}"

            path = out_dir / f"{state_id}.png"
            client.screenshot(path=str(path))
            print(f"shot={path}")

            content = client.query_selector(content_selector)
            if content is not None:
                split_path = out_dir / f"{state_id}-split.png"
                content.screenshot(path=str(split_path))
                print(f"split={split_path}")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
