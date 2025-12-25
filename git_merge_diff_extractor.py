#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import subprocess


def run(cmd, cwd):
    """
    安全执行 Git 命令（关键修复点）
    - 使用列表形式避免 Windows shell 解析失败
    - 捕获 stdout/stderr，避免输出被吞掉
    - 禁用 shell=True，避免路径/编码导致截断
    """
    result = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Git 命令执行失败: {' '.join(cmd)}\n{result.stderr}"
        )

    return result.stdout


def write_file(path, content):
    """
    统一写文件，强制 UTF-8，避免 Windows 下写入不完整
    """
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def extract_merge_inputs(repo_path, branchA, branchB, output_dir="merge_inputs"):
    """
    MR 模式核心：生成 BASE/diffA/diffB/diffAB
    最小修复版本：仅修复 Windows diff 丢失问题，不改变任何流程逻辑
    """

    os.makedirs(output_dir, exist_ok=True)

    # 1) merge base
    merge_base = run(["git", "merge-base", branchA, branchB], cwd=repo_path).strip()
    base_content = run(["git", "show", merge_base], cwd=repo_path)
    base_path = os.path.join(output_dir, "base.txt")
    write_file(base_path, base_content)

    # 2) diffA = BASE → A
    diffA = run(["git", "diff", merge_base, branchA], cwd=repo_path)
    diffA_path = os.path.join(output_dir, "diffA.diff")
    write_file(diffA_path, diffA)

    # 3) diffB = BASE → B
    diffB = run(["git", "diff", merge_base, branchB], cwd=repo_path)
    diffB_path = os.path.join(output_dir, "diffB.diff")
    write_file(diffB_path, diffB)

    # 4) diffAB = A ↔ B
    diffAB = run(["git", "diff", branchA, branchB], cwd=repo_path)
    diffAB_path = os.path.join(output_dir, "diffAB.diff")
    write_file(diffAB_path, diffAB)

    # 返回路径（保持你原有的接口格式）
    return {
        "merge_base": merge_base,
        "base": base_path,
        "diffA": diffA_path,
        "diffB": diffB_path,
        "diffAB": diffAB_path,
    }
