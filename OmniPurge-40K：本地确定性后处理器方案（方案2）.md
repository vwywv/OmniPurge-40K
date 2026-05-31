# OmniPurge-40K：方案 2 — 本地确定性后处理器（Local Static Post-Processor）

> 对应审查报告中的 🔴2 修复方案。用真实工具替代黑盒争议，让 Demo 从「黑盒互审」进化为「AI 生成 + 工具验证」的工业级可信管线。

---

## 一、现状痛点

原架构中 Agent B（审查器）是一个 LLM 节点，其判决逻辑：

```
ClawPro 工作流:
  Agent A (生成) → Agent B (LLM 审查) → 不合格则打回 A → 最多 3 次
```

三个不可控点：

1. **判决标准是语义化的**——「防空指针」在 LLM 看来是模糊指令，同一段代码换个措辞结果可能不同
2. **无法向评委展示「为什么通过」**——Agent B 说「已合格」是个黑盒结论，评委无法验证
3. **3 次循环是硬上限而非收敛条件**——可能 A/B 两 Agent 各执一词直到超限，Demo 当场崩溃

---

## 二、方案 2 核心架构

### 设计原则

> **「AI 负责创造力，确定性工具负责质检。」**

把 Agent B 的审查职责从云端 ClawPro 工作流中剥离，下沉到本地 CLI 层，用真实的静态分析工具替代 LLM 的主观判断。

### 新旧流程对比

```
旧流程 (纯双 Agent):
  CLI 发送堆栈+源码
      → ClawPro 工作流:
          Agent A(生成修复) → Agent B(LLM审查)
          ↳ 不合格 → 回 A 重做 (最多3次)
          ↳ 合格 → 返回 CLI
      → CLI 渲染输出

新流程 (方案2):
  CLI 发送堆栈+源码
      → ClawPro 工作流:
          Agent A(生成修复)
      → CLI 收到修复代码
      → 本地静态分析 (pylint/bandit/正则)
          ↳ 不合格 → 带着具体错误信息重新调 Agent A (最多3次)
          ↳ 合格 → 渲染输出
```

### 核心改动点

| 项目 | 原架构 | 方案 2 |
|------|--------|--------|
| 审查方 | ClawPro 云端 Agent B (LLM) | **本地 CLI + 确定性工具** |
| 判决依据 | Prompt 语义 → 概率输出 | **pylint 错误码 / bandit 警告 / 正则匹配** |
| 重试触发 | Agent B 返回 JSON 中的 `passed: false` | **本地 subprocess 退出码 / JSON 解析结果** |
| 重试上下文 | Agent B 的模糊评语 | **行号 + 错误码 + 具体消息（如 `E0602: undefined variable 'x' at line 42`）** |
| 可视化 | 无（云端黑盒） | **终端可打印「⛏ pylint 发现 3 个错误，正在重新锻造...」** |
| ClawPro 依赖 | 依赖双 Agent 工作流 | **只需要 Agent A（单节点），大幅降低工作流配置复杂度** |

---

## 三、详细模块设计

### 3.1 模块调用链

```
┌─────────────────────────────────────────────┐
│  CLI Main Loop                               │
│                                              │
│  for attempt in range(MAX_RETRIES):          │
│      code = call_agent_a(prompt, context)     │
│      errors = run_static_analysis(code, lang) │
│                                              │
│      if not errors:                           │
│          render_success(code)  ← 渲染输出     │
│          break                                │
│      else:                                    │
│          show_review_feedback(errors)         │
│          prompt = enrich_prompt(errors)       │
│  else:                                        │
│      render_fallback(code)  ← 3次均失败降级   │
└─────────────────────────────────────────────┘
```

### 3.2 模块职责

#### `run_static_analysis(code: str, language: str) -> list[AnalysisError]`

根据语言类型分发到不同的分析器：

```
language="python"  →  pylint (首选) + bandit (安全扫描)
language="java"    →  grep 式正则 (无 JDK 依赖) 或 接口预留
language="go"      →  go vet 接口预留 (需 Go 环境)
language="rust"    →  clippy 接口预留
language="unknown" →  通用正则回退
```

**返回结构**：

```python
@dataclass
class AnalysisError:
    line: int          # 错误行号
    column: int        # (可选) 列号
    severity: str      # "error" | "warning" | "convention"
    code: str          # 错误码, e.g. "E0602"
    message: str       # 可读描述
```

**严重级别过滤规则**：只有 `severity == "error"` 才触发重试。`warning` 和 `convention` 级别只打印提示，不阻断流程。

#### `enrich_prompt(original_prompt: str, errors: list[AnalysisError]) -> str`

将静态分析结果注入到重试 Prompt 中：

```
原始 Prompt:
「根据以下堆栈和上下文修复 Java NullPointerException...」

重试 Prompt:
「根据以下堆栈和上下文修复 Java NullPointerException...
⚠️ 注意：你上一次生成的代码未通过 pylint 静态检查，具体问题如下：
  行 42, E0602: undefined variable 'config'
  行 58, W0611: unused import 'os'
请修正上述问题后重新生成完整代码。」
```

**关键设计**：注入的是**结构化、确定性**的错误信息，而非 Agent B 的模糊评语。Agent A 拿到错误行号和具体描述后，定位和修复效率远高于「这段代码可能有空指针风险」之类的模糊反馈。

### 3.3 pylint 输出解析

Pylint 输出格式为 JSON（需传入 `--output-format=json`），解析逻辑：

```python
import subprocess, json, tempfile

def run_pylint(code: str) -> list[AnalysisError] | None:
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(code)
        f.flush()
        result = subprocess.run(
            ["python3", "-m", "pylint", f.name, "--output-format=json"],
            capture_output=True, text=True, timeout=30
        )
        # pylint 即使发现错误 exit code 也是非零，但 stdout 有 JSON
        if result.stdout:
            issues = json.loads(result.stdout)
        else:
            return []
        return [
            AnalysisError(
                line=issue["line"],
                column=issue.get("column", 0),
                severity="error" if issue["type"] in ("error", "fatal") else "warning",
                code=issue["symbol"],
                message=issue["message"]
            )
            for issue in issues
        ]
```

### 3.4 回退正则引擎（无 pylint 环境兜底）

当目标语言无可用静态分析工具时，降级为模式匹配：

```python
FALLBACK_PATTERNS = {
    "python": [
        (r'open\([^)]+\)(?!\s*\n\s*.*close)', "可能未关闭的文件句柄"),
        (r'except\s*:\s*(?!\s*raise|\s*pass)', "裸 except 应指定异常类型"),
        (r'(?<!def )\w+\s*=\s*\{\}', "可变默认参数风险"),
    ],
    "java": [
        (r'catch\s*\(\s*Exception\s+\w+\s*\)\s*\{[^}]*\}', "空 catch 块"),
        (r'new\s+Thread\(', "直接创建 Thread，建议使用线程池"),
    ],
    "generic": [
        (r'(?<!""")\bpassword\s*=\s*["\'][^"\']+["\']', "代码中硬编码密码"),
        (r'(?<!//)\bapi[_-]?key\b\s*=\s*["\'][^"\']+["\']', "代码中硬编码 API Key"),
    ]
}
```

通过 `re.findall` 扫描修复后的代码，匹配则生成对应的 `AnalysisError`。

---

## 四、状态机：重试控制逻辑

```
                    ┌──────────────┐
                    │  收到修复代码  │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │  静态分析判断   │  ← 运行 pylint/bandit/正则
                    └──────┬───────┘
                           │
               ┌───────────┴───────────┐
               ▼                       ▼
        ┌──────────────┐      ┌──────────────────┐
        │  无错误       │      │  有错误 (仅error)  │
        └──────┬───────┘      └────────┬─────────┘
               │                       │
               ▼                       ▼
        ┌──────────────┐      ┌──────────────────┐
        │  渲染成功输出   │      │  attempts < 3 ?   │
        │  (绿色 + 印章)  │      └────────┬─────────┘
        └──────────────┘         ┌───────┴────────┐
                                 ▼                ▼
                          ┌──────────────┐   ┌──────────────┐
                          │  是: 重试      │   │ 否: 降级输出   │
                          │  注入错误信息   │   │ (黄色警告+    │
                          │  重新调 Agent A│   │  but 展示代码) │
                          └──────────────┘   └──────────────┘
```

### 重试次数的可视化反馈

每一次重试都在终端输出进度，让 Demo 观众看到「机器在自我修正」：

```
■ 第 1 次锻造完成... [机魂扫描中]
  ⛏ pylint 发现 2 个 ERROR (E0602, W0611) — 机魂不悦，重新锻造
  ──────────────────────────────────────────────

■ 第 2 次锻造完成... [机魂扫描中]
  ⛏ pylint 发现 1 个 ERROR (E0602) — 接近纯净，再锻一次
  ──────────────────────────────────────────────

■ 第 3 次锻造完成... [机魂扫描中]
  ✓ pylint 扫描通过 — 代码纯净，机魂喜悦！
  ──────────────────────────────────────────────
```

**如果 3 次均失败：**

```
  ⚠ 经过 3 次锻造，静态分析仍发现 1 个 ERROR (E0602)
  ⚠ 进入降级模式：展示当前最佳修复结果
  ⚠ 你可以在本地手动调整后重新运行 omnipurge
```

---

## 五、边界情况处理

| 场景 | 处理方式 |
|------|---------|
| 本地未安装 pylint | 自动检测 → 打印提示 → 降级到正则回退引擎 |
| pylint 运行超时（>30s） | `subprocess.TimeoutExpired` → 视为「不可用」，降级正则 |
| 修复后代码语法错误 | pylint 会报 `E0001`（syntax-error），计入重试逻辑 |
| 第一次生成的代码就 100% 通过 | 重试循环 0 次触发，零额外延迟 |
| 3 次后仍有错误但错误不同 | 展示最后一次的错误给用户，输出最佳结果 |
| 跨语言场景（Java/Go 无 CLI） | 走正则回退，准确率降低但流程不断 |

---

## 六、与 ClawPro 工作流的协作关系

方案 2 的一个隐含优势：**它降低了 ClawPro 工作流的配置复杂度**。

```
原 ClawPro 工作流需要:
  [开始] → [LLM: Agent A] → [LLM: Agent B] → [条件分支: 通过/重试] → [结束]
  节点数: 4个, 需要配置: 2个LLM节点 + 1个条件节点 + 循环连接

使用方案 2 后 ClawPro 工作流只需要:
  [开始] → [LLM: Agent A] → [结束]
  节点数: 2个, 需要配置: 1个LLM节点
```

重试逻辑完全由本地 CLI 驱动——CLI 收到 Agent A 的返回 → 跑静态分析 → 决定是否再次调用 Agent A 的 API。这意味着：

1. **ClawPro 工作流需要暴露单次 Agent A 的 API 端点**（而非完整工作流入口）
2. **CLI 需要管理 API 调用的幂等性和请求 ID**（同一错误重试时携带上下文）

如果你用的是 Mock API 进行开发测试，方案 2 甚至不需要修改 Mock 端的逻辑——Mock 只需要生成随机修复代码，CLI 端自己跑 pylint 验证。

---

## 七、实现路线图（4h 冲刺）

| 步骤 | 内容 | 产出 | 工时 |
|------|------|------|------|
| **Step 1** | 实现 `run_static_analysis()` — 先只支持 Python(pylint+bandit) 和正则回退 | 核心分析函数 | 1.5h |
| **Step 2** | 实现 `enrich_prompt()` — 将 `list[AnalysisError]` 注入重试 Prompt | Prompt 增强函数 | 0.5h |
| **Step 3** | 改造 CLI 主循环 — 将等待 Agent B 替换为重试 for 循环 | 主流程改造 | 1.5h |
| **Step 4** | 终端反馈渲染 — 格式化输出「每一次重试的错误详情+重试进度」 | 可视化 | 0.5h |
| **Step 5** | 测试验证 — 构造坏代码/好代码两个测试用例验证重试逻辑 | 测试通过 | 0.5h |

### 第一步代码骨架（直接可用的起点）

```python
import subprocess
import tempfile
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

@dataclass
class AnalysisError:
    line: int
    column: int = 0
    severity: str = "error"  # "error" | "warning" | "convention"
    code: str = ""
    message: str = ""

MAX_RETRIES = 3

def run_static_analysis(code: str, language: str = "python") -> list[AnalysisError]:
    """主入口：根据语言分发到对应的分析器"""
    if language == "python":
        errors = run_pylint(code)
        if errors is not None:
            return [e for e in errors if e.severity == "error"]
        # pylint 不可用，降级正则
        errors = run_fallback_regex(code, "python")
        return [e for e in errors if e.severity == "error"]
    else:
        # 未知语言走通用正则回退
        return [e for e in run_fallback_regex(code, language)
                if e.severity == "error"]

def run_pylint(code: str) -> Optional[list[AnalysisError]]:
    """调用 pylint --output-format=json，返回 None 表示 pylint 不可用"""
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py',
                                         delete=False) as f:
            f.write(code)
            tmp_path = f.name
        result = subprocess.run(
            ["python3", "-m", "pylint", tmp_path, "--output-format=json"],
            capture_output=True, text=True, timeout=30
        )
        Path(tmp_path).unlink(missing_ok=True)
        if not result.stdout:
            return []
        issues = json.loads(result.stdout)
        SEVERITY_MAP = {
            "fatal": "error", "error": "error",
            "warning": "warning", "convention": "convention",
            "refactor": "convention"
        }
        return [
            AnalysisError(
                line=issue["line"],
                column=issue.get("column", 0),
                severity=SEVERITY_MAP.get(issue["type"], "warning"),
                code=issue["symbol"],
                message=issue["message"]
            )
            for issue in issues
        ]
    except (FileNotFoundError, subprocess.TimeoutExpired,
            json.JSONDecodeError, PermissionError):
        return None  # pylint 不可用，触发降级

FALLBACK_PATTERNS = {
    "python": [
        (r'(\s*)except\s*:\s*\n\s*pass', "裸 except: pass 会静默所有异常"),
        (r'open\([^)]+\)(?!\s*\.close\b)', "文件打开后未显式调用 .close()"),
    ],
}

def run_fallback_regex(code: str, language: str) -> list[AnalysisError]:
    """正则降级检测"""
    errors = []
    patterns = FALLBACK_PATTERNS.get(language, [])
    patterns += FALLBACK_PATTERNS.get("generic", [])
    lines = code.split('\n')
    for pattern, msg in patterns:
        for i, line in enumerate(lines, 1):
            if re.search(pattern, line):
                errors.append(AnalysisError(
                    line=i,
                    severity="error",
                    code="fallback-pattern",
                    message=msg
                ))
    return errors
```

---

## 八、Demo 叙事建议

方案 2 的天然优势是可以编排出一条精彩的 Demo 叙事链：

### 3 分钟 Demo 脚本

| 时间 | 画面 | 旁白 |
|------|------|------|
| 0:00-0:20 | `cat error.log \| omnipurge` 运行 | 「一条命令，触发 OmniPurge 修复管线」 |
| 0:20-0:40 | 终端显示「第 1 次锻造...」→ pylint 发现错误 →「机魂不悦，重锻」 | 「AI 生成了修复代码，但本地的 pylint 机械神官发现了 2 个隐藏错误——未使用的变量和未关闭的文件句柄」 |
| 0:40-0:55 | 第二次锻造、第三次锻造的动态显示 | 「AI 收到了精确的错误坐标，正在针对性调整...」 |
| 0:55-1:10 | 「✓ pylint 扫描通过 — 代码纯净」+ 绿字输出 | 「第三次锻造通过了一切质检。注意：这不是 AI 说它自己通过了，而是真实的 pylint 工具给出的认证」 |
| 1:10-1:30 | 纯洁印章 ASCII 落下 | 「代码已安抚机魂」 |
| 1:30-2:00 | 展示原始错误代码 vs 最终修复代码的 diff | 「左边是有 Bug 的代码，右边是 OmniPurge 自动修复后并通过静态度量的代码」 |
| 2:00-2:30 | 快速展示 ClawPro 工作流截图（只有 Agent A 一个节点）| 「因为审查逻辑是我们本地做的，ClawPro 云端的配置极其简单——我们只用了单 Agent 节点」 |
| 2:30-3:00 | 收尾 + Q&A 引导 | 「源码已开源，静态分析器是标准工具——任何人都可以复现这个验证过程」 |

### 关键叙事武器

> **「我们的 AI 不做虚假承诺。它生成的每一行代码都要经过 pylint 这把尺子的丈量才能呈现在你面前。」**

这句话在现场 Demo 的杀伤力极大——因为其他团队展示 AI 修复时只能「说它修好了」，你的团队可以「证明它修好了」。

---

## 九、风险与缓解

| 风险 | 概率 | 缓解措施 |
|------|------|---------|
| Demo 环境未装 pylint | 中 | 安装脚本 `pip install pylint bandit` 写在 README 第一步 + 正则回退兜底 |
| pylint 对动态代码生成误报率高 | 中 | 只拦截 ERROR/FATAL 级别，WARNING/CONVENTION 放行 |
| Agent A 返回的代码缩进被破坏 | 低 | 重试时在 Prompt 中强调「保持原缩进风格」|
| 正则回退准确率低 | 高（无 pylint 时） | 可接受——降级模式的定位本来就是「总比没有好」 |
| 3 次重试后仍有 ERROR | 低 | 展示最佳结果 + 黄色警告，流程不崩溃 |

---

*「真理由 pylint 的 JSON 输出中浮现，而非大模型的概率云中。本地铸铁，万机垂青。」*