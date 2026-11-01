# 阶段 3：GitHub 小规模采集与检索修订

2026-11-01 补做先前未完成的公开资料采集模块，按本人要求先提交可复现入口，再实际运行、核实并补充结果。

运行：在项目 04 目录执行 `.venv\Scripts\python.exe -m tools.course_collect`。

入口复用 `media_platform/research/core.py` 中的 `GithubCrawler`，固定查询 `RAG security`，按 stars 降序，每页最多 5 条，只请求一次查询，不使用浏览器登录。将现有采集器产出的记录保存为独立 JSONL，避免重复运行时追加混淆批次；原始数据留在忽略的 data 目录中。

初版尚未运行，不能宣称采集成功或内容已人工核验。待检查 HTTP 结果、实际数量、字段完整性、重复来源、公开链接，以及标题/描述与 RAG 安全主题的相关性。后续清洗分析及知识归档属于下一模块。

## 初版核验：查询过宽

初版 `5150ce1` 推送后，于北京时间 2026-11-01 19:08:34 实际运行，GitHub API 请求成功，返回 5 条且来源链接唯一，JSONL 保存并可重新解析。初版文件为本地 `data/github/jsonl/course_rag_security_20261101T110834459456Z.jsonl`，未提交。

逐条查看标题、描述和 topics 后，发现检索相关性有限：quivr、DB-GPT 是通用平台，mine-ai 是支付安全/合规方向；ai-engineer-notebooks 为综合教程，LLMVault 为安全训练平台。不能把检索命中等同于全部适合提示注入研究，不能把 stars 排序当作可信度评分。

## 修订与再次验证

默认查询收紧为 `topic:rag topic:prompt-injection`，要求来源自行标注两种主题。新增 `--query` 和 `--limit` 参数以便复现，数量只允许 1–5，并检查重复来源。两次执行各为一个英文查询，没有触发中文关键词扩展。超出上限的 `--limit 6` 已验证会被参数解析拒绝，未发起新采集。

```powershell
.venv\Scripts\python.exe -m tools.course_collect --query 'topic:rag topic:prompt-injection' --limit 5
```

修订后于北京时间 2026-11-01 19:09:47 实际执行成功，按 stars 降序返回 5 条，来源链接唯一，每条同时包含 rag 和 prompt-injection topics；标题、URL 均非空。原始 JSONL 留在 `data/github/jsonl/course_rag_security_20261101T110947104727Z.jsonl`，报告不附原始采集记录。

以下为基于本次 API 元数据的人工初筛，不代表已审阅源代码或验证工具安全效果：

| 公开来源 | 初筛用途 | 核验边界 |
| --- | --- | --- |
| [CyberSunil/LLMVault](https://github.com/CyberSunil/LLMVault) | 描述明确涉及提示注入和 RAG 安全，可作为训练场景候选 | 未部署或执行其测试 |
| [heaven999b/hello-agent-system](https://github.com/heaven999b/hello-agent-system) | Agent、RAG、安全教程，作为背景资料 | 未逐章核验具体防御结论 |
| [Ali-hey-0/ai-runtime-lab](https://github.com/Ali-hey-0/ai-runtime-lab) | 涉及 RAG 与安全的系统工程参考 | 主题标签不能证明实验有效 |
| [RikyZ90/ShibaClaw](https://github.com/RikyZ90/ShibaClaw) | 通用 Agent 项目，暂不作为核心研究证据 | 描述未直接论证提示注入，待深入核验 |
| [olegnazarov/rag-security-scanner](https://github.com/olegnazarov/rag-security-scanner) | 描述明确涉及 RAG/LLM 安全扫描，可作为工具候选 | 未运行扫描，未确认检测准确率 |

双主题查询改善了候选约束，但标签由仓库作者提供，仍需人工筛选。下一阶段只将初筛为直接相关的资料优先用于分析与归档，并保留排除/待定理由。本模块没有进行模型调用、源代码执行、漏洞扫描或知识库归档。
