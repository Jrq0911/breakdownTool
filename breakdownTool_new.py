#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenHarmony Kit 部件拆解/下载/打包工具 (全自动化多线程版)
- 支持通过 -x 参数配置网络代理 (支持账密鉴权代理)
- 支持多线程拆解与打包
- 自动生成详尽的 Result.log
"""

import os
import sys
import shutil
import argparse
import subprocess
import zipfile
import pandas as pd
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# 线程安全的日志打印锁
log_lock = threading.Lock()
log_file_path = None

def log_msg(msg: str, is_error: bool = False):
    """线程安全的控制台和文件双输出"""
    with log_lock:
        if is_error:
            print(f"[ERROR] {msg}")
        else:
            print(msg)
        if log_file_path:
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(msg + "\n")

def fix_git_url(raw_url: str) -> str:
    """修正 URL：确保结尾是 .git，并自动剔除网页浏览后缀"""
    if "/-/" in raw_url:
        raw_url = raw_url.split("/-/")[0]
    if not raw_url.endswith('.git'):
        raw_url += '.git'
    return raw_url

def is_git_url(text: str) -> bool:
    if not text: return False
    clean_text = text.strip().lower()
    return clean_text.startswith("http://") or clean_text.startswith("https://") or clean_text.startswith("git@")

def run_git_cmd(cmd):
    """封装 Git 命令执行，统一处理代理环境变量注入"""
    env = os.environ.copy()
    if proxy_url:
        env["http_proxy"] = proxy_url
        env["https_proxy"] = proxy_url
        # Windows 下 Git 可能也需要这个
        env["HTTP_PROXY"] = proxy_url
        env["HTTPS_PROXY"] = proxy_url
    return subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8', env=env)

# 全局变量，用于存储代理地址
proxy_url = None

def prepare_asset(target_dir: Path, source: str, branch: str = None):
    """执行 Git Clone (主线程调用，用于 Docs 和 SDK)"""
    if not source:
        log_msg(f"  [跳过] 未配置地址", is_error=True)
        return False
    
    target_dir.mkdir(parents=True, exist_ok=True)
    
    if is_git_url(source):
        branches_to_try = []
        if branch and branch.lower() != 'master':
            branches_to_try.append(branch)
        branches_to_try.append('master')

        for b in branches_to_try:
            cmd = ['git', 'clone', '--depth', '1']
            if b: cmd.extend(['-b', b])
            cmd.extend([source.strip(), str(target_dir)])
            
            log_msg(f"  [克隆中] 分支: {b}...")
            try:
                run_git_cmd(cmd)
                log_msg(f"  [成功] 克隆完成")
                return True
            except subprocess.CalledProcessError as e:
                log_msg(f"  [失败] {e.stderr.strip()}", is_error=True)
                if target_dir.exists(): shutil.rmtree(target_dir)
        log_msg(f"  [错误] 无法克隆: {source}", is_error=True)
        return False
    else:
        log_msg(f"  [错误] 配置的地址不是合法的 URL: {source}", is_error=True)
        return False

def process_kit_task(row, local_repo: Path, IS_LOCAL_MODE: bool, output_root: Path, branch: str):
    """处理单个 Kit 部件的任务函数 (供多线程调用)"""
    kit_name = str(row['Kit英文名']).strip()
    kit_name_safe = kit_name.replace('/', '_').replace('\\', '_')
    sub_project = str(row['子项目归属']).strip()
    comp_name_en = str(row['部件英文名称']).strip()
    comp_path = str(row['部件路径']).strip()
    
    if sub_project == "OPEN_HARMONY":
        oss_type = "开源"
        base_dir = output_root / "OpenHarmony"
        repo_url = str(row['开源仓名称']).strip()
    elif sub_project == "HARMONY_OS_SDK":
        oss_type = "闭源"
        base_dir = output_root / "Hmos"
        repo_url = str(row['闭源仓名称']).strip()
    else:
        log_msg(f"[跳过] {kit_name} -> 未知的归属类型 '{sub_project}'")
        return (kit_name, comp_name_en, "SKIP", "未知的归属类型")

    if IS_LOCAL_MODE:
        if not comp_path or comp_path == 'nan':
            return (kit_name, comp_name_en, "SKIP", "Excel中未配置部件路径(L列)")
        
        local_comp_path = local_repo / comp_path.lstrip("/")
        target_comp_dir = base_dir / kit_name_safe / comp_name_en
        
        log_msg(f"[本地拆解] {kit_name} -> {comp_name_en}")
        log_msg(f"  寻址路径: {local_comp_path}")
        
        if not local_comp_path.exists() or not any(local_comp_path.iterdir()):
            log_msg(f"  [失败] 本地缺失该路径", is_error=True)
            return (kit_name, comp_name_en, "ERROR", f"本地路径不存在或为空: {local_comp_path}")
            
        try:
            target_comp_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(local_comp_path, target_comp_dir, dirs_exist_ok=True)
            log_msg(f"  [成功] 已从本地全量仓复制")
            return (kit_name, comp_name_en, "SUCCESS", "")
        except Exception as e:
            log_msg(f"  [失败] 复制过程报错: {e}", is_error=True)
            return (kit_name, comp_name_en, "ERROR", f"复制异常: {str(e)}")
    else:
        if not repo_url or repo_url == 'nan':
            log_msg(f"[远程下载] {kit_name} -> {comp_name_en} [跳过: 无仓库地址]")
            return (kit_name, comp_name_en, "SKIP", "无仓库地址")
            
        target_repo_dir = base_dir / kit_name_safe / comp_name_en
        log_msg(f"[远程下载] {kit_name} -> {comp_name_en}")
        
        if target_repo_dir.exists() and any(target_repo_dir.iterdir()):
            log_msg(f"  [跳过] 目录已存在")
            return (kit_name, comp_name_en, "SKIP", "目标目录已存在")
            
        branches_to_try = []
        if branch and branch.lower() != 'master':
            branches_to_try.append(branch)
        branches_to_try.append('master')
        
        for b in branches_to_try:
            cmd = ['git', 'clone', '--depth', '1']
            if b: cmd.extend(['-b', b])
            cmd.extend([repo_url, str(target_repo_dir)])
            log_msg(f"  [克隆] 分支: {b}...")
            try:
                run_git_cmd(cmd)
                log_msg(f"  [成功] 仓库克隆完成")
                return (kit_name, comp_name_en, "SUCCESS", "")
            except subprocess.CalledProcessError as e:
                log_msg(f"  [失败] {e.stderr.strip()}", is_error=True)
                if target_repo_dir.exists(): shutil.rmtree(target_repo_dir)
                
        log_msg(f"  [错误] 仓库下载失败", is_error=True)
        return (kit_name, comp_name_en, "ERROR", "Git克隆失败")

def zip_kit_task(kit_dir: Path):
    """按 Kit 打包为 zip (供多线程调用)，包存放在 Kit 文件夹内部"""
    if not kit_dir.exists() or not any(kit_dir.iterdir()):
        return (kit_dir.name, "SKIP", "目录为空或不存在")
    
    zip_path = kit_dir / f"{kit_dir.name}.zip"
    
    try:
        files_to_zip = [
            f for f in kit_dir.rglob('*') 
            if f.is_file() and f.suffix.lower() != '.zip'
        ]
        
        if not files_to_zip:
            return (kit_dir.name, "SKIP", "目录内没有可打包的有效文件")
            
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path in files_to_zip:
                try:
                    arcname = file_path.relative_to(kit_dir.parent)
                    zipf.write(file_path, arcname)
                except PermissionError:
                    log_msg(f"    [警告] 跳过无权限文件: {file_path.name}", is_error=True)
                except Exception as e:
                    log_msg(f"    [警告] 跳过异常文件: {file_path.name} ({e})", is_error=True)
                    
        return (kit_dir.name, "SUCCESS", "")
    except Exception as e:
        return (kit_dir.name, "ERROR", str(e))

def main():
    global log_file_path, proxy_url
    
    parser = argparse.ArgumentParser(description="Kit部件拆解/下载/打包工具 (多线程+日志+代理)")
    parser.add_argument("-e", "--excel", required=True, help="Kit部件映射 Excel 文件路径")
    parser.add_argument("-o", "--output", required=True, help="输出根目录")
    parser.add_argument("-r", "--repo", default=None, help="(可选)本地全量代码仓路径。提供则本地拆解，不提供则Git下载")
    parser.add_argument("-b", "--branch", default=None, help="(可选)指定分支，不存在则回退 master")
    parser.add_argument("-t", "--threads", type=int, default=4, help="(可选)拆解/打包的并发线程数，默认 4")
    parser.add_argument("-x", "--proxy", default=None, help="(可选)配置网络代理，格式如: http://ip:port 或带鉴权 http://user:pass@ip:port")
    args = parser.parse_args()

    output_root = Path(args.output).resolve()
    excel_path = Path(args.excel).resolve()
    local_repo = Path(args.repo).resolve() if args.repo else None
    proxy_url = args.proxy
    
    IS_LOCAL_MODE = True if local_repo else False
    MODE_TEXT = "【模式2：本地全量拆解】" if IS_LOCAL_MODE else "【模式1：默认全量下载】"
    
    # 初始化日志文件
    log_file_path = output_root / "result.log"
    if log_file_path.exists():
        log_file_path.unlink()
    
    print("\n" + "="*60)
    log_msg(f" 启动模式: {MODE_TEXT} | 并发线程数: {args.threads}")
    if proxy_url:
        # 隐藏代理中的账密进行日志打印
        safe_proxy = proxy_url
        if '@' in proxy_url:
            parts = proxy_url.split('://')
            if len(parts) == 2:
                auth_host = parts[1].split('@')
                safe_proxy = f"{parts[0]}://***:***@{auth_host[1]}"
        log_msg(f" 网络代理: 已配置 ({safe_proxy})")
    else:
        log_msg(f" 网络代理: 未配置 (使用本机默认网络)")
        
    if IS_LOCAL_MODE and not local_repo.exists():
        log_msg(f"错误: 本地代码仓不存在 -> {local_repo}", is_error=True)
        sys.exit(1)
    log_msg("="*60)

    try:
        df = pd.read_excel(excel_path)
        df.columns = df.columns.str.strip()
    except Exception as e:
        sys.exit(f"读取Excel失败: {e}")

    oh_root = output_root / "OpenHarmony"
    hmos_root = output_root / "Hmos"

    # ==================== 阶段0: 初始化骨架 ====================
    log_msg("\n--- 阶段0: 初始化标准目录骨架 ---")
    for base in [oh_root, hmos_root]:
        (base / "Docs").mkdir(parents=True, exist_ok=True)
        (base / "SDK" / "JS").mkdir(parents=True, exist_ok=True)
        (base / "SDK" / "C").mkdir(parents=True, exist_ok=True)
        (base / "SDK" / "Cangjie").mkdir(parents=True, exist_ok=True)
    log_msg("  [成功] 骨架创建完毕")

    # ==================== 阶段1: 处理 Docs 和 SDK ====================
    log_msg("\n--- 阶段1: 处理 Docs 和 SDK ---")
    #prepare_asset(oh_root / "Docs", "https://gitcode.com/openharmony/docs.git", args.branch)
    #prepare_asset(hmos_root / "Docs", fix_git_url("https://cr-y.codehub.huawei.com/CBG_CR/huawei/HarmonyOS_Docs/-/home"), args.branch)

    if IS_LOCAL_MODE:
        log_msg("\n--- 阶段1.1: 处理 SDK (本地模式) ---")
        sdk_local_map = {
            oh_root / "SDK" / "JS": "/interface/sdk-js",
            oh_root / "SDK" / "C": "/interface/sdk_c",
            oh_root / "SDK" / "Cangjie": "/interface/sdk_cangjie",
            hmos_root / "SDK" / "JS": "/vendor/huawei/interface/hmscore_sdk_js",
            hmos_root / "SDK" / "C": "/vendor/huawei/interface/hmscore_sdk_c",
        }
        for target_dir, rel_path in sdk_local_map.items():
            log_msg(f"\n处理 [{target_dir.relative_to(output_root)}]...")
            src_path = local_repo / rel_path.lstrip("/")
            if src_path.exists():
                shutil.copytree(src_path, target_dir, dirs_exist_ok=True)
                log_msg(f"  [成功] 从本地复制")
            else:
                log_msg(f"  [警告] 本地路径不存在: {src_path}", is_error=True)
    else:
        log_msg("\n--- 阶段1.1: 处理 SDK (下载模式) ---")
        sdk_url_map = {
            oh_root / "SDK" / "JS": "https://open.codehub.huawei.com/OpenSourceCenter_CR/openharmony/interface_sdk-js",
            oh_root / "SDK" / "C": "https://open.codehub.huawei.com/OpenSourceCenter_CR/openharmony/interface_sdk_c",
            oh_root / "SDK" / "Cangjie": "https://open.codehub.huawei.com/OpenSourceCenter_CR/openharmony/interface_sdk_cangjie",
            hmos_root / "SDK" / "JS": "https://cr-y.codehub.huawei.com/CBG_CR_HarmonyOS/huawei/interface/hmscore_sdk_js",
            hmos_root / "SDK" / "C": "https://cr-y.codehub.huawei.com/CBG_CR_HarmonyOS/huawei/interface/hmscore_sdk_c",
        }
        for target_dir, raw_url in sdk_url_map.items():
            log_msg(f"\n处理 [{target_dir.relative_to(output_root)}]...")
            real_clone_url = fix_git_url(raw_url)
            prepare_asset(target_dir, real_clone_url, args.branch)

    # ==================== 阶段2: 多线程处理 Kit 与 部件 ====================
    log_msg("\n--- 阶段2: 多线程处理 Kit 与 部件 ---")
    results = []
    
    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        futures = {
            executor.submit(process_kit_task, row, local_repo, IS_LOCAL_MODE, output_root, args.branch): idx
            for idx, row in df.iterrows()
        }
        for future in as_completed(futures):
            results.append(future.result())

    success_count = sum(1 for r in results if r[2] == "SUCCESS")
    error_count = sum(1 for r in results if r[2] == "ERROR")
    skip_count = sum(1 for r in results if r[2] == "SKIP")
    
    log_msg("\n--- 阶段2: 拆解/下载结果汇总 ---")
    log_msg(f"总计: {len(results)} | 成功: {success_count} | 失败: {error_count} | 跳过: {skip_count}")
    
    if error_count > 0:
        log_msg("\n[失败明细如下]:")
        for kit, comp, status, err in results:
            if status == "ERROR":
                log_msg(f"  - {kit} / {comp} : {err}", is_error=True)

    # ==================== 阶段3: 按 Kit 多线程打包 ====================
    log_msg("\n--- 阶段3: 按 Kit 归档打包 (存放在各自 Kit 目录下) ---")
    kit_dirs = []
    for base in [oh_root, hmos_root]:
        for kit_dir in base.iterdir():
            if kit_dir.is_dir() and kit_dir.name not in ["Docs", "SDK"]:
                kit_dirs.append(kit_dir)
                
    zip_results = []
    if kit_dirs:
        with ThreadPoolExecutor(max_workers=args.threads) as executor:
            futures = [executor.submit(zip_kit_task, kd) for kd in kit_dirs]
            for future in as_completed(futures):
                zip_results.append(future.result())
                
        for name, status, err in zip_results:
            if status == "SUCCESS":
                log_msg(f"  [打包成功] {name} 目录下已生成 {name}.zip")
            elif status == "ERROR":
                log_msg(f"  [打包失败] {name}: {err}", is_error=True)
    else:
        log_msg("  未检测到需要打包的 Kit 目录")

    log_msg("\n" + "="*60)
    log_msg("✅ 全部任务执行完毕！详情请查看 output 目录下的 result.log")
    log_msg("="*60 + "\n")

if __name__ == "__main__":
    main()