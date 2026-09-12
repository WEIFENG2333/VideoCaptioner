"""UI 样式契约：防止“组件定义了 syncStyle 但构造时没应用样式”。

历史 bug：批量处理页 TaskRow 定义了 syncStyle（内含 setStyleSheet）却没在
__init__ 调用，行内 QLabel 落到 Qt 默认黑字（深色主题下不可读）。截图回归
只能逐页发现，这里用 AST 做全量静态检查。

规则：类的 syncStyle 自身包含 setStyleSheet（说明该类对自己的样式负责）时，
__init__ 必须能（沿 self.xxx() 调用链传递地）到达一次 setStyleSheet 或
syncStyle 调用；没有 __init__ 的子类视为父类构造负责。

确认过“由外部在构造后统一调用 syncStyle”的类进白名单并注明原因。
"""

import ast
from pathlib import Path

UI_ROOT = Path(__file__).resolve().parents[2] / "videocaptioner" / "ui"

# 构造后由持有方立即调用 syncStyle 的类（运行时已逐一核实有样式）。
EXEMPT: dict[str, set[str]] = {}


def _method_calls(func: ast.FunctionDef) -> set[str]:
    """func 体内 self.xxx(...) 形式的方法调用名集合。"""
    calls = set()
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
        ):
            calls.add(node.func.attr)
    return calls


def _applies_style(func: ast.FunctionDef) -> bool:
    src = ast.dump(func)
    return "setStyleSheet" in src or "syncStyle" in src


def _class_violations(tree: ast.Module) -> list[str]:
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        methods = {
            item.name: item for item in node.body if isinstance(item, ast.FunctionDef)
        }
        sync = methods.get("syncStyle")
        init = methods.get("__init__")
        if sync is None or init is None:
            continue
        if "setStyleSheet" not in ast.dump(sync):
            continue  # syncStyle 只转发子控件，无自我样式职责
        # 从 __init__ 沿 self 方法调用做可达性搜索
        seen, queue = set(), ["__init__"]
        reached_style = False
        while queue:
            name = queue.pop()
            if name in seen or name not in methods:
                continue
            seen.add(name)
            if _applies_style(methods[name]):
                reached_style = True
                break
            queue.extend(_method_calls(methods[name]))
        if not reached_style:
            violations.append(node.name)
    return violations


def test_widgets_apply_styles_on_construction():
    assert UI_ROOT.exists()
    all_violations: dict[str, list[str]] = {}
    for path in sorted(UI_ROOT.rglob("*.py")):
        relative = str(path.relative_to(UI_ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        violations = [
            name
            for name in _class_violations(tree)
            if name not in EXEMPT.get(relative, set())
        ]
        if violations:
            all_violations[relative] = violations
    assert not all_violations, (
        "以下类定义了带 setStyleSheet 的 syncStyle，但 __init__ 未应用样式"
        "（QLabel 会落到默认黑字）：\n"
        + "\n".join(f"  {file}: {names}" for file, names in all_violations.items())
    )
