# 阶段 3：GitHub 小规模采集（初版）

2026-11-01 补做先前未完成的公开资料采集模块，按本人要求先提交可复现入口，再实际运行、核实并补充结果。

运行：在项目 04 目录执行 `.venv\Scripts\python.exe -m tools.course_collect`。

入口复用 `media_platform/research/core.py` 中的 `GithubCrawler`，固定查询 `RAG security`，按 stars 降序，每页最多 5 条，只请求一次查询，不使用浏览器登录。将现有采集器产出的记录保存为独立 JSONL，避免重复运行时追加混淆批次；原始数据留在忽略的 data 目录中。

初版尚未运行，不能宣称采集成功或内容已人工核验。待检查 HTTP 结果、实际数量、字段完整性、重复来源、公开链接，以及标题/描述与 RAG 安全主题的相关性。后续清洗分析及知识归档属于下一模块。
