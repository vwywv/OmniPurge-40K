import sys
import select
import re
import os
from pathlib import Path
import argparse
from rich.console import Console

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
    """精准锁定真正的业务 Bug 现场：根据 Caused by 分块，从最底层块内部自顶向下扫描"""
    # 正则匹配 Java 堆栈: at com.example.Class.method(Filename.java:123)
    pattern = re.compile(r'at\s+[\w\.\$]+\(([\w]+\.java):(\d+)\)')
    
    # 按 Caused by: 切分异常链，从最深层的根因开始找
    blocks = re.split(r'Caused by:', log_text)
    for block in reversed(blocks):
        # 在每个异常块内部，必须自顶向下（Top-down）找，因为块的顶部才是案发第一现场
        for line in block.strip().split('\n'):
            match = pattern.search(line)
            if match:
                filename = match.group(1)
                lineno = int(match.group(2))
                
                # 文件物理存在性校验 (过滤掉 JDK/Spring 等幽灵文件)
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

def main():
    parser = argparse.ArgumentParser(description="OmniPurge-40K 本地确定性排障神龛")
    parser.add_argument("--mock", action="store_true", help="使用离线 Mock 模式调试")
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
    
    if context_code and args.mock:
        console.print("\n[cyan]--- 抓取到的 Payload 上下文预览 ---[/cyan]")
        print(context_code.strip())

if __name__ == "__main__":
    main()