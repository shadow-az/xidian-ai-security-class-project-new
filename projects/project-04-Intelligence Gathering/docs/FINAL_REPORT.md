# 项目04课程实验报告

学号：26241215007；姓名：arthur-207；整理日期：2026-11-02。

## 目标与范围

围绕RAG安全与提示注入，复现公开资料采集、规则分析、SQLite入库、Markdown归档，并改进去重与来源溯源。基于课程原有平台二次开发，保留MediaCrawler版权与LICENSE。本文保留初版22b478c；以下补充2026-11-02实际交付核验结果。

## 环境与复现

Python 3.12.14、Node.js 24.19.0、FastAPI 0.110.2、httpx 0.28.1。详细版本和本机解释器位置见 ENVIRONMENT_VALIDATION.md。进入项目04目录，使用真实Python创建独立环境，再执行：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m tools.course_smoke
.venv\Scripts\python.exe -m tools.course_collect
.venv\Scripts\python.exe -m pytest tests/test_analysis_provenance.py tests/test_research_deduplication.py -q
.venv\Scripts\python.exe -m tools.course_analyze --source github/jsonl/你的采集文件.jsonl
```

本机WindowsApps的python占位入口不可用，应使用环境报告记录的真实解释器。分析入口现通过--source显式接收data目录下的JSONL文件。请使用采集命令实际输出的文件名；示例占位名必须替换，且目前要求输入包含已人工选择的两个来源。

## 已有实验结果

11月1日已验证依赖一致性、健康接口、首页HTML和采集入口可运行。GitHub宽泛查询RAG security返回5条，但混入通用平台；改为topic:rag topic:prompt-injection后再获5条不重复来源，元数据初筛选出LLMVault与rag-security-scanner。详细来源与筛选边界见 COLLECTION_VALIDATION.md。

两条真实仓库描述完成规则分析与入库，生成2份Markdown笔记。重复入库仍为2份文档，采集观察保留4条。标题、正文、URL、发布时间与数据库逐条核对，笔记包含稳定文档ID及来源链接。详细验证见 ANALYSIS_ARCHIVE_VALIDATION.md。

## 改进与前后对照

| 问题 | 修复前 | 修改及验证 |
| --- | --- | --- |
| 跨批次空白变化 | 同一内容存成2份文档 | 分析与入库共用规范化指纹，修复后1份，观察记录保留 |
| 发布时间丢失 | published_at未映射，分析日期为空 | 优先读取该字段，兼容旧字段与空值回退 |
| 同秒重复入库 | 观察或同步记录主键冲突 | 每次运行使用独立UUID，文档ID稳定 |

截至11月1日，9项相关测试通过。初版、复现与修订提交均保留，未重写历史，见本分支提交记录。

## 局限与交付状态

样本为GitHub仓库元数据及短描述，不是论文全文或工具效果验证。主题标签由作者提供，规则摘要和评分不构成安全结论。未调用模型、生成研究想法、运行扫描器、测试社交登录或AI Scientist。旧数据库不自动迁移合并。数据、知识库、日志、环境和密钥不提交。

当前代码和阶段记录已交个人fork；本轮最终交付检查已通过，详见下表。班级仓库PR尚未创建，需要本人明确授权。上游依赖锁文件安装与完整WebUI交互未验证。

## 2026-11-02交付核验

| 检查 | 实际结果 |
| --- | --- |
| 相关回归 | 9 passed |
| pip check | No broken requirements found |
| 真实服务检查 | 健康接口、首页HTML、采集环境均通过，端口61338，测试进程已停止 |
| 参数化分析入口 | 显式指定实际JSONL后通过，输入输出各2条、数据库重复处理仍2文档、4观察、2笔记 |

修订了分析入口写死历史文件名的问题；未提供--source时参数解析会拒绝执行，提供路径限定在data目录内。重新采集结果会变化，若不含本实验选定的两个来源应先重新人工筛选并调整实验选取范围，不能将无数据当作复现成功。原阶段文档中的无参数命令属于历史初版，当前复现以本文为准。

基础课程流程与改进验证报告已完成。向班级仓库提交PR尚未授权，不能将个人fork推送等同于教师已接收作业。
