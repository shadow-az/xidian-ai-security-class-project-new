# 项目 01 课程复现记录

## 任务与节点

目标：梳理自动研究流程，独立复现一个模块，完成有明确目标的修改，并分析证据、模型输出和实验结果的关系。

| 节点 | 交付内容 | 状态 |
| --- | --- | --- |
| ① 流程与基线 | 源码流程、环境版本、离线样例、原实现的结果 | 已完成 |
| ② 目标修改 | 改进 JSON 提取，接入两个研究入口，对比修改前后 | 待实施 |
| ③ 验证与分析 | 边界验证、证据关系分析、可复现步骤与局限 | 待补齐最终结果 |


## 自动研究流程：源码追踪

下表记录本地源码的控制流，不表示本次已完整运行这些阶段。

| 阶段 | 输入与行为 | 主要代码 |
| --- | --- | --- |
| 入口选择 | 详细想法模式进入 `run_infer_plan`；参考文献构思模式进入 `run_infer_idea`；论文生成是单独的模式 | `main_ai_researcher.py::main_ai_researcher` |
| 任务及检索 | 读取 benchmark 的参考文献与任务；查询 arXiv 元数据取得日期；根据文献搜索 GitHub 仓库 | 两个入口的 `load_instance`、`github_search` |
| 准备参考材料 | Prepare Agent 阅读搜索结果、选择仓库，返回论文、仓库及路径列表；优先读取结构化 `prepare_result`，缺少时才从文本提取 JSON；校验后下载论文源码 | 两个入口的 `InnoFlow.forward`；`prepare_agent.py::case_resolved`；`flowcache.py::validate_prepare_result` |
| 构思或调研 | 参考文献模式生成 5 个想法并选择一个，再进行代码调研；详细想法模式对输入想法进行论文和代码调研 | `run_infer_idea.py` 的 Idea / Code Survey Agent；`run_infer_plan.py` 的 Survey Agent |
| 计划与开发 | Coding Plan Agent 制定计划；ML Agent 按计划实现，并被提示在真实数据集上完成 2 epoch 训练测试 | 两个入口的 Coding Plan / ML Agent 调用 |
| 评审与迭代 | Judge Agent 检查实现；按 `max_iter_times` 进行修改；提交阶段继续执行实验；再进行两轮实验分析和修改 | 两个入口的 Judge / ML / Experiment Analysis Agent 调用 |
| 论文生成 | 分别组织方法、相关工作、实验、引言、结论、摘要，再清理和编译 LaTeX | `paper_agent/writing.py::writing` |

注意：`max_iter_times=0` 只取消对应的评审修改循环，首次开发、提交实验与后续两轮分析仍在控制流中，不能据此认为整套流程不再执行代码。提示词要求训练成功，也不等于已有实验日志证明成功。

## 选取模块与明确问题

本次选择两个入口中相同的 `extract_json_from_output`，它是 Prepare Agent 文本结果的**回退解析路径**。已有结构化 `prepare_result` 时，该函数通常不会被调用。

原实现用栈对所有 `{` / `}` 计数，没有区分 JSON 字符串与对象结构，存在三个可观察问题：

1. 字符串中的 `}` 会提前结束截取；字符串中的 `{` 会让结构无法闭合。
2. JSON 之前的孤立 `}` 会对空栈执行 `pop()`，抛出 `IndexError`。
3. 遇到 `{placeholder}` 等非 JSON 内容后，解析失败便返回 `{}`，不会找到后续的有效结果。

节点②目标：正确处理字符串、转义与说明前缀中的括号，保留对普通对象和代码围栏的支持；没有完整对象时返回 `{}`，不将截断结果的内层对象当作完整输出。两个入口应共享一致的行为。该修改旨在提高文本解析可靠性，不能证明参考文献真实或模型研究结论正确。

## 节点①环境与版本

记录日期：2026-11-05（Asia/Shanghai）。

| 项目 | 本次记录 |
| --- | --- |
| 课程副本的基线父提交 | `a2d043f9db3bb18c0914faba4bc4ef81a2ff43b1` |
| 上游版本 | 课程 README 记录为 `f9a6f8480860c193afff600eeffe3defcee8a978` |
| 系统 | Windows，NT 10.0 build 26200，AMD64；Python 3.11 的 `platform.platform()` 输出见结果 JSON |
| 本次解释器 | CPython 3.11.17，uv 管理的 Windows Python |
| PowerShell | 7.6.5 |
| Git | 2.56.0.windows.2 |
| uv | 0.13.0；已记录版本，本实验不依赖 uv 命令 |
| 第三方包 | 无，仅使用 Python 标准库 |
| 模型、API、GPU、Docker | 均未使用 |

当前 PowerShell 的默认 `python` 是 3.10.10，因此本次显式选择 Windows Python 3.11.17。项目已有 `.venv` 为 Linux 环境，本次没有修改或使用它。完整项目的依赖安装与网页运行不属于这次模块验证。

## 最小示例和运行命令

文件：

- `reproduce_json_extraction.py`：从实际入口文件的 AST 中载入原函数，执行样例。没有复制一份待测算法，也不导入完整应用或读取 `.env`。
- `fixtures/json_extraction_cases.json`：10 条人工构造的输出文本、期望对象及来源说明。
- `results/baseline.json`：本次执行生成的环境、父提交、源码/样例 SHA-256、逐条结果与异常。

在课程仓库根目录打开 PowerShell：

```powershell
Set-Location 'projects/project-01-ai-researcher'
$coursePython = Join-Path $env:APPDATA 'uv/python/cpython-3.11-windows-x86_64-none/python.exe'
& $coursePython --version
& $coursePython coursework/reproduce_json_extraction.py --output coursework/results/baseline.json
```

其他电脑可使用自己安装的 Python 3.11+，例如：

```powershell
python --version
python coursework/reproduce_json_extraction.py --output coursework/results/baseline.json
```

以上命令必须在项目 01 目录执行。修复后使用新的结果文件名，保留原始基线。脚本默认返回 0 表示复现实验成功执行并写入记录，不表示所有样例通过。添加 `--require-all` 时，只要有样例失败就返回 1：

```powershell
& $coursePython coursework/reproduce_json_extraction.py --output coursework/results/check.json --require-all
$LASTEXITCODE
```

基线的严格检查应返回 1。`check.json` 是临时检查产物，不需提交。

最小失败输入：

```text
{"reference_papers":["Neural discrete representation learning"],"note":"A literal } is part of this note."}
```

期望：返回完整字典。实测：两个入口均打印 JSON 解析错误并返回 `{}`。字符串内的 `}` 被当成外层对象结束位置，导致截取到不完整的 JSON。

## 节点①基线结果

“符合预期”按返回对象与 fixture 中 `expected` 的完整相等比较，并要求未发生异常。无 JSON 与截断 JSON 的期望都是 `{}`，属于正确拒绝，不是成功提取。

| 样例 | 构思入口 | 详细想法入口 |
| --- | --- | --- |
| 普通 JSON | 符合预期 | 符合预期 |
| Markdown 代码围栏 | 符合预期 | 符合预期 |
| 嵌套对象及数组 | 符合预期 | 符合预期 |
| 字符串内含 `}` | 返回 `{}`，失败 | 返回 `{}`，失败 |
| 字符串内含 `{` | 返回 `{}`，失败 | 返回 `{}`，失败 |
| 转义引号与括号 | 返回 `{}`，失败 | 返回 `{}`，失败 |
| 前缀孤立 `}` | `IndexError` | `IndexError` |
| 非 JSON 占位符前缀 | 返回 `{}`，失败 | 返回 `{}`，失败 |
| 外层 JSON 截断 | 正确返回 `{}` | 正确返回 `{}` |
| 无 JSON 文本 | 正确返回 `{}` | 正确返回 `{}` |

每个入口 **5/10 符合预期**，共 20 次函数调用、10 次符合预期。两个入口使用相同算法和相同样例，这 20 次调用不是 20 个独立样本，50% 也不能解释成真实模型输出的失败概率。

## 检索证据、模型输出与结果：目前能说明什么

完整流程中，检索结果提供候选论文与仓库；Prepare Agent 输出是对这些候选材料的选择；解析和字段校验决定后续能否取得参考材料；实现及真实运行才产生实验指标。各阶段需要分别核验。

本次离线样例仅从 `benchmark/final/vq/rotation_vq.json` 的 `source_papers[0].reference` 读取一条标题作为可追踪的本地输入。脚本核对标题并记录该文件的哈希。这是课程已有材料的读取，没有执行在线检索；文件中的文献说明与结论也未在本次重新核验。`offline-reference` 及其路径都是实验占位符，没有下载对应仓库。

样例输出为人工构造，`model=null`，不是模型实际生成。实验结果是实际执行原解析函数得到的对象或异常。部分样例只保留 `reference_papers` 以隔离语法问题，并不满足完整 Prepare Agent 的三个必填列表；本实验的通过标准也不代表能通过完整业务校验。

可以据此得出：即使输出中的参考文献标题与本地输入一致，有效 JSON 也可能因括号出现在字符串中而在回退路径丢失。不能据此断言：模型产生了幻觉、检索证据不可靠，或修复后训练指标会提高。`validate_prepare_result` 检查字段形状，不负责验证文献存在、候选来源一致性或实验结论。

## 验证范围与局限

- AST 载入运行实际函数的原始语法树，隔离了 LLM、Docker、浏览器等无关依赖；未验证完整入口导入、缓存及 agent 上下文的集成行为。
- 10 个刻意挑选的样例用于复现边界问题，样本量小且不是随机抽样；尚未统计真实模型输出分布。
- 没有模型 API 请求、在线文献或仓库检索，没有训练结果，也没有生成论文。项目自带 examples 的结果未当作本次结果。
- 当前结果只说明修改前行为；节点②完成后补充同样输入下的对照，节点③再补充回归验证和最终局限。
