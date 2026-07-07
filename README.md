# USYD Assessment Collector

用于提取 University of Sydney 指定 unit 在指定年份和学期的 assessment 信息，并生成 `task_info.html` 方便查看。

## 使用方法

1. 启动 `collector.py`。
2. 在窗口中选择年份和学期。
   - 1 月默认选择上一年的 `S2`。
   - 2 月到 7 月默认选择今年的 `S1`。
   - 8 月到 12 月默认选择今年的 `S2`。
3. 输入 unit code，例如 `WRIT1000`。
4. 点击 `提取`。
   - 如果该年份和学期存在这个 unit，会把 assessment 追加写入 `task_info.html`。
   - 如果当前学期没有这个 unit，会弹出提示窗口。
   - 如果该 unit 已经在结果中存在，不会重复提取。
5. 点击 `打开结果` 可以直接查看 `task_info.html`。
6. 点击 `清除结果` 可以清空已有结果。
7. 点击 `退出` 关闭程序。

## 输出文件

- `task_info.html`：最终查看用的 assessment 页面。
- `resources/task_info.md`：程序内部用于保存 assessment 数据的 Markdown 文件。
