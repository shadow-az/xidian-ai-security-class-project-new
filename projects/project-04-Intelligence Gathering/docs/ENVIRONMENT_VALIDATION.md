# 阶段 2：独立环境与启动验证（初版）

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
