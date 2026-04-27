#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenHarmony Kit 部件拆解/下载工具 (双模式版 - 修正目录层级)
"""

import os
import sys
import shutil
import argparse
import subprocess
import pandas as pd
from pathlib import Path

def is_git_url(text: str) -> bool:
    """判断字符串是否是 Git 仓库地址"""
    if not text: return False
    clean_text = text.strip().lower().rstrip('/').rstrip('\\')
    return clean_text.startswith("http://") or clean_text.startswith("https://") or clean_text.startswith("git@")

def prepare_asset(target_dir: Path, source: str, branch: str = None):
    """
    智能准备资源：自动识别 URL 执行 clone，识别本地路径执行 copy
    """
    if not source:
        # 即使没有来源，文件夹也已经在前面强制建好了，这里只做提示
        print(f"  [跳过] 未提供来源，保持空文件夹: {target_dir.name}")
        return

    if is_git_url(source):
        branches_to_try = []
        if branch and branch.lower() != 'master':
            branches_to_try.append(branch)
        branches_to_try.append('master')

        for b in branches_to_try:
            cmd = ['git', 'clone', '--depth', '1']
            if b: cmd.extend(['-b', b])
            cmd.extend([source.strip(), str(target_dir)])
            
            print(f"  [识别为URL] 执行克隆 (分支: {b})...")
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
                print(f"  [成功] 克隆完成")
                return
            except subprocess.CalledProcessError as e:
                print(f"  [失败] {e.stderr.strip()}")
                if target_dir.exists(): shutil.rmtree(target_dir)
        print(f"  [错误] 无法克隆: {source}")
    else:
        src_path = Path(source).resolve()
        print(f"  [识别为本地] 执行复制...")
        if src_path.exists():
            shutil.copytree(src_path, target_dir, dirs_exist_ok=True)
            print(f"  [成功] 复制完成")
        else:
            print(f"  [错误] 本地路径不存在: {src_path}")

def main():
    parser = argparse.ArgumentParser(description="Kit部件拆解/下载工具")
    parser.add_argument("-e", "--excel", required=True, help="Kit部件映射 Excel 文件路径")
    parser.add_argument("-o", "--output", required=True, help="输出根目录")
    parser.add_argument("-r", "--repo", default=None, help="(可选)本地全量代码仓路径。提供则本地拆解，不提供则Git下载")
    parser.add_argument("-b", "--branch", default=None, help="(可选)指定分支，不存在则回退 master")
    
    parser.add_argument("--oh-docs", default=None, help="开源Docs (填URL克隆 / 填本地路径复制)")
    parser.add_argument("--oh-sdk-js", default=None, help="开源SDK-JS (填URL克隆 / 填本地路径复制)")
    parser.add_argument("--oh-sdk-c", default=None, help="开源SDK-C (填URL克隆 / 填本地路径复制)")
    parser.add_argument("--hmos-docs", default=None, help="闭源Docs (填URL克隆 / 填本地路径复制)")
    parser.add_argument("--hmos-sdk-js", default=None, help="闭源SDK-JS (填URL克隆 / 填本地路径复制)")
    parser.add_argument("--hmos-sdk-c", default=None, help="闭源SDK-C (填URL克隆 / 填本地路径复制)")
    
    args = parser.parse_args()

    output_root = Path(args.output).resolve()
    excel_path = Path(args.excel).resolve()
    local_repo = Path(args.repo).resolve() if args.repo else None
    
    IS_LOCAL_MODE = True if local_repo else False
    MODE_TEXT = "【本地全量代码拆解模式】" if IS_LOCAL_MODE else "【默认 Git Clone 下载模式】"
    
    print("\n" + "="*60)
    print(f" 启动模式: {MODE_TEXT}")
    if IS_LOCAL_MODE and not local_repo.exists():
        sys.exit(f"错误: 本地代码仓不存在 -> {local_repo}")
    print("="*60)

    try:
        df = pd.read_excel(excel_path)
        df.columns = df.columns.str.strip()
    except Exception as e:
        sys.exit(f"读取Excel失败: {e}")

    oh_root = output_root / "OpenHarmony"
    hmos_root = output_root / "Hmos"
    clone_cache_dir = output_root / ".git_cache"

    # ==================== 核心修正：强制建立严谨的平行骨架目录 ====================
    print("\n--- 阶段0: 初始化标准目录骨架 ---")
    for base in [oh_root, hmos_root]:
        (base / "Docs").mkdir(parents=True, exist_ok=True)
        (base / "SDK" / "JS").mkdir(parents=True, exist_ok=True)
        (base / "SDK" / "C").mkdir(parents=True, exist_ok=True)
    print(f"  [成功] 骨架创建完毕于: {output_root}")

    # ==================== 阶段1: 填充 Docs 和 SDK ====================
    print("\n--- 阶段1: 准备 Docs 与 SDK (JS/C) ---")
    
    # 修正了这里的路径拼接，严格保证是 base/Docs, base/SDK/JS 等
    assets_config = [
        (oh_root / "Docs", "OpenHarmony/Docs", args.oh_docs),
        (oh_root / "SDK" / "JS", "OpenHarmony/SDK/JS", args.oh_sdk_js),
        (oh_root / "SDK" / "C", "OpenHarmony/SDK/C", args.oh_sdk_c),
        (hmos_root / "Docs", "Hmos/Docs", args.hmos_docs),
        (hmos_root / "SDK" / "JS", "Hmos/SDK/JS", args.hmos_sdk_js),
        (hmos_root / "SDK" / "C", "Hmos/SDK/C", args.hmos_sdk_c),
    ]
    
    for target_dir, label, source in assets_config:
        print(f"\n处理 [{label}]...")
        prepare_asset(target_dir, source, args.branch)

    # ==================== 阶段2: 处理 Kit 与 部件 ====================
    print("\n--- 阶段2: 处理 Kit 与 部件 ---")
    repo_cache_map = {} 

    for _, row in df.iterrows():
        kit_name = str(row['Kit英文名']).strip()
        kit_name_safe = kit_name.replace('/', '_').replace('\\', '_')
        oss_type = str(row['开闭源']).strip()
        comp_name_en = str(row['部件英文名称']).strip()
        comp_path = str(row['部件路径']).strip()
        
        base_dir = oh_root if oss_type == '开源' else hmos_root
        repo_url = str(row['开源仓名称']).strip() if oss_type == '开源' else str(row['闭源仓名称']).strip()
        
        if not comp_path or comp_path == 'nan':
            continue

        target_comp_dir = base_dir / kit_name_safe / comp_path
        target_comp_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n[{oss_type}] {kit_name} -> {comp_name_en}")

        if IS_LOCAL_MODE:
            local_comp_path = local_repo / comp_path
            if local_comp_path.exists() and any(local_comp_path.iterdir()):
                shutil.copytree(local_comp_path, target_comp_dir, dirs_exist_ok=True)
                print(f"  [成功] 已从本地全量仓复制")
            else:
                print(f"  [警告] 本地缺失该路径，已跳过。")
        else:
            if not repo_url or repo_url == 'nan':
                print(f"  [错误] Excel中未提供仓库地址，跳过。")
                continue

            if repo_url not in repo_cache_map:
                repo_name = repo_url.rstrip('/').split('/')[-1]
                cache_path = clone_cache_dir / repo_name
                repo_cache_map[repo_url] = cache_path
                
                branches_to_try = []
                if args.branch and args.branch.lower() != 'master':
                    branches_to_try.append(args.branch)
                branches_to_try.append('master')
                
                clone_success = False
                for b in branches_to_try:
                    cmd = ['git', 'clone', '--depth', '1']
                    if b: cmd.extend(['-b', b])
                    cmd.extend([repo_url, str(cache_path)])
                    
                    print(f"  [克隆] {repo_name} (分支: {b})")
                    try:
                        subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
                        print(f"  [成功] 仓库克隆完成")
                        clone_success = True
                        break
                    except subprocess.CalledProcessError as e:
                        print(f"  [失败] {e.stderr.strip()}")
                        if cache_path.exists(): shutil.rmtree(cache_path)
                
                if not clone_success:
                    print(f"  [错误] 仓库下载失败，跳过。")
                    repo_cache_map[repo_url] = None 

            cached_repo = repo_cache_map[repo_url]
            if cached_repo and cached_repo.exists():
                source_in_repo = cached_repo / comp_path
                if source_in_repo.exists() and any(source_in_repo.iterdir()):
                    shutil.copytree(source_in_repo, target_comp_dir, dirs_exist_ok=True)
                    print(f"  [成功] 部件代码提取完成")
                else:
                    print(f"  [提示] 未找到子路径，提取仓库根目录。")
                    shutil.copytree(cached_repo, target_comp_dir, dirs_exist_ok=True)

    if not IS_LOCAL_MODE and clone_cache_dir.exists():
        shutil.rmtree(clone_cache_dir)
        print("\n[清理] 已删除临时缓存")

    print("\n" + "="*60)
    print("✅ 任务执行完毕！")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()