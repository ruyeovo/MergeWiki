#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from typing import Dict, List
from models import DiffBlock, DiffHunk, Location, FileReport


class DiffParser:
    """
    以 diffAB（branchA↔branchB）作为唯一冲突块来源的 MR 解析器。

    - diffAB 决定 block 数量（一个 hunk = 一个 block）
    - diffA/diffB 用于为 LLM 提供修改上下文（修改原因、原始内容）
    """

    HUNK_PATTERN = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

    # --------------------------
    # 通用：解析单个 diff 文件/文本 → {file: [DiffHunk]}
    # --------------------------
    def _parse_diff_lines(self, lines: List[str]) -> Dict[str, List[DiffHunk]]:
        """解析 diff 文本行 -> {file_path: [DiffHunk]}（内部通用实现）"""
        file_hunks: Dict[str, List[DiffHunk]] = {}
        current_file = None
        current_hunk_lines: List[str] = []
        hunk_start = None
        hunk_end = None

        for line in lines:
            if line.startswith("diff --git"):
                if current_file and current_hunk_lines:
                    file_hunks.setdefault(current_file, []).append(
                        DiffHunk(current_file, hunk_start, hunk_end, "".join(current_hunk_lines))
                    )
                current_file = None
                current_hunk_lines = []
                continue

            if line.startswith("+++ "):
                current_file = line[4:].strip()
                continue

            match = self.HUNK_PATTERN.match(line)
            if match:
                if current_file and current_hunk_lines:
                    file_hunks.setdefault(current_file, []).append(
                        DiffHunk(current_file, hunk_start, hunk_end, "".join(current_hunk_lines))
                    )
                hunk_start = int(match.group(3))
                hunk_len = match.group(4)
                hunk_end = hunk_start + (int(hunk_len) if hunk_len else 1)
                current_hunk_lines = [line]
            else:
                if current_file:
                    current_hunk_lines.append(line)

        if current_file and current_hunk_lines:
            file_hunks.setdefault(current_file, []).append(
                DiffHunk(current_file, hunk_start, hunk_end, "".join(current_hunk_lines))
            )

        return file_hunks

    def parse_diff_file(self, diff_path: str) -> Dict[str, List[DiffHunk]]:
        """解析 diff 文件 -> {file_path: [DiffHunk]}"""
        with open(diff_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return self._parse_diff_lines(lines)

    def parse_diff_text(self, diff_text: str) -> Dict[str, List[DiffHunk]]:
        """解析 diff 字符串 -> {file_path: [DiffHunk]}"""
        return self._parse_diff_lines(diff_text.splitlines(keepends=True))

    def parse_diff(self, diff_text: str) -> List[DiffBlock]:
        """单 diff 字符串模式：把 diffAB 作为来源构建 block 列表（兼容 CodeDiffAnalyzer.analyze_diff_content）"""
        diffAB = self.parse_diff_text(diff_text)
        file_reports = self.build_diff_blocks({}, {}, diffAB)

        blocks: List[DiffBlock] = []
        for fr in file_reports:
            blocks.extend(fr.diff_blocks)
        return blocks

    # --------------------------
    # 构建基于 diffAB hunk 的冲突块
    # --------------------------
    def build_diff_blocks(self, diffA, diffB, diffAB):
        """
        每个 diffAB 的 hunk 都是一个冲突块。
        A/B 内容仅作为上下文提供给 LLM，不用于分块。
        """
        file_reports = []
        block_id = 1

        for file_path, ab_hunks in diffAB.items():
            blocks = []

            for hAB in ab_hunks:
                # 根据 AB hunk 的行号找到 A/B 对应的 hunk（如有）
                matchA = self._find_matching_hunk(diffA.get(file_path, []), hAB)
                matchB = self._find_matching_hunk(diffB.get(file_path, []), hAB)

                block = DiffBlock(
                    id=block_id,

                    file_path_branchA=file_path,
                    file_path_branchB=file_path,

                    location_branchA=Location(matchA.start_line, matchA.end_line) if matchA else Location(0, 0),
                    location_branchB=Location(matchB.start_line, matchB.end_line) if matchB else Location(0, 0),

                    branchA_content=matchA.content if matchA else None,
                    branchB_content=matchB.content if matchB else None,

                    diff_ab_content=hAB.content,

                    # 最终 content 用 AB hunk
                    content=hAB.content,
                )

                # 为 LLM Prompt 注入 hunk 级上下文（避免依赖 main.py 的 monkey patch）
                setattr(block, 'diffA_raw', matchA.content if matchA else '')
                setattr(block, 'diffB_raw', matchB.content if matchB else '')

                blocks.append(block)
                block_id += 1

            file_reports.append(FileReport(file_path=file_path, diff_blocks=blocks))

        return file_reports

    # --------------------------
    # 根据行号找 “重叠” hunk
    # --------------------------
    def _find_matching_hunk(self, hunks: List[DiffHunk], target: DiffHunk):
        for h in hunks:
            if (h.start_line <= target.end_line and target.start_line <= h.end_line):
                return h
        return None

    # --------------------------
    # 顶层 parse（MR 模式：diffA/diffB/diffAB 三文件）
    # --------------------------
    def parse(self, diffA_path, diffB_path, diffAB_path):
        diffA = self.parse_diff_file(diffA_path)
        diffB = self.parse_diff_file(diffB_path)

        # 解析 diffAB → {file: [hunks]}
        diffAB = self.parse_diff_file(diffAB_path)

        # 仅基于 diffAB hunk 构建冲突块
        return self.build_diff_blocks(diffA, diffB, diffAB)
