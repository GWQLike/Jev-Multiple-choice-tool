# Jev Multiple Choice Tool

Windows 极简单选题答题工具：按下 **Alt+Q**，截图、识别题干和选项，通过 Jev 获取答案，再显示一个短暂的小弹窗。

```text
Alt+Q → 截图 → 本地 OCR → 解析 → Jev Choice → 答案弹窗
```

没有主窗口、设置页面或托盘菜单。OCR 模型和 HTTP Client 在启动时初始化并复用；一次只处理一道题。

## 功能

- 固定区域截图，或在鼠标所在显示器上手动框选。
- RapidOCR + ONNX Runtime 本地识别中英文，解析从 A 开始连续排列的 2～10 个选项。
- 支持 `A.`、`A、`、`A:`、`A：`、`(A)`、`（A）` 和选项跨行等常见格式。
- 置顶、无标题栏的结果弹窗，默认 1.5 秒后消失；低置信度时显示问号。
- 记录阶段耗时，遇到单次答题错误后继续等待快捷键。

## 快速开始

### 1. 安装

需要 **Windows、64 位 Python 3.12+**，并安装 Python 自带的 tkinter。建议使用 python.org 的完整安装包。

在 PowerShell 中执行：

```powershell
git clone https://github.com/GWQLike/Jev-Multiple-choice-tool.git
cd Jev-Multiple-choice-tool
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path config.json)) { Copy-Item config.example.json config.json }
```

如果已经下载或克隆项目，直接进入项目目录，从创建虚拟环境开始即可。

### 2. 配置截图区域

编辑 `config.json`。第一次使用建议将 `capture_mode` 改为 `"select"`，按快捷键后用鼠标框选**完整题干和全部选项**。

默认示例使用 `"fixed"`，会静默截取指定坐标，**不会显示框选提示**。使用固定模式前请调整 `capture_region`，使其覆盖题目。

### 3. 设置 Key 并运行

**当前版本使用 Vercel AI Gateway API，模型为 `typesafe-ai/jev`。** 请使用 Vercel AI Gateway 的 Key，环境变量名称为 `AI_GATEWAY_API_KEY`。

以下输入方式会隐藏密钥，也不会把密钥字面值写进 PowerShell 命令历史：

```powershell
$gatewayKey = Read-Host "Vercel AI Gateway API Key" -AsSecureString
$env:AI_GATEWAY_API_KEY = [System.Net.NetworkCredential]::new("", $gatewayKey).Password
Remove-Variable gatewayKey
.\.venv\Scripts\python.exe main.py
```

设置 Key 和启动程序必须在**同一个 PowerShell 窗口**完成。此设置仅影响当前窗口及其后续启动的子进程；关闭窗口后，下次需要重新设置。程序启动后修改环境变量，需要重启程序才会生效。

首次启动可能需要联网下载 OCR 模型到 `.models/`，请等终端出现 `Ready` 后再操作。后续启动复用本地模型；答题过程中不重复初始化 OCR。

### 4. 使用与退出

| 操作 | 默认快捷键 |
| --- | --- |
| 开始一次答题 | Alt+Q |
| 退出程序 | Alt+Shift+Q |
| 取消框选 | Esc 或鼠标右键 |
| 控制台中退出 | Ctrl+C |

退出组合键请先按 Alt 和 Shift，再按 Q。任务进行期间重复触发会被忽略。请只启动一个实例，避免多个程序同时响应快捷键。

在 `select` 模式下，按 Alt+Q 后会显示鼠标所在显示器的冻结画面，拖动框选，松开鼠标后开始识别。

成功时显示类似结果：

```text
        B
  98.2% · 278ms
```

这里的耗时仅为展示示例，实际速度取决于截图大小、OCR、网络和模型响应。confidence 低于阈值时显示 `B ?`。confidence 保留 API 返回值，可能与所选答案的 probability 不同。

确认运行正常后，可在已设置 Key 的 PowerShell 中改用无控制台方式：

```powershell
.\.venv\Scripts\pythonw.exe main.py
```

## 配置

`config.json` 始终从项目目录读取；文件不存在时使用代码默认值。修改后重启生效。

```json
{
  "hotkey": "<alt>+q",
  "exit_hotkey": "<alt>+<shift>+q",
  "capture_mode": "select",
  "capture_region": {
    "left": 300,
    "top": 200,
    "width": 1200,
    "height": 700
  },
  "popup_duration_ms": 1500,
  "confidence_warning_threshold": 0.8,
  "jev_timeout_seconds": 5,
  "jev_model": "typesafe-ai/jev",
  "debug": false
}
```

- `fixed`：使用 `capture_region`，坐标为虚拟桌面的物理像素，支持副屏负坐标。
- `select`：每次手动框选，忽略固定区域配置。
- `jev_timeout_seconds`：HTTPX 的连接、读、写及连接池各阶段超时，不是整个答题流程的总时限。
- `debug`：记录 OCR 行数和成功请求的 `capture_ms / ocr_ms / parse_ms / jev_ms / total_ms`。手动模式总耗时包含框选时间。

旧示例中的 `jev_model: "jev-latest"` 会自动转换为 `typesafe-ai/jev`。旧字段 `typesafe_api_key` 可保留为空；当前程序只从 `AI_GATEWAY_API_KEY` 读取凭据，不读取配置文件中的 Key，也不会自动加载 `.env`。

## API 提供商与切换

默认调用 Vercel 官方的 [TypeSafe 兼容接口](https://vercel.com/docs/ai-gateway/sdks-and-apis/typesafe)：

```text
POST https://ai-gateway.vercel.sh/typesafe/v1/systemone
模型：typesafe-ai/jev
环境变量：AI_GATEWAY_API_KEY
```

该接口使用 `state`、`questions` 和 Choice `criteria`，保留 `confidence` 与 `probabilities`。它属于结构化评估接口，不能按 OpenAI Chat Completions 的格式调用。

如需改用 [TypeSafe 官方直连 API](https://docs.typesafe.ai/api)，需要少量源码修改：

1. 在 `jev_client.py` 中将 `_ENDPOINT` 改为 `https://api.typesafe.ai/v1/systemone`。
2. 在 `jev_client.py` 和 `config.py` 中，将环境变量名 `AI_GATEWAY_API_KEY` 改为 `TYPESAFE_API_KEY`；将模型字符串 `typesafe-ai/jev` 统一改为 `jev-latest`，包括默认值、转换逻辑和校验。
3. 将本地 `config.json` 的 `jev_model` 改为 `jev-latest`，在同一 PowerShell 中设置 `TYPESAFE_API_KEY` 后重启；同步调整 API 测试中的地址、模型和环境变量断言。

两种服务的 Key 分别申请和使用。仅修改 `config.json` 无法完成切换；`Question`、`Answer` 及 Choice 解析接口可以保留。

## 故障排查

详细错误见 `logs/app.log`：

| 提示或现象 | 优先检查 |
| --- | --- |
| Alt+Q 没有框选界面 | 检查是否使用 `fixed`；切换为 `select` 后重启 |
| `CAPTURE ERROR` | 截图区域是否超出显示器范围 |
| `OCR ERROR` | 是否框选了可辨认的文字，而不是空白或其他窗口 |
| `PARSE ERROR` | 是否包含完整题干、连续的 A～J 标签及非空选项内容 |
| `API ERROR` | 查看日志区分 Key 缺失、HTTP 状态错误或响应无效；确认设置 Key 与启动在同一窗口 |
| `NETWORK ERROR` / `TIMEOUT` | 检查网络和服务可用性，必要时调高 `jev_timeout_seconds` |
| `INTERNAL ERROR` | 查看日志中的异常详情 |
| tkinter 初始化失败 | 检查 Python 安装是否包含完整 Tcl/Tk |

只检查环境变量是否存在，不显示密钥：

```powershell
if ([string]::IsNullOrWhiteSpace($env:AI_GATEWAY_API_KEY)) { "Key missing" } else { "Key configured" }
```

此检查只验证变量非空，不能证明 Key 有效。已经运行的程序不会自动读取其他窗口新设置的变量。

## 测试与 OCR 诊断

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

测试覆盖选项解析、配置、截图裁剪、OCR 行排列、流程控制和 HTTPX MockTransport 模拟请求；测试不会调用真实 Jev API。

对已有截图运行本地 OCR：

```powershell
.\.venv\Scripts\python.exe tools\diagnose.py .\.diagnostics\question.png
```

请先自行将诊断图片放到 `.diagnostics/`。该命令会在终端输出识别文字；它显示的 OCR 耗时包含本次引擎初始化，不能直接当作常驻程序的预热后耗时。

## 项目结构

```text
.
├── main.py                 # 生命周期与后台任务
├── capture.py              # MSS 截图与框选
├── ocr_engine.py           # OCR 初始化、预热、行排列
├── parser.py               # 单选题解析
├── jev_client.py           # Jev HTTP 协议适配
├── popup.py                # 结果与错误弹窗
├── config.py               # 配置与校验
├── models.py               # 数据结构和错误类型
├── hotkeys.py              # 快捷键状态
├── windows_utils.py        # DPI、显示器和窗口样式
├── logging_utils.py        # 日志轮转与脱敏
├── config.example.json
├── requirements.txt
├── requirements-dev.txt
├── tools/diagnose.py
└── tests/
```

## 当前范围

首版面向 Windows 的普通文字单选题，不处理图表语义、多选题或自动点击。结果仅供参考，confidence 不代表答案正确率。当前没有历史记录、数据库、浏览器插件、开机自启安装器或打包发布流程。
