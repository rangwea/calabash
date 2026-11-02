"""检查工具源码契约；不导入或执行被检查文件，仅依赖标准库。"""

import argparse
import ast
import re
import tokenize
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from core.tool_api_contracts import api_errors

_PAGE_HELPERS = {
    "component.tool_files.ToolFileInput",
    "component.tool_results.ToolResults",
    "component.tool_results.ToolJobStatus",
    "service.files.tool_outputs.ToolOutputs",
    "service.tools.tool_jobs.ToolJobs",
    "service.tools.tool_jobs.ToolTask",
}


class _ModuleStateCheck(ast.NodeVisitor):
    """Spot known shared page state without importing or running tool code."""

    def __init__(self):
        self.aliases = {}
        self.errors = []

    def visit_Import(self, node):
        for item in node.names:
            self.aliases[item.asname or item.name.split(".")[0]] = item.name if item.asname else item.name.split(".")[0]

    def visit_ImportFrom(self, node):
        for item in node.names:
            self.aliases[item.asname or item.name] = f"{node.module}.{item.name}"

    def _name(self, node):
        if isinstance(node, ast.Name):
            return self.aliases.get(node.id, "")
        if isinstance(node, ast.Attribute):
            parent = self._name(node.value)
            return f"{parent}.{node.attr}" if parent else ""
        return ""

    def visit_Call(self, node):
        name = self._name(node.func)
        if name == 'nicegui.ui.run':
            self.errors.append(f"第 {node.lineno} 行：Calabash 管理运行，不调用 ui.run()")
        if name in _PAGE_HELPERS:
            self.errors.append(f"第 {node.lineno} 行：{name.rsplit('.', 1)[1]} 必须在 main()/UI 回调内创建，不能作为模块共享状态")
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        return

    def visit_AsyncFunctionDef(self, node):
        return

    def visit_Lambda(self, node):
        return

def validate_source(source: str) -> list[str]:
    """返回静态契约错误；通过不代表工具能够运行。"""
    try:
        tree = ast.parse(source)
        compile(tree, "<tool>", "exec")  # 编译但绝不执行；补充 return/await 位置检查。
    except (SyntaxError, ValueError) as exc:
        return [f"Python 语法错误：{exc}"]

    state_check = _ModuleStateCheck()
    state_check.visit(tree)
    errors = state_check.errors + api_errors(tree)
    metadata = {}
    for line in (ast.get_docstring(tree) or "").splitlines():
        key, separator, value = line.strip().partition(":")
        if separator:
            metadata[key.strip().lower()] = value.strip()
    if metadata.get("requires"):
        declaration = metadata["requires"]
        parts = declaration.split(",")
        pattern = r"([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)(?:\s*>=\s*[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6})?"
        seen = set()
        if len(declaration) > 2048 or len(parts) > 16:
            errors.append("metadata requires 超出长度或能力数量限制")
        else:
            for part in parts:
                match = re.fullmatch(pattern, part.strip())
                if match is None or match[1] in seen:
                    errors.append("metadata requires 格式无效或重复；使用 media.ffmpeg 或 media.ffmpeg>=9.0.2，多个能力以英文逗号分隔")
                    break
                seen.add(match[1])
    for key in (
        "project",
        "name",
        "description",
        "creator",
        "created_at",
        "updated_at",
        "tags",
    ):
        if not metadata.get(key):
            errors.append(f"metadata 缺少非空字段：{key}")
    if metadata.get("tags"):
        tags = [
            tag.strip() for tag in re.split(r"[,，]", metadata["tags"]) if tag.strip()
        ]
        if not 2 <= len(tags) <= 5:
            errors.append("metadata tags 必须包含 2–5 个逗号分隔的用途词")

    mains = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "main"
    ]
    if len(mains) != 1:
        errors.append("必须定义且仅定义一个顶层 main 函数")
    elif mains[0].decorator_list:
        errors.append("顶层 main 不得使用装饰器")
    if len(mains) == 1:
        entrypoint = mains[0]
        args = entrypoint.args
        if len(args.posonlyargs) + len(args.args) > len(args.defaults) or any(
            default is None for default in args.kw_defaults
        ):
            errors.append("平台无参调用 main()，入口不得包含必填参数")
        # 嵌套函数和类中的 yield 不会把 main 变成生成器。
        pending = list(entrypoint.body)
        while pending:
            node = pending.pop()
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
            ):
                continue
            if isinstance(node, (ast.Yield, ast.YieldFrom)):
                errors.append("main 不得是生成器；平台不会迭代其返回值")
                break
            pending.extend(ast.iter_child_nodes(node))

    for node in tree.body:
        if isinstance(node, ast.If) and any(isinstance(value, ast.Name) and value.id == '__name__' for value in ast.walk(node.test)):
            errors.append("由 Calabash 调用 main()，不要添加独立运行入口或 ui.run()")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        with tokenize.open(args.file) as stream:
            errors = validate_source(stream.read())
    except (OSError, UnicodeError, SyntaxError) as exc:
        parser.exit(2, f"无法读取工具源码：{exc}\n")
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        return 1
    print("静态检查通过；未执行源码，未验证页面或业务行为。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
