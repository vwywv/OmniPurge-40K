import sys
import select
import warnings
warnings.filterwarnings("ignore") # 屏蔽 urllib3 等底层环境警告，保证终端纯净
import re
import os
import tempfile
import requests
import json
import subprocess
from pathlib import Path
import argparse
from rich.console import Console
import time

console = Console()

def check_stdin_timeout(timeout=3.0):
    """防呆机制：利用 select 监听标准输入管道超时 (macOS/Unix 专属)"""
    if os.name == 'nt':
        return # Windows 平台 select 不支持 stdin，降级跳过
        
    rlist, _, _ = select.select([sys.stdin], [], [], timeout)
    if not rlist:
        console.print("[bold red]❌ [警告] 亚空间链路未激活！未检测到管道输入流。[/bold red]")
        console.print("[yellow]用法示例: cat error.log | python src/main.py[/yellow]")
        sys.exit(1)

def find_file_in_dir(filename, root_dir='.', max_depth=3):
    """启发式文件存在性探测 (限制深度以避免全局扫描卡顿)"""
    root_path = Path(root_dir).resolve()
    for dirpath, dirnames, files in os.walk(root_path):
        # 计算当前深度
        current_depth = len(Path(dirpath).relative_to(root_path).parts)
        if current_depth > max_depth:
            del dirnames[:]  # 停止向下递归
            continue
        
        if filename in files:
            return os.path.join(dirpath, filename)
    return None

def extract_stacktrace(log_text):
    """精准锁定真正的业务 Bug 现场：支持 Runtime 异常和 Javac 编译报错"""
    # 1. 尝试匹配 Java Runtime 堆栈: at com.example.Class.method(Filename.java:123)
    runtime_pattern = re.compile(r'at\s+[\w\.\$]+\(([\w]+\.java):(\d+)\)')
    
    # 2. 尝试匹配 javac 编译报错: File.java:123: error: ...
    javac_pattern = re.compile(r'([\w]+\.java):(\d+):')

    # 优先检测是不是编译报错
    for line in log_text.strip().split('\n'):
        match = javac_pattern.search(line)
        if match:
            filename = match.group(1)
            lineno = int(match.group(2))
            actual_file_path = find_file_in_dir(filename)
            if actual_file_path:
                return actual_file_path, lineno

    # 按 Caused by: 切分异常链，从最深层的根因开始找 (针对 Runtime)
    blocks = re.split(r'Caused by:', log_text)
    for block in reversed(blocks):
        # 在每个异常块内部，必须自顶向下（Top-down）找
        for line in block.strip().split('\n'):
            match = runtime_pattern.search(line)
            if match:
                filename = match.group(1)
                lineno = int(match.group(2))
                actual_file_path = find_file_in_dir(filename)
                if actual_file_path:
                    return actual_file_path, lineno
                
    return None, None

def get_context(filepath, lineno, context_lines=20):
    """提取报错行前后高浓度上下文"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        start = max(0, lineno - 1 - context_lines)
        end = min(len(lines), lineno + context_lines)
        return "".join(lines[start:end])
    except Exception as e:
        console.print(f"[bold red]❌ 无法读取源文件: {e}[/bold red]")
        return None

def call_ai_agent(prompt, is_mock=False, attempt=1):
    """模拟调用 ClawPro/CodeBuddy 节点"""
    console.print(f"\n[bold blue]>> 正在请求云端机魂 (Agent A) 下发净化指令... (尝试 {attempt}/3)[/bold blue]")
    if is_mock:
        time.sleep(1) # 模拟网络延迟
        if attempt == 1:
            # 第一次故意返回有语法错误的代码，触发 javac 审判打回
            return """public class TestApp {
    public static void main(String[] args) { frameworkInvoke(); }
    public static void frameworkInvoke() { businessLogic(); }
    public static void businessLogic() {
        String data = "secret";
        // 故意漏掉分号，触发本地静态拦截
        if (data.equals("secret")) { System.out.println("Access Granted") }
    }
}"""
        else:
            # 第二次修复成功
            return """public class TestApp {
    public static void main(String[] args) { frameworkInvoke(); }
    public static void frameworkInvoke() { businessLogic(); }
    public static void businessLogic() {
        String data = "secret";
        if (data != null && data.equals("secret")) {
            System.out.println("Access Granted");
        }
    }
}"""

    # --- 真实 API 请求逻辑 ---
    # 通过环境变量选择 API 提供商，默认直连 DEEPSEEK 机魂
    api_provider = os.environ.get("OMNIPURGE_LLM_PROVIDER", "DEEPSEEK").upper()
    
    headers = {"Content-Type": "application/json"}
    api_url = None
    
    # 组装强硬的 System Prompt (对 Gemini 以外的通用格式)
    system_prompt = (
        "你是一个极其资深的 Java 技术神甫（高级工程师）。"
        "你的唯一任务是修复用户提供的包含 Bug 的 Java 代码。"
        "请严格遵循以下规则：\n"
        "1. 只输出修复后的 Java 代码，必须用 ```java 和 ``` 包裹。\n"
        "2. 保持原有的类名和方法名不变。\n"
        "3. 绝对不要输出任何解释、问候或 markdown 以外的文本。"
    )
    
    payload = { # 通用 payload 结构，会被特定供应商覆盖
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2
    }

    if api_provider == "CLAWPRO":
        api_url = os.environ.get("CLAWPRO_API_URL", "https://api.clawpro.example.com/v1/chat/completions")
        api_key = os.environ.get("CLAWPRO_API_KEY")
        if not api_key:
            console.print("\n[bold red]❌ CLAWPRO 供应商未配置 CLAWPRO_API_KEY 环境变量！[/bold red]")
            console.print("[yellow]请在终端执行: export CLAWPRO_API_KEY='你的比赛专属秘钥'[/yellow]")
            sys.exit(1)
        headers["Authorization"] = f"Bearer {api_key}"
        payload["model"] = os.environ.get("CLAWPRO_MODEL", "codebuddy-pro-latest")
    elif api_provider == "OPENAI":
        api_url = os.environ.get("OPENAI_API_URL", "https://api.openai.com/v1/chat/completions")
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            console.print("\n[bold red]❌ OPENAI 供应商未配置 OPENAI_API_KEY 环境变量！[/bold red]")
            console.print("[yellow]请在终端执行: export OPENAI_API_KEY='你的 OpenAI API 秘钥'[/yellow]")
            sys.exit(1)
        headers["Authorization"] = f"Bearer {api_key}"
        payload["model"] = os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo") # 或 gpt-4
    elif api_provider == "GEMINI":
        api_url = os.environ.get("GEMINI_API_URL", "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent")
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            console.print("\n[bold red]❌ GEMINI 供应商未配置 GEMINI_API_KEY 环境变量！[/bold red]")
            console.print("[yellow]请在终端执行: export GEMINI_API_KEY='你的 Gemini API 秘钥'[/yellow]")
            sys.exit(1)
        api_url = f"{api_url}?key={api_key}" # Gemini API key 通常作为 URL 参数，而非 Authorization Header
        payload = { # Gemini 的 payload 结构略有不同
            "contents": [{"role": "user", "parts": [{"text": system_prompt + "\n" + prompt}]}],
            "generationConfig": {"temperature": 0.2}
        }
    elif api_provider == "XIAOMI": # 基于你提供的环境配置进行适配
        api_url = os.environ.get("ANTHROPIC_BASE_URL", "https://token-plan-cn.xiaomimimo.com/anthropic") # 使用 ANTHROPIC_BASE_URL 作为 Xiaomi API URL
        api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN") # 使用 ANTHROPIC_AUTH_TOKEN 作为 Xiaomi API Key
        if not api_key:
            console.print("\n[bold red]❌ XIAOMI 供应商未配置 ANTHROPIC_AUTH_TOKEN 环境变量！[/bold red]")
            console.print("[yellow]请在终端执行: export ANTHROPIC_AUTH_TOKEN='你的 Xiaomi API 秘钥'[/yellow]")
            sys.exit(1)
        headers["x-auth-token"] = api_key # Xiaomi (Anthropic API) 使用 x-auth-token 作为认证头
        payload["model"] = os.environ.get("ANTHROPIC_MODEL", "mimo-v2.5-pro") # 使用 ANTHROPIC_MODEL
        # Anthropic API 通常使用 messages 结构，与 OpenAI 类似
    elif api_provider == "DEEPSEEK": # 假设 DeepSeek API 结构与 OpenAI 类似
        api_url = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions") # DeepSeek 官方 API
        api_key = os.environ.get("DEEPSEEK_API_KEY") # 从环境变量获取
        if not api_key:
            console.print("\n[bold red]❌ DEEPSEEK 供应商未配置 DEEPSEEK_API_KEY 环境变量！[/bold red]")
            console.print("[yellow]请在终端执行: export DEEPSEEK_API_KEY='你的 DeepSeek API 秘钥'[/yellow]")
            sys.exit(1)
        headers["Authorization"] = f"Bearer {api_key}"
        payload["model"] = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash") # DeepSeek 官方主力代码模型 (如果需要覆盖，可设置 DEEPSEEK_MODEL)
    else:
        console.print(f"[bold red]❌ 未知的 LLM 提供商: {api_provider}[/bold red]")
        sys.exit(1)
    
    # 对 Gemini 以外的供应商，system_prompt 是 payload["messages"][0]["content"]
    # 如果当前供应商不是 Gemini，需要确保 system_prompt 被设置到 payload 中
    if api_provider != "GEMINI":
        payload["messages"][0]["content"] = system_prompt
    
    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        reply_text = ""
        if api_provider == "GEMINI":
            # Gemini 的响应体格式不同
            reply_text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        elif api_provider == "XIAOMI": # Xiaomi (Anthropic API) 响应结构与 OpenAI 类似
            reply_text = data.get("content", [{}])[0].get("text", "") # Anthropic API 返回内容在 content 数组中
        elif api_provider in ["CLAWPRO", "OPENAI", "DEEPSEEK"]:
            # OpenAI/ClawPro/DeepSeek 等通用格式 (假设它们返回结构类似)
            reply_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        else:
            console.print(f"[bold red]❌ 未知 LLM 提供商 {api_provider} 的响应解析逻辑[/bold red]")
            sys.exit(1)
        
        # 利用正则剥离 markdown 代码块包裹，只保留纯净的 Java 代码
        code_match = re.search(r'```(?:java)?\s*(.*?)\s*```', reply_text, re.DOTALL)
        if code_match:
            return code_match.group(1).strip()
        return reply_text.strip()
        
    except Exception as e:
        console.print(f"[bold red]❌ 云端机魂连接断开 (API 请求失败): {e}[/bold red]")
        sys.exit(1)

def extract_classname(code):
    match = re.search(r'(?:public\s+)?class\s+(\w+)', code)
    return match.group(1) if match else "Target"

def run_local_judgement(code):
    """本地 javac 降维打击"""
    classname = extract_classname(code)
    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, f"{classname}.java")
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(code)
        
    console.print(f"[dim]>> 本地审判庭已接管，隐蔽触发 javac {classname}.java ...[/dim]")
    result = subprocess.run(["javac", file_path], capture_output=True, text=True)
    return result.returncode == 0, result.stderr

def notify_workbuddy(title, stacktrace, fixed_code):
    """
    将修复结果推送至企业微信。
    支持两种模式：
    1. Webhook 模式 (环境变量: WORKBUDDY_WEBHOOK_URL)
    2. API 模式 (环境变量: WECOM_CORP_ID, WORKBUDDY_BOT_ID, WORKBUDDY_SECRET)
    """
    webhook_url = os.environ.get("WORKBUDDY_WEBHOOK_URL")
    corp_id = os.environ.get("WECOM_CORP_ID")
    bot_id = os.environ.get("WORKBUDDY_BOT_ID")
    secret = os.environ.get("WORKBUDDY_SECRET")

    if not (webhook_url or (corp_id and bot_id and secret)):
        console.print("[yellow]未配置通知凭据（Webhook 或 CorpID/BotID/Secret），跳过推送。[/yellow]")
        return

    console.print(f"\n[bold cyan]>> 正在推送净化报告至企业矩阵...[/bold cyan]")

    # 构建 Markdown 内容
    message_content = f"### {title}\n" \
                      f"**检测到亚空间逻辑污染并已成功净化。**\n\n" \
                      f"**原始堆栈摘要:**\n" \
                      f"```\n{stacktrace[:500]}...\n```\n\n" \
                      f"**修复后代码:**\n" \
                      f"```java\n{fixed_code}\n```"

    try:
        if webhook_url:
            # 模式 B: 标准 Webhook 模式 (优先使用，最稳定)
            payload = {
                "msgtype": "markdown",
                "markdown": {"content": message_content}
            }
            response = requests.post(webhook_url, json=payload, timeout=10)
        elif corp_id and bot_id and secret:
            # 模式 A: API 模式 (针对企业微信智能机器人/自建应用)
            # 1. 使用企业 CorpID + 应用 Secret 获取 Access Token
            token_url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={corp_id}&corpsecret={secret}"
            token_res = requests.get(token_url, timeout=10).json()
            token = token_res.get("access_token")
            
            if not token:
                console.print(f"[bold red]❌ 无法获取推送授权: {token_res.get('errmsg', '未知错误')}[/bold red]")
                return

            # 2. 发送消息
            send_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
            payload = {
                "touser": "@all",
                "msgtype": "markdown",
                "agentid": bot_id, 
                "markdown": {"content": message_content},
                "safe": 0
            }
            response = requests.post(send_url, json=payload, timeout=10)

        response.raise_for_status()
        res_data = response.json()
        if res_data.get("errcode", 0) == 0:
            console.print("[green]✓ 净化报告已成功送达。[/green]")
        else:
            console.print(f"[bold red]❌ 推送失败: {res_data.get('errmsg')}[/bold red]")

    except Exception as e:
        console.print(f"[bold red]❌ 通讯链路故障: {e}[/bold red]")

def main():
    parser = argparse.ArgumentParser(description="OmniPurge-40K 本地确定性排障神龛")
    parser.add_argument("--mock", action="store_true", help="使用离线 Mock 模式调试")
    parser.add_argument("--notify-workbuddy", action="store_true", help="修复成功后通过 Webhook 推送至 WorkBuddy")
    args = parser.parse_args()

    check_stdin_timeout()
    raw_log = sys.stdin.read()
    
    # 保留原始日志，打印闪烁红警
    print(raw_log, end="")
    console.print("\n[bold red blink]*[警告] 检测到亚空间逻辑污染，开始净化...*[/bold red blink]")

    target_file, target_line = extract_stacktrace(raw_log)
    if not target_file:
        console.print("[bold red]❌ 无法定位到当前目录下的 Java 业务源码！[/bold red]")
        sys.exit(1)
        
    console.print(f"[green]✓ 锁定物理坐标: {target_file} (行 {target_line})[/green]")
    context_code = get_context(target_file, target_line)
    if not context_code:
        sys.exit(1)
        
    # 2. 圣洁重构与 javac 审判循环
    max_retries = 3
    final_code = None
    success = False
    prompt = f"以下 Java 代码在第 {target_line} 行抛出异常。请修复：\n```java\n{context_code}\n```"

    for attempt in range(1, max_retries + 1):
        ai_code = call_ai_agent(prompt, is_mock=args.mock, attempt=attempt)
        final_code = ai_code
        
        is_clean, stderr = run_local_judgement(ai_code)
        if is_clean:
            success = True
            break
        else:
            console.print(f"[bold yellow]⚠ javac 审判未通过！捕获报错:[/bold yellow]\n{stderr.strip()}")
            prompt += f"\n\n[JAVAC_ERROR]: 代码编译失败:\n{stderr}\n请根据以上报错重新生成代码。"
            
    # 3. 降维盖章（终端特效渲染）
    if success:
        console.print("\n[bold green]=== 净化完成的完美代码 ===[/bold green]")
        for line in final_code.split('\n'):
            console.print(f"[bold green]{line}[/bold green]")
            time.sleep(0.02)
        console.print("\n[bold red]      ╭━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╮[/bold red]")
        console.print("[bold red]      ┃  [ 纯 洁 印 章 | PURITY SEAL ]  ┃[/bold red]")
        console.print("[bold red]      ╰━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━╯[/bold red]")
        console.print("[bold red]              ┃ ▓▓▓▓▓▓▓▓▓▓▓ ┃[/bold red]")
        console.print("[bold red]              ┃ ▓▓▓▓▓▓▓▓▓▓▓ ┃[/bold red]")
        console.print("[bold red]                ▀▀▀▀   ▀▀▀▀  [/bold red]")
        console.print("[bold red blink]>> 万机神眷顾此行，亚空间 Bug 已被彻底净化！ <<[/bold red blink]")
        print("[ALERT]\a")

        if args.notify_workbuddy:
            notify_workbuddy(
                title="✅ OmniPurge 净化成功",
                stacktrace=raw_log,
                fixed_code=final_code)
    else:
        console.print("\n[bold yellow]⚠ 极限降级：3次重试均失败，展示最终版代码供手动调整：[/bold yellow]")
        print(final_code)

if __name__ == "__main__":
    main()