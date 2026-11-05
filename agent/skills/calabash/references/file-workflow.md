# 文件与结果

工具前端使用宿主注册的 CalabashFiles（change 事件返回 ID、名称、状态）、CalabashResults、CalabashJobStatus。文件默认列表可追加/移除/清空，执行中冻结。不要给用户展示内部路径。

后端 sdk.inputs() 返回已选择文件 ID；sdk.input_path(id) 检查当前快照并解析路径。阻塞处理使用 await sdk.io。不要读取任意机器路径或覆盖输入文件。

sdk.output_path(name) 创建工具所属临时输出位置；处理成功后 sdk.add_result(path) 将完成文件写入持久结果服务。CalabashResults 在没有文件时不占空间，结果可下载；重新打开工具仍可查询历史结果。

聊天附件与工具输入是不同授权范围，不自动把所有聊天文件交给任意工具。模型只读取用户在当前对话明确发送的附件。
