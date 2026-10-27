# 文件输入、结果与批量任务

适用于读取用户文件、导出产物或批量处理的 Calabash。普通表单、查询和纯计算工具继续使用其他模板，不为它们强加文件组件。可运行的 CSV 示例见 [file-tool.py](file-tool.py)；Excel/PDF/Word 等任务替换其中的处理函数，不保留与任务无关的 CSV 限制。

共享组件由 Calabash 宿主提供，优先在正式工具页或预览页验证。模板的本地 run guard 只适用于能导入 `component`/`service` 的开发环境；不要复制平台组件进工具，或把它当作无需宿主的独立脚本。

## 输入

在 `main()` 的 UI 上下文中创建：

```python
from component.tool_files import ToolFileInput

inputs = ToolFileInput()
```

- `inputs.paths` 返回 `list[str]`，不是 Path 对象；用 `Path(path)` 转换。
- 聊天预览自动带入当前上下文的附件；独立打开时为空，用户可以用内置选择器选择文件。不要硬编码本次用户路径、手工拼接上下文 URL 或从所有聊天附件表中扫描文件。
- 开始执行时用 `paths = inputs.freeze()` 获取不可变的 `tuple[str, ...]` 并冻结输入；捕获 `ValueError`，为空时先 `inputs.unfreeze()` 再返回。整个运行在 `try/finally` 中，最终调用 `inputs.unfreeze()`；初始化任务失败也必须解锁。
- 默认追加文件，自动按真实路径/文件身份去重；取消选择保留列表。支持逐项移除、清空和重新选择不可用文件，只改当前页面输入引用，不删除源文件，不改历史聊天附件。刷新页面恢复上下文默认输入，不持久化本次改选。
- `inputs.files` 返回 key、name、type、size、status 元数据；状态为 ready/changed/missing/denied/expired/not_file。执行前读取路径会重新检查；通过“检查文件状态”可更新显示。不是持续文件监听，不支持目录递归。
- `inputs.set_enabled(False/True)` 冻结/解锁全部输入变更，`inputs.frozen` 查看状态。`inputs.add_paths(paths)`、`inputs.remove(key)`、`inputs.clear()` 同样遵守冻结；`inputs.add_files()`、`inputs.reselect(key)` 为异步原生选择操作。冻结前打开、冻结后才返回的选择结果也会被忽略。
- 冻结仅锁定输入选择，不锁定磁盘文件内容；工具仍需在实际处理时检查文件变化并友好报错。
- 附件正文只有在 Agent 调用受控读取接口时才发送至所选模型；工具本地处理使用完整输入，不用聊天的前几行样本做全量统计。不要声称生成的 Python 工具处于沙箱。

## 结果文件

```python
from component.tool_results import ToolResults
from nicegui import run

results = ToolResults()  # 在 main() 内创建

async def export():
    results.start_run()  # 每次用户发起的新执行调用一次
    await run.io_bound(
        results.outputs.write,
        "report.xlsx",
        lambda destination: dataframe.to_excel(destination, index=False),
    )
    results.refresh()  # 回到 UI 任务后刷新，不在 writer 中创建 UI
```

| API | 契约 |
|---|---|
| `results.start_run()` | 为一次新执行创建批次，保留历史；失败项重试不调用它。 |
| `results.outputs.write(name, writer)` | 同步操作，放在 `run.io_bound`；name 只能是文件名。writer 接收一个私有临时 Path，成功后自动登记并返回随机结果 ID。 |

`ToolResults()` 在创建时立即渲染到当前容器，无需且不存在 `mount()`。需要放到页面底部时，在底部容器内创建；写出文件后调用 `results.refresh()`。
结果为空时组件完全隐藏；有文件时默认显示紧凑的折叠入口，用户展开后查看结果和交付操作。不要额外创建空结果占位、预留高度或重复结果面板。
| `results.refresh()` | 重读历史和文件状态，更新 UI；不恢复批量任务执行状态。 |
| `results.outputs.files()` | 返回元数据列表：id、name、size、run_id、created、available。不是路径列表。 |
| `results.outputs.path(file_id)` | 按当前作用域校验结果 ID、文件身份和存在性；不要改成接收浏览器提交的任意本机路径。 |

文件默认写入 `~/.calabash/outputs/standalone/<run>/` 或会话哈希目录，同一批次重名自动加序号。工具缓存与偏好可放 `~/.calabash/tool-data`，用户交付文件使用结果组件。无需自行拼输出路径、维护结果数据库或构造下载路由。

正式工具恢复该工具的独立运行结果；聊天预览恢复当前工具在当前对话中的结果。归属由平台页面壳设置，不要传入/伪造其他工具或对话的 owner。元数据存于 SQLite；刷新、重新打开和重启后恢复。缺失或变化的产物显示不可用，删除对话只删除关联，不删除实际产物。以前没有登记的文件不会自动导入。

结果列表已包含打开、定位、保存副本及历史分页，不重复实现一套按钮。桌面保存副本使用原生对话框，取消不创建文件；当前实现拒绝覆盖已存在的目标，选择新的文件名。浏览器模式降级下载，不能把浏览器验证写成原生权限验证。

## 批量任务

```python
from pathlib import Path
from component.tool_results import ToolJobStatus
from service.tools.tool_jobs import ToolJobs

async def process():
    paths = inputs.freeze()
    if not paths:
        inputs.unfreeze()
        return
    results.start_run()
    jobs = ToolJobs(paths)
    status = ToolJobStatus(jobs)  # 在已捕获的 UI 容器内创建

    async def handle(source):
        source = Path(source)
        result_id = await run.io_bound(
            results.outputs.write,
            source.stem + "_copy" + source.suffix,
            lambda destination: destination.write_bytes(source.read_bytes()),
        )
        results.refresh()
        return result_id

    try:
        await status.run(handle)
    finally:
        inputs.unfreeze()
```

以上复制片段仅说明 API；大文件使用流式复制，或采用模板的流式处理函数。UI 控件在 `main()`/UI 回调中创建；writer 只做阻塞数据处理，不能调用 `ui.*`、`results.refresh()` 或修改控件。

- handler 是接受单个任务值的 **async 函数**，内部用 `await run.io_bound(...)` 执行文件 I/O。传同步 handler 会被误判为失败，不要这样使用。
- `ToolJobStatus.run(handler)` 内置取消按钮和失败重试入口；重试复用捕获的 handler，只处理 failed 项，成功项不会重复写文件。不要在 handler 内调用 `start_run()`。
- 状态为 queued/running/succeeded/failed/cancelled；`jobs.running` 用于阻止新批次与重试重叠。参考模板局部 `BatchStatus.refresh()`，通过 `inputs.set_enabled(not self.jobs.running)` 在初次执行和失败重试期间都冻结输入，同时冻结处理参数和开始按钮。不要仅在提交回调中禁用控件。
- 重试沿用原批次的路径快照和参数，不读取后来编辑的输入草稿；改选文件只影响下一次新执行。取消后仍等待当前文件完成，期间保持冻结。上面的简略片段只展示初次运行清理，完整重试绑定和初始化错误处理以模板为准。
- 取消只停止后续调度，等待当前处理函数结束；`jobs.cancelling` 为真时不声称任务已终止。不能用取消 asyncio task 来伪装中断线程写入。
- 文件变化、格式问题逐项失败，不丢掉成功结果；技术详情写日志，界面保留可执行的错误提示。
- 任务队列不跨重启恢复，也不是应用级定时调度器。不要新增后台调度来实现普通批量按钮。

## 写入边界与验收

默认只生成新文件，不修改输入。确实要求覆盖、移动或删除原文件时，先呈现具体变更清单并取得确认；当前平台没有通用的破坏性操作确认 API，不要编造 `confirm_changes` 等方法或把 `ToolResults` 当作覆盖授权。

校验模板后，用合成文件验证：预览默认输入、无上下文选择、混入损坏文件、失败项重试不重复成功项、执行中取消、新运行分组、刷新恢复历史、原文件字节不变。明确区分静态检查、浏览器交互、桌面原生操作及真实模型生成验证，不擅自使用用户原文件测试写入。
