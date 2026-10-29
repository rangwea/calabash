#!/usr/bin/env python3
"""Calabash local tool CLI.

Formal tool commands operate directly on ~/.calabash/tools. Preview commands
still use the running local NiceGUI server because they need a browser URL.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

SCRIPT_PATH = Path(__file__).resolve()
SKILL_ROOT = SCRIPT_PATH.parent.parent


class ApiError(Exception):
    def __init__(self, status_code: int, data: Optional[dict], message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.data = data or {}


def app_dir() -> Path:
    return Path(os.environ.get("CALABASH_HOME", Path.home() / ".calabash")).expanduser()


def tools_dir() -> Path:
    path = app_dir() / "tools"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = app_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_name(value: str) -> str:
    name = re.sub(r"[^a-z0-9_-]", "-", value.strip().lower())
    name = re.sub(r"-+", "-", name).strip("-")
    if not name:
        raise ValueError("名称不能为空")
    return name


def tool_path(project: str, name: str) -> Path:
    project_name = normalize_name(project)
    raw_name = name[:-3] if name.endswith(".py") else name
    tool_name = normalize_name(raw_name)
    return tools_dir() / project_name / f"{tool_name}.py"


def sidecar_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.calabash.json")


def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def read_content_arg(args) -> str:
    if getattr(args, "file", None):
        return Path(args.file).expanduser().resolve().read_text(encoding="utf-8")
    if getattr(args, "stdin", False):
        return sys.stdin.read()
    raise ValueError("必须指定 --file 或 --stdin")


def parse_metadata(content: str, fallback_name: str) -> dict:
    meta = {
        "title": fallback_name,
        "description": "",
        "creator": "",
        "created_at": "",
        "updated_at": "",
        "tags": "",
    }
    in_header = False
    for raw_line in content.splitlines()[:40]:
        line = raw_line.strip()
        if line in {'"""', "'''"}:
            in_header = not in_header
            continue
        if not in_header or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "name":
            meta["title"] = value
        elif key in meta:
            meta[key] = value
    return meta


def tool_meta(path: Path) -> dict:
    project = path.parent.name
    name = path.stem
    content = read_text(path)
    parsed = parse_metadata(content, name)
    stat = path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
    return {
        "project": project,
        "name": name,
        "title": parsed["title"],
        "description": parsed["description"],
        "creator": parsed["creator"],
        "created_at": parsed["created_at"] or mtime,
        "updated_at": parsed["updated_at"] or mtime,
        "path": str(path),
        "tags": parsed["tags"],
        "revision": sha256_text(content),
    }


def scan_tools(project: str | None = None) -> list[dict]:
    root = tools_dir()
    projects = (
        [normalize_name(project)]
        if project
        else sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("_"))
    )
    rows = []
    for project_name in projects:
        project_dir = root / project_name
        if not project_dir.is_dir():
            continue
        for path in sorted(project_dir.glob("*.py")):
            if path.name != "__init__.py":
                rows.append(tool_meta(path))
    return rows


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    if not rows:
        print("(无数据)")
        return
    widths = [len(item) for item in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(str(cell)))
    header = " | ".join(item.ljust(widths[index]) for index, item in enumerate(headers))
    print(header)
    print("-" * len(header))
    for row in rows:
        print(" | ".join(str(cell).ljust(widths[index]) for index, cell in enumerate(row)))


def normalize_error_payload(data: Optional[dict]) -> dict:
    source = data or {}
    message = source.get("message") or source.get("detail") or source.get("error") or "请求失败"
    return {
        **{k: v for k, v in source.items() if k not in {"success", "message", "detail", "error"}},
        "success": False,
        "code": source.get("code") or "request_failed",
        "message": message,
        "next_action": source.get("next_action") or "inspect_error",
    }


def make_request(url: str, method: str = "GET", data: Optional[dict] = None, timeout: int = 30) -> dict:
    headers = {"Content-Type": "application/json"}
    body = json.dumps(data).encode("utf-8") if data is not None else None
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        text = exc.read().decode("utf-8")
        try:
            payload = normalize_error_payload(json.loads(text))
        except json.JSONDecodeError:
            payload = normalize_error_payload({"error": f"HTTP {exc.code}: {text}"})
        raise ApiError(exc.code, payload, payload["message"])
    except URLError as exc:
        raise RuntimeError(f"连接失败: {exc.reason}") from exc


def make_raw_request(url: str, timeout: int = 30) -> tuple[int, str]:
    headers = {"Accept": "text/plain, */*"}
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")
    except URLError as exc:
        return 0, f"连接失败: {exc.reason}"


def build_public_url(server: str, path_or_url: str) -> str:
    if not path_or_url:
        return server.rstrip("/")
    returned = urlsplit(path_or_url)
    if returned.scheme and returned.netloc:
        return path_or_url
    base = urlsplit(server.rstrip("/"))
    base_path = base.path.rstrip("/")
    returned_path = f"/{returned.path.lstrip('/')}"
    final_path = returned_path if not base_path else f"{base_path}{returned_path}"
    return urlunsplit((base.scheme, base.netloc, final_path, returned.query, returned.fragment))


def local_result(success: bool, **data) -> dict:
    return {"success": success, **data}


def cmd_list(args) -> None:
    tools = scan_tools(args.project)
    result = {"tools": tools, "total": len(tools), "tools_dir": str(tools_dir())}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"工具目录: {tools_dir()}")
    print(f"共 {len(tools)} 个工具\n")
    print_table(
        ["项目", "名称", "标题", "描述", "更新时间"],
        [
            [item["project"], item["name"], item["title"][:20], item["description"][:30], item["updated_at"]]
            for item in tools
        ],
    )


def cmd_projects(args) -> None:
    projects = sorted({item["project"] for item in scan_tools()})
    result = {"projects": projects, "total": len(projects), "tools_dir": str(tools_dir())}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"共 {len(projects)} 个项目:\n")
    for project in projects:
        print(f"  - {project}")


def cmd_get(args) -> None:
    path = tool_path(args.project, args.name)
    if not path.is_file():
        raise FileNotFoundError(f"工具不存在: {args.project}/{args.name}")
    meta = tool_meta(path)
    content = read_text(path)
    result = {"meta": meta, "content": content}
    if args.output:
        output = Path(args.output).expanduser().resolve()
        write_text(output, content)
        sidecar_path(output).write_text(
            json.dumps(
                {"project": meta["project"], "name": meta["name"], "revision": meta["revision"], "source": str(path)},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        result = local_result(True, output=str(output), sidecar=str(sidecar_path(output)), revision=meta["revision"])
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.output:
        print(f"✓ 已写入: {result['output']}")
        print(f"  revision: {result['revision']}")
        return
    print(f"项目: {meta['project']}")
    print(f"名称: {meta['name']}")
    print(f"标题: {meta['title']}")
    print(f"描述: {meta['description']}")
    print(f"标签: {meta['tags']}")
    print(f"Revision: {meta['revision']}")
    print(f"路径: {meta['path']}")
    print("\n" + "=" * 60)
    print(content)


def generate_template(args) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    title = args.title or args.name.replace("_", " ").replace("-", " ").title()
    description = args.description or f"{title} tool"
    creator = args.creator or "tool-cli"
    tags = args.tags or "local"
    return f'''"""
project: {args.project}
name: {title}
description: {description}
creator: {creator}
created_at: {today}
updated_at: {today}
tags: {tags}
"""

from nicegui import ui


def main():
    ui.label("{title}").classes("text-lg font-medium")


if __name__ in {{"__main__", "__mp_main__"}}:
    main()
    ui.run(title="{title}", port=8080, show=True)
'''


def cmd_create(args) -> None:
    path = tool_path(args.project, args.name)
    if path.exists():
        raise FileExistsError(f"工具已存在: {path}")
    content = read_content_arg(args) if args.file or args.stdin else generate_template(args)
    write_text(path, content)
    result = local_result(True, project=path.parent.name, name=path.stem, path=str(path))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"✓ 本地创建成功: {path.parent.name}/{path.stem}")
    print(f"  路径: {path}")


def next_version(path: Path) -> str:
    sidecar = sidecar_path(path)
    if not sidecar.is_file():
        return "v1"
    try:
        current = json.loads(sidecar.read_text(encoding="utf-8")).get("version", "v0")
    except Exception:
        current = "v0"
    if isinstance(current, str) and current.startswith("v") and current[1:].isdigit():
        return f"v{int(current[1:]) + 1}"
    return "v1"


def cmd_publish(args) -> None:
    if not args.yes and not sys.stdin.isatty():
        raise RuntimeError("拒绝非交互式发布，请显式传入 --yes")
    if not args.yes:
        confirm = input(f"确认发布到本地工具目录 {args.project}/{args.name}? [y/N] ")
        if confirm.lower() != "y":
            print("已取消")
            return
    path = tool_path(args.project, args.name)
    content = read_content_arg(args) if args.file or args.stdin else read_text(path)
    write_text(path, content)
    version = next_version(path)
    sidecar_path(path).write_text(
        json.dumps(
            {
                "project": path.parent.name,
                "name": path.stem,
                "version": version,
                "revision": sha256_text(content),
                "published_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    result = local_result(
        True,
        project=path.parent.name,
        name=path.stem,
        version=version,
        revision=sha256_text(content),
        path=str(path),
        url=f"/tools/{path.parent.name}/{path.stem}",
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"✓ 本地发布成功: {path.parent.name}/{path.stem}")
    print(f"  版本: {version}")
    print(f"  路径: {path}")


def cmd_status(args) -> None:
    path = tool_path(args.project, args.name)
    if not path.is_file():
        raise FileNotFoundError(f"工具不存在: {args.project}/{args.name}")
    meta = tool_meta(path)
    status = {}
    if sidecar_path(path).is_file():
        status = json.loads(sidecar_path(path).read_text(encoding="utf-8"))
    result = local_result(True, tool=meta, state={"indexed": True, "published": bool(status)}, publish=status)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"✓ 工具状态: {meta['project']}/{meta['name']}")
    print(f"  路径: {path}")
    print(f"  当前版本: {status.get('version') or '本地文件'}")
    print(f"  Revision: {meta['revision']}")


def cmd_delete(args) -> None:
    path = tool_path(args.project, args.name)
    if not path.exists():
        raise FileNotFoundError(f"工具不存在: {args.project}/{args.name}")
    if not args.yes:
        confirm = input(f"确定删除本地工具 {path.parent.name}/{path.stem}? [y/N] ")
        if confirm.lower() != "y":
            print("已取消")
            return
    path.unlink()
    sidecar = sidecar_path(path)
    if sidecar.exists():
        sidecar.unlink()
    result = local_result(True, project=path.parent.name, name=path.stem)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"✓ 删除成功: {path.parent.name}/{path.stem}")


def cmd_preview(args) -> None:
    if bool(args.project) != bool(args.name):
        raise ApiError(400, {"success": False, "message": "固定预览必须同时提供 project 和 name"}, "固定预览必须同时提供 project 和 name")
    content = read_content_arg(args)
    url = f"{args.server}/api/tools/preview/{args.project}/{args.name}" if args.project else f"{args.server}/api/tools/preview"
    result = make_request(url, method="POST", data={"content": content})
    result["preview_url"] = build_public_url(args.server, result.get("preview_url") or result.get("url", ""))
    if result.get("log_url"):
        result["log_url"] = build_public_url(args.server, result["log_url"])
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"✓ 预览地址: {result['preview_url']}")
    if result.get("log_url"):
        print(f"  日志地址: {result['log_url']}")


def cmd_prelog(args) -> None:
    from preview_log import snapshot

    if args.json:
        result = snapshot(args, make_request, make_raw_request)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        if not result["success"]:
            sys.exit(1)
        return
    if not args.target:
        result = make_request(f"{args.server}/api/tools/preview/list")
        rows = [[item["key"][:16] + "...", item.get("title") or "-", str(item.get("created_at", ""))] for item in result.get("tools", [])]
        print_table(["Key", "名称", "创建时间"], rows)
        return
    lines = args.lines or 50
    if args.name:
        log_url = f"{args.server}/api/tools/preview/log/fixed/{args.target}/{args.name}"
    else:
        log_url = f"{args.server}/api/tools/preview/log/{args.target}"
    status, content = make_raw_request(f"{log_url}?lines={lines}")
    if status != 200:
        raise RuntimeError(f"获取日志失败: HTTP {status}\n{content}")
    print(content)


def cmd_toollog(args) -> None:
    base = logs_dir() / 'runs'
    rows = []
    for marker in base.glob('*/*/*/run.json'):
        if any(item.is_symlink() for item in (marker, marker.parent, marker.parent.parent, marker.parent.parent.parent, base)):
            continue
        try:
            metadata = json.loads(marker.read_text(encoding='utf-8'))
            if metadata.get('preview_key') is not None:
                continue
            if (metadata['project'], metadata['name'], metadata['id']) != (marker.parents[2].name, marker.parents[1].name, marker.parent.name):
                continue
            if not re.fullmatch(r'[a-f0-9]{32}', metadata['id']):
                continue
            path = marker.parent / 'tool.log'
            if path.is_symlink() or not path.is_file():
                continue
            rows.append((float(metadata['created']), metadata['project'], metadata['name'], metadata['id'], path))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    rows.sort(reverse=True)
    if args.project and args.name:
        matches = [row for row in rows if row[1:3] == (normalize_name(args.project), normalize_name(args.name)) and (not args.run or row[3] == args.run)]
        if not matches:
            raise FileNotFoundError('No matching published tool run log')
        print('\n'.join(matches[0][4].read_text(encoding='utf-8', errors='replace').splitlines()[-(args.lines or 50):]))
        return
    print_table(['Project', 'Name', 'Run'], [[project, name, run_id] for _, project, name, run_id, _ in rows])


def add_content_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--file", "-f", help="从文件读取代码")
    parser.add_argument("--stdin", action="store_true", help="从标准输入读取代码")


def requires_server(command: str) -> bool:
    return command in {"preview", "prelog"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Calabash local tool CLI")
    parser.add_argument("--server", default=None, help="本地 Calabash 服务地址，仅 preview/prelog 需要")
    parser.add_argument("--skill-root", action="store_true", help="打印 skill 根目录路径后退出")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser("list", help="列出本地工具")
    list_parser.add_argument("--project", "-p", help="按项目过滤")
    list_parser.set_defaults(func=cmd_list)

    subparsers.add_parser("projects", help="列出本地工具项目").set_defaults(func=cmd_projects)

    get_parser = subparsers.add_parser("get", help="获取本地工具详情")
    get_parser.add_argument("project")
    get_parser.add_argument("name")
    get_parser.add_argument("--output", "-o")
    get_parser.set_defaults(func=cmd_get)

    create_parser = subparsers.add_parser("create", help="本地创建工具文件")
    create_parser.add_argument("project")
    create_parser.add_argument("name")
    add_content_args(create_parser)
    create_parser.add_argument("--title")
    create_parser.add_argument("--description")
    create_parser.add_argument("--creator")
    create_parser.add_argument("--tags")
    create_parser.set_defaults(func=cmd_create)

    publish_parser = subparsers.add_parser("publish", help="写入并标记本地工具版本")
    publish_parser.add_argument("project")
    publish_parser.add_argument("name")
    add_content_args(publish_parser)
    publish_parser.add_argument("--yes", "-y", action="store_true")
    publish_parser.set_defaults(func=cmd_publish)

    status_parser = subparsers.add_parser("status", help="查看本地工具状态")
    status_parser.add_argument("project")
    status_parser.add_argument("name")
    status_parser.set_defaults(func=cmd_status)

    delete_parser = subparsers.add_parser("delete", help="删除本地工具")
    delete_parser.add_argument("project")
    delete_parser.add_argument("name")
    delete_parser.add_argument("--yes", "-y", action="store_true")
    delete_parser.set_defaults(func=cmd_delete)

    preview_parser = subparsers.add_parser("preview", help="通过本地服务预览工具")
    preview_parser.add_argument("project", nargs="?")
    preview_parser.add_argument("name", nargs="?")
    add_content_args(preview_parser)
    preview_parser.set_defaults(func=cmd_preview)

    prelog_parser = subparsers.add_parser("prelog", help="查看预览日志")
    prelog_parser.add_argument("target", nargs="?")
    prelog_parser.add_argument("name", nargs="?")
    prelog_parser.add_argument("--lines", "-n", type=int)
    prelog_parser.add_argument("--max-chars", type=int, default=8000)
    prelog_parser.set_defaults(func=cmd_prelog)

    toollog_parser = subparsers.add_parser("toollog", help="查看工具日志")
    toollog_parser.add_argument("project", nargs="?")
    toollog_parser.add_argument("name", nargs="?")
    toollog_parser.add_argument("--run", help="Read a specific published run; defaults to latest")
    toollog_parser.add_argument("--lines", "-n", type=int)
    toollog_parser.set_defaults(func=cmd_toollog)

    args = parser.parse_args()
    if args.skill_root:
        print(SKILL_ROOT)
        return
    if not args.command:
        parser.print_help()
        raise SystemExit(1)
    try:
        if requires_server(args.command):
            if not args.server:
                parser.error("preview/prelog 需要显式传入 --server，例如 http://127.0.0.1:8000")
            args.server = args.server.rstrip("/")
        args.func(args)
    except ApiError as exc:
        print(json.dumps(exc.data, ensure_ascii=False, indent=2) if args.json else f"错误: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        if args.json:
            print(json.dumps(normalize_error_payload({"error": str(exc)}), ensure_ascii=False, indent=2), file=sys.stderr)
        else:
            print(f"错误: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
