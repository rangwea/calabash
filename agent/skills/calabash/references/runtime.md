# 桌面运行环境与能力

创建工具前读取同目录的 [runtime-libraries.json](runtime-libraries.json)。它是宿主 Agent 提示与桌面打包共同使用的依赖契约；不要以 Agent 自己的终端、开发环境或系统 PATH 推断用户 App 的能力。

## 库选择

| 任务 | 首选内置库 | 边界 |
|---|---|---|
| 普通文件、CSV、JSON、SQLite | Python 标准库 | 不因任务简单而增加依赖 |
| 表格清洗与统计 | pandas、numpy | XLSX 读写显式使用 `engine="openpyxl"`，不假定 xlrd/xlsxwriter 可用 |
| XLSX 单元格、格式、工作表 | openpyxl | 不执行公式；`data_only=True` 只能读取已有缓存值 |
| DOCX | `from docx import Document` | 不是 `import python_docx`；不提供 Word 渲染或转 PDF |
| PDF 页面提取、拆分、合并 | pypdf | 扫描页无法直接提取文字 |
| PDF 生成 | ReportLab（`reportlab`） | 非拉丁文字需要合法随附字体，不能硬编码系统字体路径 |
| PDF 页面转图片 | pypdfium2 | 使用内置 PDFium；关闭 page/bitmap/document，限制页数、渲染尺寸与像素总量 |
| 图片读写、缩放、裁剪、旋转 | `from PIL import Image` | Pillow 的导入名是 PIL；限制解码像素量，保持解压炸弹保护，不将任意编码器视为已验证 |
| 交互图表 | `ui.echart` | 不需要 matplotlib 或外部浏览器 |
| HTTP 请求 | httpx | 必须有用户授权；文件正文不能隐式外发 |

常用标准库、平台共享组件和其他边界见 JSON 清单。清单是维护的正式工具运行契约，不是所有传递依赖的公开支持承诺。

## 统一执行生命周期

单个耗时操作使用 `from service.tools.tool_jobs import ToolTask`，批量使用 `ToolJobs`。
两者均配合 `ToolJobStatus(jobs, inputs=(inputs,), controls=(start, parameter))`，由组件冻结输入、禁用控件并防止重复提交；控件原本禁用时不会被误启用。
`await status.run(handler)`：ToolTask 的 handler 无参数，ToolJobs 的 handler 接收单项值。执行前捕获不可变文件路径和普通参数；不要让 worker 读取动态 UI 值或更新 UI。
在 async handler 内 `await run.io_bound(...)` 执行阻塞操作，需要细粒度进度时在事件循环调用 `jobs.report_progress(0.5)`，范围 0 到 1；不伪造耗时进度。
状态为 queued/running/cancelling/succeeded/failed/cancelled。取消后当前项继续完成，未开始项标记 cancelled，已经生成的结果保留。单任务也等待当前操作完成，不将取消按钮当作强杀线程。不要用 task.cancel() 中断文件写入。
离开视图提醒任务继续在后台运行，刷新活动预览被阻止；退出 App 提供等待当前项完成、停止后续调度后退出。任务状态不跨 App 重启恢复。未采用统一组件的旧工具不会被自动改写。

## 工具能力声明

使用可选插件的工具必须在模块 docstring 声明，例如：

```python
"""
requires: media.ffmpeg>=9.0.2
"""
```

只用内置 Python 库时省略 requires 或留空；不要将 pandas、pip 包名、路径或 URL 写入其中。
格式为能力 ID 或 ID>=三段数字最低版本，多个能力以英文逗号分隔，不允许重复；不支持 ==、范围表达式或安装指令。
宿主在导入任何工具模块代码前检查声明，正式工具和嵌入预览使用相同入口。
缺失、损坏或版本不足时显示本地 ZIP 导入入口，导入成功只更新状态，用户点击“重试运行”才会重新检查并加载工具。
未知能力或尚无宿主适配器的能力（包括当前 OCR）会被阻止，不能靠导入任意 ZIP 绕过。
已有未声明的工具保持兼容，宿主不会扫描 import 自动猜测依赖；该检查不是权限沙箱。

## 不安装系统工具

用户不需要系统 Python、pip、uv、Homebrew 或 npm。不能在生成工具中执行包管理器、修改 sys.path 搜索系统包，或调用未经清单提供的系统程序补依赖。外部 Agent 自己运行 Skill CLI 仍需要其运行环境的 Python，这与生成工具在 App 内运行不同，不能让普通 App 用户为工具运行安装 Python。

FFmpeg/ffprobe 是独立的本地 ZIP 插件，首期仅支持 macOS arm64。用户从设置页导入可信签名 ZIP，安装到 ~/.calabash/plugins；不随主 App 打包，不自动下载。创建工具前检查 `MediaRuntime().status()["state"] == "ready"`，不能凭清单声明假称已安装，不直接调用安装管理器。

使用 `from service.capabilities.media_runtime import MediaRuntime`，阻塞操作须用 `await run.io_bound(...)`：

```python
from nicegui import run
from service.capabilities.media_runtime import MediaRuntime

media = MediaRuntime()
info = await run.io_bound(media.probe, selected_path)
result = await run.io_bound(media.convert, selected_path, output_path, profile="flac")
```

接口为 probe(source, event=None, timeout=30)、convert(source, destination, profile=None, event=None, timeout=120)、extract_audio(source, destination, event=None, timeout=120)，event/timeout/profile 为仅关键字参数。profile 仅 wav（PCM）、flac、mp4（MPEG-4 Part 2 视频/AAC 音频）；extract_audio 只输出 wav/flac。只处理用户明确选择的本地文件，不接受网络地址、播放列表或任意参数；不覆盖已有输出。结果交给 ToolResults，任务期间冻结输入，取消用 threading.Event.set()，不要只取消 Python task 而遗留子进程。未支持的编码器可能无法处理某些真实媒体，不能宣称完整 FFmpeg 格式支持。该接口不是权限沙箱。

OCR、浏览器运行时、音视频转写模型、Office 转换、旧版 xls/doc 和 matplotlib 未提供。需要时说明能力限制，优先提出现有能力可实现的替代方案，不静默下载程序或模型。

PDF 渲染能力属于工具可用库，不代表聊天附件解析器已经有 OCR。下载或读取网络内容、覆盖用户原文件仍需遵守原授权边界。生成 Python 工具不是沙箱。

## 验证

开发维护者可运行 `uv run python3 -m backend.desktop_server --check-runtime`。正式 sidecar 支持 `--check-runtime`，输出 JSON 并退出，不启动 Web 服务。打包过程必须运行冻结版自检，导入或资源/动态库检查失败则构建失败。

自检验证 pandas/XLSX、DOCX、PDF 读写、JPEG/PNG 转换、PDF 文字与图片生成、PDFium 非空页面渲染；不使用网络、系统字体或外部程序。自检通过不等于所有文件格式、真实用户文档或所有平台都已测试。
