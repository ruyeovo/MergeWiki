#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from typing import List, Optional, Dict, Any
from models import DiffBlock


def block_to_dict(block):
    return {
        "id": getattr(block, "id", None),

        "file_path_branchA": block.file_path_branchA,
        "file_path_branchB": block.file_path_branchB,

        "location_branchA": {
            "startLine": block.location_branchA.start_line,
            "endLine": block.location_branchA.end_line
        },
        "location_branchB": {
            "startLine": block.location_branchB.start_line,
            "endLine": block.location_branchB.end_line
        },

        "modification_type": block.modification_type,

        # 保持兼容：content 默认是 block.content（通常是 diffAB hunk）
        "content": block.content,

        "branchA_content": block.branchA_content,
        "branchA_reason": block.branchA_reason,
        "branchA_influence": block.branchA_influence,

        "branchB_content": block.branchB_content,
        "branchB_reason": block.branchB_reason,
        "branchB_influence": block.branchB_influence,

        "resolution_suggestion": block.resolution_suggestion,
        "resolution_suggestion_reason": block.resolution_suggestion_reason,

        "mixed_code": block.mixed_code
    }


class ReportGenerator:
    def generate_json_report(self, diff_blocks: List[DiffBlock], meta: Optional[Dict[str, Any]] = None) -> str:
        """
        输出结构化 JSON：

        {
          "meta": {...},
          "res": [ ... ]
        }

        说明：
        - 继续保留 top-level 的 `res` 以兼容你现有解析/下游工具；
        - 新增 `meta` 用于 GitHub Actions 幂等评论、版本追踪、运行上下文等；
        - meta 为空时输出 {}，不影响旧逻辑。
        """
        report_data = {
            "meta": meta or {},
            "res": [block_to_dict(b) for b in diff_blocks],
        }
        return json.dumps(report_data, ensure_ascii=False, indent=2)

    def generate_summary_report(self, diff_blocks: List[DiffBlock]) -> str:
        type_stats = {}
        suggestion_stats = {}

        for block in diff_blocks:
            mod_type = block.modification_type.strip() if block.modification_type else ""
            if mod_type:
                type_stats[mod_type] = type_stats.get(mod_type, 0) + 1

        for block in diff_blocks:
            suggestion = block.resolution_suggestion.strip() if block.resolution_suggestion else ""
            if suggestion:
                suggestion_stats[suggestion] = suggestion_stats.get(suggestion, 0) + 1

        branchA_files = set(block.file_path_branchA for block in diff_blocks)
        branchB_files = set(block.file_path_branchB for block in diff_blocks)

        summary = f"""
# 代码差异分析汇总报告

## 总体统计
- 总差异块数量: {len(diff_blocks)}
- 涉及 branchA 文件数量: {len(branchA_files)}
- 涉及 branchB 文件数量: {len(branchB_files)}

## 修改类型分布
"""
        for mod_type, count in sorted(type_stats.items(), key=lambda x: x[1], reverse=True):
            summary += f"- {mod_type}: {count}个\n"

        summary += "\n## 解决建议分布\n"
        for suggestion, count in sorted(suggestion_stats.items(), key=lambda x: x[1], reverse=True):
            summary += f"- {suggestion}: {count}个\n"

        return summary
