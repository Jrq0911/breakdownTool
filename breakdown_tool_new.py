#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenHarmony Kit 部件拆解/下载工具 (全自动化配置版)
- Docs 与 SDK 路径/地址全部内置于脚本中，无需命令行传参
- 自动将网页浏览 URL 转换为标准 Git Clone URL
"""

import os
import sys
import shutil
import argparse
import subprocess
import pandas as pd
from pathlib import Path

def fix_git_url(raw_url: str) -> str:
    """
    修正 URL：确保结尾是 .git，并自动剔除网页浏览后缀
    """
    if "/-/" in raw_url:
        raw_url = raw_url.split("/-/")[0] # 砍掉后面的网页参数
    if not raw_url.endswith('.git'):
        raw_url += '.git'                # 补齐标准的 git 后缀
    return raw_url

def is_git_url(text: str) -> bool:
    if not text: return False
    clean_text = text.strip().lower()
    return clean_text.startswith("http://") or clean_text.startswith("https://") or clean_text.startswith("git@")

def prepare_asset(target_dir: Path, source: str, branch: str = None):
    """执行 Git Clone"""
    if not source:
        print(f"  [跳过] 未配置地址")
        return
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
            
            print(f"  [克隆中] 分支: {b}...")
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
                print(f"  [成功] 克隆完成")
                return
            except subprocess.CalledProcessError as e:
                print(f"  [失败] {e.stderr.strip()}")
                if target_dir.exists(): shutil.rmtree(target_dir)
        print(f"  [错误] 无法克隆: {source}")
    else:
        print(f"  [错误] 配置的地址不是合法的 URL: {source}")

def main():
    parser = argparse.ArgumentParser(description="Kit部件拆解/下载工具 (Docs/SDK全自动)")
    parser.add_argument("-e", "--excel", required=True, help="Kit部件映射 Excel 文件路径")
    parser.add_argument("-o", "--output", required=True, help="输出根目录")
    parser.add_argument("-r", "--repo", default=None, help="(可选)本地全量代码仓路径。提供则本地拆解，不提供则Git下载")
    parser.add_argument("-b", "--branch", default=None, help="(可选)指定分支，不存在则回退 master")
    args = parser.parse_args()

    output_root = Path(args.output).resolve()
    excel_path = Path(args.excel).resolve()
    local_repo = Path(args.repo).resolve() if args.repo else None
    
    IS_LOCAL_MODE = True if local_repo else False
    MODE_TEXT = "【模式2：本地全量拆解】" if IS_LOCAL_MODE else "【模式1：默认全量下载】"
    
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
        (base / "SDK" / "Cangjie").mkdir(parents=True, exist_ok=True) # 新增 Cangjie
    print(f"  [成功] 骨架创建完毕")

    # ====================================================================
    # 阶段1: 处理 Docs 和 SDK (全部内置写死，不再读取外部参数)
    # ====================================================================
    print("\n--- 阶段1: 处理 Docs (两种模式均直接 Clone) ---")
    prepare_asset(oh_root / "Docs", "https://gitcode.com/openharmony/docs", args.branch)
    prepare_asset(hmos_root / "Docs", fix_git_url("https://cr-y.codehub.huawei.com/CBG_CR/huawei/HarmonyOS_Docs/-/home"), args.branch)

    print("\n--- 阶段1: 处理 SDK ---")
    if IS_LOCAL_MODE:
        print("  检测到本地拆解模式，从本地仓固定路径复制...")
        sdk_local_map = {
            oh_root / "SDK" / "JS": "/code/interface/sdk-js",
            oh_root / "SDK" / "C": "/code/interface/sdk_c",
            oh_root / "SDK" / "Cangjie": "/code/interface/sdk_cangjie",
            hmos_root / "SDK" / "JS": "/code/vendor/huawei/interface/hmscore_sdk_js",
            hmos_root / "SDK" / "C": "/code/vendor/huawei/interface/hmscore_sdk_c",
        }
        for target_dir, rel_path in sdk_local_map.items():
            print(f"\n处理 [{target_dir.relative_to(output_root)}]...")
            src_path = local_repo / rel_path.lstrip("/")
            if src_path.exists():
                shutil.copytree(src_path, target_dir, dirs_exist_ok=True)
                print(f"  [成功] 从本地复制")
            else:
                print(f"  [警告] 本地路径不存在: {src_path}")
    else:
        print("  检测到下载模式，从固定地址 Clone...")
        # 注意：这里的 URL 已经去掉了 ref=master，保持纯粹的仓库地址
        # 分支完全由运行脚本时的 -b 参数控制！
        sdk_url_map = {
            oh_root / "SDK" / "JS": "https://open.codehub.huawei.com/OpenSourceCenter_CR/openharmony/interface_sdk-js",
            oh_root / "SDK" / "C": "https://open.codehub.huawei.com/OpenSourceCenter_CR/openharmony/interface_sdk_c",
            oh_root / "SDK" / "Cangjie": "https://open.codehub.huawei.com/OpenSourceCenter_CR/openharmony/interface_sdk_cangjie",
            hmos_root / "SDK" / "JS": "https://cr-y.codehub.huawei.com/CBG_CR_HarmonyOS/huawei/interface/hmscore_sdk_js",
            hmos_root / "SDK" / "C": "https://cr-y.codehub.huawei.com/CBG_CR_HarmonyOS/huawei/interface/hmscore_sdk_c",
        }
        for target_dir, raw_url in sdk_url_map.items():
            print(f"\n处理 [{target_dir.relative_to(output_root)}]...")
            real_clone_url = fix_git_url(raw_url) # 这里会自动加上 .git
            prepare_asset(target_dir, real_clone_url, args.branch) # args.branch 会传给 git clone -b

    # ==================== 阶段2: 处理 Kit 与 部件 ====================
    print("\n--- 阶段2: 处理 Kit 与 部件 ---")

    for _, row in df.iterrows():
        kit_name = str(row['Kit英文名']).strip()
        kit_name_safe = kit_name.replace('/', '_').replace('\\', '_')
        sub_project = str(row['子项目归属']).strip()
        comp_name_en = str(row['部件英文名称']).strip()
        comp_path = str(row['部件路径']).strip()
        
        if sub_project == "OPEN_HARMONY":
            oss_type = "开源"
            base_dir = oh_root
            repo_url = str(row['开源仓名称']).strip()
        elif sub_project == "HARMONY_OS_SDK":
            oss_type = "闭源"
            base_dir = hmos_root
            repo_url = str(row['闭源仓名称']).strip()
        else:
            print(f"\n[跳过] {kit_name} -> 未知的归属类型 '{sub_project}'")
            continue

        if IS_LOCAL_MODE:
            if not comp_path or comp_path == 'nan': continue
            
            # 新逻辑：L列仅用于寻址，目标目录严格保持和下载模式一样的平级结构
            target_comp_dir = base_dir / kit_name_safe / comp_name_en
            target_comp_dir.mkdir(parents=True, exist_ok=True)
            
            print(f"\n[本地拆解] {kit_name} -> {comp_name_en}")
            print(f"  寻址路径(L列): {comp_path}")
            
            # 去本地仓里按照 L列 寻找源码
            local_comp_path = local_repo / comp_path
            if local_comp_path.exists() and any(local_comp_path.iterdir()):
                shutil.copytree(local_comp_path, target_comp_dir, dirs_exist_ok=True)
                print(f"  [成功] 已从本地全量仓复制")
            else:
                print(f"  [警告] 本地缺失该路径，已跳过。")
        else:
            if not repo_url or repo_url == 'nan':
                print(f"\n[远程下载] {kit_name} -> {comp_name_en} [跳过: 无仓库地址]")
                continue
            target_repo_dir = base_dir / kit_name_safe / comp_name_en
            print(f"\n[远程下载] {kit_name} -> {comp_name_en}")
            if target_repo_dir.exists() and any(target_repo_dir.iterdir()):
                print(f"  [跳过] 目录已存在")
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
                print(f"  [克隆] 分支: {b}...")
                try:
                    subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
                    print(f"  [成功] 仓库全量克隆完成")
                    clone_success = True
                    break
                except subprocess.CalledProcessError as e:
                    print(f"  [失败] {e.stderr.strip()}")
                    if target_repo_dir.exists(): shutil.rmtree(target_repo_dir)
            if not clone_success:
                print(f"  [错误] 仓库下载失败，跳过。")

    print("\n" + "="*60)
    print("✅ 任务执行完毕！")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()