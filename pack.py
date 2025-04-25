# auto_pyinstaller_pack.py
import ast, os, subprocess, sys

used_modules = set()
exclude_modules = {"tkinter", "unittest", "email", "http", "test", "pydoc"}

def scan_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        try:
            tree = ast.parse(f.read(), filename=filepath)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        used_modules.add(alias.name.split('.')[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        used_modules.add(node.module.split('.')[0])
        except Exception as e:
            print(f"[!] Error parsing {filepath}: {e}")

def scan_folder(folder):
    for root, _, files in os.walk(folder):
        for file in files:
            if file.endswith(".py"):
                scan_file(os.path.join(root, file))

def build_pyinstaller_command(entry_script):
    hidden_imports = [f"--hidden-import={m}" for m in sorted(used_modules - exclude_modules)]
    excludes = [f"--exclude-module={m}" for m in sorted(exclude_modules)]
    cmd = [
        "pyinstaller",
        entry_script,
        "--onefile",
        "-w",
        *hidden_imports,
        *excludes
    ]
    return cmd

def main():

    entry_script = "main.py"

    if not os.path.exists(entry_script):
        print(f"[!] 找不到入口脚本文件: {entry_script}")
        return

    print("[*] 正在扫描项目使用的模块...")
    scan_folder(".")
    print("[*] 发现的模块:", ", ".join(sorted(used_modules)))

    print("[*] 构建 PyInstaller 命令...")
    cmd = build_pyinstaller_command(entry_script)
    print("[*] 执行命令：\n", " ".join(cmd))

    print("[*] 开始打包...")
    subprocess.run(cmd)

if __name__ == "__main__":
    main()
