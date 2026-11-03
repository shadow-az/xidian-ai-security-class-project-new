# 阶段 4：真实资料分析、入库与归档验证

2026-11-01 本人授权补齐截至今天的计划任务。先提交此入口，再实际验证；不补造历史日期。

从已实际采集的5条来源中，按上一阶段元数据初筛选择 LLMVault 与 rag-security-scanner 两条直接相关资料。执行 `.venv\Scripts\python.exe -m tools.course_analyze`，复用现有规则分析、SQLite 入库及 Markdown 同步，不调用模型。

入口使用独立的本地验证数据库和专用知识库目录，避免修改个人已有知识库。检查输入输出数量、标题、原始正文、来源链接、发布时间对应关系，并重复入库验证文档不重复、采集观察保留。数据、分析结果、数据库、知识库和日志仅本机保存，不提交仓库。

初版尚未执行，不能宣称入库或归档已通过；运行后补充真实结果和失败修复说明。来源元数据的描述属于作者声明，不代表已验证工具安全效果。

## 初版核验与失败证据

初版 `71c9ee2` 已先推送，再运行。第一次真实执行在发布时间核对处失败：GitHub 采集器输出 `published_at`，而 `_normalize` 只读取 create_time/publish_time/time/date，导致日期丢失。合成字段回归测试复现为 `1 failed, 3 passed`。最小修复为优先读取 published_at，保留原来的兼容字段和空值回退。

修复日期后，重复入库检查出现 `UNIQUE constraint failed: sync_runs.id`；进一步在固定同秒时间重复处理同一文件，复现 `crawl_observations.id` 冲突，相关去重测试为 `1 failed, 4 passed`。原运行标识由秒级时间和路径组合而成，不足以区分同秒执行。改为每次入库生成 UUID 运行标识，同步日志使用该运行标识派生 ID；文档指纹与稳定文档 ID 保持原策略，不重写已有数据。

## 修订后实际验证

```powershell
.venv\Scripts\python.exe -m pytest tests/test_analysis_provenance.py tests/test_research_deduplication.py -q
.venv\Scripts\python.exe -m tools.course_analyze
```

- 9 项回归通过：4 个来源字段映射场景、原有4项去重场景、同秒重复入库与运行日志保留场景。
- 真实输入2条、分析输出2条，主题过滤未丢失这两个已人工初筛的直接相关候选，模型开关为 false。
- 标题、正文、URL、来源发布时间在原始记录、标准化结果与 SQLite 中逐条一致。
- SQLite 文档2条；第二次入库后仍为2条，采集观察为4条。
- 学术知识库生成2份 Markdown；每份包含对应公开链接和稳定文档 ID，再次同步没有新增重复笔记。
- 使用 knowledge/course_validation/<运行时间>/ 专用知识库和 data/course_validation/<运行时间>/ 专用数据库；未修改个人既有知识库。失败运行产物仅留本地用于排错，验收按最后成功运行结果计。

## 证据边界与后续工作

本次分析正文是 GitHub API 的公开仓库描述，不是下载的完整 README、论文全文或经验证的漏洞报告。规则摘要属于描述摘录，关键词与主题匹配不是安全效果证明；两个项目仅作为候选资料来源。已完成课程基础数据链路复现，尚未验证外部模型摘要、研究想法生成、社交平台或 AI Scientist 实验。次日继续整理最终复现报告和交付检查，向班级仓库发 PR 仍需本人明确授权。
