# 工具任务生命周期

sdk.start_batch(values, async_handler) 顺序处理任务，sdk.io(function,*args) 承载阻塞业务。GET /api/sdk/status 提供真实状态、进度和计数，POST /api/sdk/cancel 请求安全停止。当前文件完成后再停止后续任务，不强行中断文件写入。

运行时禁止重复提交及修改输入。页面切换不终止工具进程，关闭运行中的工具应提醒并请求安全停止。任务结束后才能关闭。用户关闭 App 时同样先安全停止。

工具前端不使用 App 的全局变量。关键业务数据通过 sdk.read_json/write_json 或工具所属 SQLite 持久化；HMR 不承诺保留全部组件状态。
