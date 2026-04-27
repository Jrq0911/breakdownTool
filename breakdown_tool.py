#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenHarmony Kit 部件拆解/下载工具 (双模式解耦版)
- 默认模式(无 -r): 无视L列，直接Clone J/K列全量仓库
- 拆解模式(有 -r): 无视J/K列，严格按L列从本地全量仓复制
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
    """智能准备 Docs/SDK：URL克隆，本地路径复制"""
    if not source:
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
    parser.add_argument("--oh-sdk-js", default=None, help="开源SDK-JS")
    parser.add_argument("--oh-sdk-c", default=None, help="开源SDK-C")
    parser.add_argument("--hmos-docs", default=None, help="闭源Docs")
    parser.add_argument("--hmos-sdk-js", default=None, help="闭源SDK-JS")
    parser.add_argument("--hmos-sdk-c", default=None, help="闭源SDK-C")
    
    args = parser.parse_args()

    output_root = Path(args.output).resolve()
    excel_path = Path(args.excel).resolve()
    local_repo = Path(args.repo).resolve() if args.repo else None
    
    IS_LOCAL_MODE = True if local_repo else False
    MODE_TEXT = "【模式2：本地全量代码拆解 (关注L列)】" if IS_LOCAL_MODE else "【模式1：默认全量下载 (关注J/K列)】"
    
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

    # ==================== 阶段0: 初始化骨架 ====================
    print("\n--- 阶段0: 初始化标准目录骨架 ---")
    for base in [oh_root, hmos_root]:
        (base / "Docs").mkdir(parents=True, exist_ok=True)
        (base / "SDK" / "JS").mkdir(parents=True, exist_ok=True)
        (base / "SDK" / "C").mkdir(parents=True, exist_ok=True)
    print(f"  [成功] 骨架创建完毕")

    # ==================== 阶段1: 填充 Docs 和 SDK ====================
    print("\n--- 阶段1: 准备 Docs 与 SDK ---")
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

    # ==================== 阶段2: 处理 Kit 与 部件 (核心逻辑解耦) ====================
    print("\n--- 阶段2: 处理 Kit 与 部件 ---")

    for _, row in df.iterrows():
        kit_name = str(row['Kit英文名']).strip()
        kit_name_safe = kit_name.replace('/', '_').replace('\\', '_')
        sub_project = str(row['子项目归属']).strip()
        comp_name_en = str(row['部件英文名称']).strip()
        comp_path = str(row['部件路径']).strip() # L列
        
        # 根据 D列 "子项目归属" 判断开闭源及获取对应URL
        if sub_project == "OPEN_HARMONY":
            oss_type = "开源"
            base_dir = oh_root
            repo_url = str(row['开源仓名称']).strip()
        elif sub_project == "HARMONY_OS_SDK":
            oss_type = "闭源"
            base_dir = hmos_root
            repo_url = str(row['闭源仓名称']).strip()
        else:
            print(f"\n[跳过] {kit_name} -> 未知的归属类型 '{sub_project}'，请检查Excel D列")
            continue

        # --------------------- 分支 A：本地拆解模式 ---------------------
        if IS_LOCAL_MODE:
            if not comp_path or comp_path == 'nan':
                continue
            
            # 目录结构: OpenHarmony/ArkUI/foundation/arkui/ace_engine/
            target_comp_dir = base_dir / kit_name_safe / comp_path
            target_comp_dir.mkdir(parents=True, exist_ok=True)
            
            print(f"\n[本地拆解] {kit_name} -> {comp_name_en}")
            print(f"  读取L列路径: {comp_path}")
            
            local_comp_path = local_repo / comp_path
            if local_comp_path.exists() and any(local_comp_path.iterdir()):
                shutil.copytree(local_comp_path, target_comp_dir, dirs_exist_ok=True)
                print(f"  [成功] 已从本地全量仓复制")
            else:
                print(f"  [警告] 本地缺失该路径，已跳过。")
                
        # --------------------- 分支 B：默认下载模式 ---------------------
        else:
            if not repo_url or repo_url == 'nan':
                print(f"\n[远程下载] {kit_name} -> {comp_name_en}")
                print(f"  [跳过] Excel中未提供仓库地址(J/K列)")
                continue
            
            # 目录结构: OpenHarmony/ArkUI/ace_engine/ (直接以部件英文名作为文件夹)
            target_repo_dir = base_dir / kit_name_safe / comp_name_en
            
            print(f"\n[远程下载] {kit_name} -> {comp_name_en}")
            print(f"  读取J/K列地址: {repo_url}")
            
            # 防止同一个 Kit 下的相同部件被重复 clone
            if target_repo_dir.exists() and any(target_repo_dir.iterdir()):
                print(f"  [跳过] 该部件目录已存在全量代码")
                continue
                
            branches_to_try = []
            if args.branch and args.branch.lower() != 'master':
                branches_to_try.append(args.branch)
            branches_to_try.append('master')
            
            clone_success = False
            for b in branches_to_try:
                cmd = ['git', 'clone', '--depth', '1']
                if b: cmd.extend(['-b', b])
                cmd.extend([repo_url, str(target_repo_dir)])
                
                print(f"  [克隆] 直接下载全量内容至: {target_repo_dir.name} (分支: {b})")
                try:
                    subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
                    print(f"  [成功] 仓库全量克隆完成")
                    clone_success = True
                    break
                except subprocess.CalledProcessError as e:
                    print(f"  [失败] {e.stderr.strip()}")
                    if target_repo_dir.exists(): shutil.rmtree(target_repo_dir)
            
            if not clone_success:
                print(f"  [错误] 仓库下载彻底失败，跳过。")

    print("\n" + "="*60)
    print("✅ 任务执行完毕！")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()