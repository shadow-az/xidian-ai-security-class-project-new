# 阶段 2：独立环境与启动验证

2026-11-01 补做先前未完成的环境模块，使用真实执行日期，不补造历史提交。

## 初版操作方案

在项目 04 目录创建 `.venv`，以本机可用的 Python 3.12.14 为基础，安装原有 `requirements.txt`，然后运行 `start.py` 并检查本地 HTTP 服务。原 README 建议 Python 3.11，当前版本差异需要实际验证。

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe start.py
```

验收条件：依赖可安装、`pip check` 通过、服务启动后返回实际 HTTP 响应。仅创建环境不能算启动成功。

## 当前状态

初版提交时已创建独立环境，pip 25.0.1 可用。WindowsApps Python 占位入口不可用，实际使用 Codex 随附 Python 绝对路径创建环境；沙箱内 ensurepip 失败，获准在沙箱外重试后成功。依赖安装和服务检查尚待下一步执行，未宣称已完成。

所有环境、配置和运行输出仅保留本机；不提交密钥或依赖目录。按本人要求先提交这一初版方案，再记录核验与修正结果。

## 核验与修订结果

初版提交 `6304893` 已推送。2026-11-01 实际执行原 requirements.txt 的完整安装，退出码 0；未修改上游依赖声明。`pip check` 输出 `No broken requirements found.`。

初版中的裸 `python` 命令在本机仍会命中 WindowsApps 占位入口，应先指定真实解释器创建环境：

```powershell
& 'C:/Users/Arthur/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt --disable-pip-version-check
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m tools.course_smoke
.venv\Scripts\python.exe -m pytest tests/test_research_deduplication.py -q
```

第一行是本机解释器位置，其他同学需换成自己的真实 Python。首次 ensurepip 在沙箱内失败，获准在沙箱外执行后成功；这属于本机执行限制，不修改项目启动代码来绕过。

新增 `tools/course_smoke.py` 自动启动真正的 `start.py`，选择空闲本地端口，依次检查接口与网页，最后终止自己创建的子进程。2026-11-01 验证端口为 60993，结果：

| 检查 | 实际结果 |
| --- | --- |
| `/api/health` | HTTP 200，`{"status":"ok"}` |
| `/` | HTTP 200，Content-Type 为 HTML，响应含 html 标签 |
| `/api/env/check` | `success=true`，采集主入口 `main.py --help` 可运行 |
| 去重回归 | 4 passed |
| Git 排除检查 | `.venv/pyvenv.cfg`、data 内 JSONL 均被忽略 |

关键版本：Python 3.12.14、pip 25.0.1、FastAPI 0.110.2、Uvicorn 0.29.0、httpx 0.28.1、Pydantic 2.14.2、Playwright 1.64.1、pandas 2.2.3、pytest 9.2.0。使用 requirements.txt 的可用安装方案，本次未验证 uv 锁文件安装。

pytest-asyncio 提示未设置默认 fixture loop scope，是非阻断弃用警告，4 项同步回归测试通过。本次未安装 Playwright 浏览器，也未测试社交登录、浏览器采集、页面交互或模型服务；GitHub 公开 API 采集不需要浏览器。HTTP 首页检查只能确认附带前端文件可返回，不能替代完整界面验收。
