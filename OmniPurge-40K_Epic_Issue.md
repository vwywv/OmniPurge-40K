# [Epic] OmniPurge-40K MVP 核心链路铸造 (macOS 专属限定版)

## Background / Context
为应对黑客松 48 小时极限开发，并针对 macOS 演示终端进行视听与底层的深度适配，我们需要落地 OmniPurge-40K 的 MVP（最小可行性产品）。
基于最新的《架构演进与核心决策备忘录》，本项目果断放弃了容易产生幻觉的“云端 Agent 循环”与“沉重的 Checkstyle JAR 包”，转而采用 **本地启发式预抓取** 与 **本地 `javac` 降维打击** 策略。

此外，为了防止 Hackathon 演示现场因紧张忘记输入管道符而导致程序死锁（冷场），需利用 macOS/Unix 完美支持的 `select` 模块为标准输入流加装防呆机制。最终通过 `rich` 库在终端渲染战锤风格的纯洁印章神龛。

## Acceptance Criteria
- [ ] **防呆与系统适配 (Poka-yoke)**: 在终端直接运行 `python src/main.py`（未挂载管道流）时，能在 3 秒内触发 `select` 超时，并优雅打印红色警告后退出，不发生进程挂起。
- [ ] **逆向寻根定位 (Heuristic Backtracking)**: 执行 `cat error.log | python src/main.py` 时，能成功通过正则提取 Java 堆栈。必须采用自底向上的顺序（适配 `Caused by`），结合限制深度的本地文件判定，过滤掉不存在的框架文件，精准定位根因业务源码。
- [ ] **增强上下文抓取**: 锁定业务源码后，能成功截取报错行前后各 20 行，并将其打包拼接成增强版 Context Window Payload。
- [ ] **确定性审判 (javac 降维打击)**: 拦截大模型返回的重构代码，正则提取类名确保与文件名一致并写入临时目录。隐蔽触发 `javac {ClassName}.java`。若编译失败，必须将 `stderr` 精确注入重试 Prompt 打回重试（最多 3 次）。
- [ ] **降级输出 (Fallback)**: 若 3 次 `javac` 均失败，程序不崩溃，打印黄色警告并输出最后一次生成的代码，供用户手动调整。
- [ ] **降维盖章终端特效**: 审判全绿通过后，保留堆栈日志并在底部打印闪烁红警。随后使用 `rich.console.Console` + `time.sleep()` 稳定逐行输出绿色完美代码，最后渲染血色“纯洁印章”，并在落地瞬间触发 `[ALERT]\a` 产生视听震颤。

## Implementation Plan

**1. 物理引擎与基建 (Setup)**
- 确认 macOS 系统下 `python3` (3.10+) 与 `javac` 环境可用。
- 执行依赖安装：`pip install requests rich`。
- 搭建基础目录骨架：创建 `src/main.py`（主控，内置 `--mock` 参数实现单文件断网调试）、`tests/TestApp.java`（制造嵌套异常报错的靶机代码）。

**2. 亵渎捕获与本地防呆 (Phase 1)**
- 在 `src/main.py` 中引入 `select` 与 `sys`，编写针对 `sys.stdin` 的 3 秒超时监控逻辑。
- 编写核心正则 `at\s+[\w\.]+\(([\w]+\.java):(\d+)\)`，并执行**自底向上**逆序遍历以锁定 `Caused by` 根因。
- 实现 `os.path.exists()` 结合限制层级（如扫描深度 3 级）的遍历函数，防止全局扫描拖慢 Demo。

**3. API 对接与本地审判庭 (Phase 2 & 3)**
- 在 `src/main.py` 编写循环结构（`for attempt in range(3):`）的 HTTP POST 请求。
- 接收到 AI 响应后，使用正则 `(public\s+)?class\s+(\w+)` 提取类名。为避免相对路径 CWD 漂移，将代码写入系统级临时目录 `tempfile.gettempdir()/{ClassName}.java`。
- 调用 `subprocess.run(["javac", "{TempDir}/{ClassName}.java"], capture_output=True, text=True)` 触发原生编译。
- 解析 `run.returncode`，非 0 则将 `run.stderr` 完整拼入下一轮 Prompt 发起请求。3次失败触发降级。

**4. 终端神龛渲染 (Phase 4)**
- 引入 `rich.console.Console`（摒弃 `rich.live` 以避免 macOS 终端时序刷新冲突）。
- 编排终端输出时间轴：
  1. 打印原始堆栈日志。
  2. Console 输出红色告警闪烁文本。
  3. Console 结合 `time.sleep` 打字机式逐行输出绿色代码。
  4. 红色纯洁印章 ASCII Art 逐行坠落。
  5. `print("[ALERT]\a")` 触发物理打击感。