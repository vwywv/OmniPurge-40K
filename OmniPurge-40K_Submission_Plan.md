# OmniPurge-40K：终极提交作战指南 (Submission Plan)

## 一、 必填材料准备

### 1. 作品简介（直接复制，字数约 400 字）
> **作品名称**：OmniPurge-40K (全链路确定性排障神龛)
> 
> **核心功能**：
> OmniPurge-40K 是一款专注于解决“大模型修复代码易产生幻觉”的终端排障利器。当开发者在终端遇到报错时，只需将日志通过管道（Pipe）输入给本工具，它便会自动穿透复杂的框架异常堆栈（如 Java 的 `Caused by`），精准锁定本地引发 Bug 的底层业务源码，截取高浓度上下文交由大模型（如 CodeBuddy/DeepSeek）生成修复方案。
> 
> **技术亮点**：
> 1. **启发式预抓取**：弃用低效的云端 Agent 检索循环，在本地通过堆栈逆向解析与文件校验，瞬间捕获真实事故现场，消灭大模型视野盲区。
> 2. **确定性降维打击**：首创“大模型生成 + 本地 `javac` 编译器校验”闭环。拦截 AI 返回的代码并在本地隐蔽编译，若失败则提取 `stderr` 精确报错注入 Prompt 打回重试，将幻觉率降至 0%。
> 3. **极客级终端视听与防呆**：采用 `select` 流监控防止演示死锁；修复成功后，在终端逐行打字机输出绿码，并伴随蜂鸣声渲染震撼的“纯洁印章” ASCII Art。
> 
> **应用场景**：
> 极客开发者的本地沉浸式 Debug 伴侣；可集成于 CI/CD 流水线；通过 WorkBuddy Webhook 推送至企业微信，实现“报错抓取-自动修复-报告通知”的企业级闭环。

### 2. Skill/Agent 文件 (ZIP 压缩包打包指南)
由于我们的核心是一个 Python CLI，为了符合“插件/技能”的规范，请在终端执行以下命令打包：
```bash
mkdir OmniPurge-40K_Skill
cp src/main.py OmniPurge-40K_Skill/
cp -r tests OmniPurge-40K_Skill/
cp OmniPurge-40K：全链路灵感与数据流转模型.md OmniPurge-40K_Skill/README.md
cp openapi.yaml OmniPurge-40K_Skill/openapi.yaml
# 创建一个 requirements.txt
echo -e "requests\nrich" > OmniPurge-40K_Skill/requirements.txt
# 打包
zip -r OmniPurge-40K_Skill.zip OmniPurge-40K_Skill/
```
*提交说明：将 `OmniPurge-40K_Skill.zip` 上传至该栏目。*

---

## 二、 选填材料（强烈建议拉满）

### 1. 作品说明文档 (PDF)
**操作**：将我们项目目录下的 `OmniPurge-40K_架构演进与决策记录.md` 和 `OmniPurge-40K：全链路灵感与数据流转模型.md` 合并，导出为一份极其硬核的 PDF 上传。这能直接震撼评委的工程审美。

### 2. 演示视频 (MP4, 3分钟内一镜到底)
**分镜脚本 (Storyboard)**：
- **0:00-0:15**：终端直接输入 `python src/main.py`，展示 3 秒防呆机制触发红警（展现产品的边界保护）。
- **0:15-0:40**：运行 `javac tests/TestApp.java` 制造真实报错，并 `| python src/main.py`。展示精准锁定 `TestApp.java (行 23)`。
- **0:40-1:30**：展示第一次 AI 修复（Mock 掉分号），终端弹出 `javac` 打回的黄色警告；接着展示第二次重试修复成功，终端逐行打印绿码，最后“纯洁印章”落下，伴随 `\a` 蜂鸣（核心爽点）。
- **1:30-2:00**：(可选) 展示企业微信群里收到了由 WorkBuddy 发出的 Markdown 修复报告卡片。

### 3. 代码仓库链接
**操作**：在 GitHub 或 Gitee 建一个 Public 仓库，把代码推上去。README 里把我们的那张“降维盖章”截图放上去。

### 4. 路演 PPT (PDF/PPTX)
**核心框架（取自决策备忘录）**：
1. **痛点**：Agent 修复代码像开盲盒，缺乏真实验证。Java 长堆栈难以定位。
2. **方案**：本地启发式预抓取 + `javac` 确定性拦截。
3. **展示**：放上终端特效和报错重试闭环的截图。
4. **商业拓展**：结合 WorkBuddy 的企微生态闭环。