#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
from pathlib import Path


def _truncate(s: str, max_chars: int) -> str:
    if s is None:
        return ""
    s = str(s)
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _guess_lang(file_path: str) -> str:
    if not file_path:
        return ""
    ext = Path(file_path).suffix.lower().lstrip(".")
    return ext if ext else ""


def _append_section(details: list, title: str, content: str):
    """Append a markdown section if content is non-empty."""
    if content:
        details.append(f"### {title}\n\n{content}")


def main():
    ap = argparse.ArgumentParser(description="Render PR comment markdown from result.json")
    ap.add_argument("json_path", help="Path to result.json")
    ap.add_argument("-o", "--output", default="comment.md", help="Output markdown path")
    ap.add_argument("--max-blocks", type=int, default=12, help="Max blocks to render in comment")
    ap.add_argument("--max-text", type=int, default=1800, help="Max chars for long text fields inside comment")
    ap.add_argument("--max-code", type=int, default=8000, help="Max chars for mixed_code snippet inside comment")
    ap.add_argument(
        "--show-empty",
        action="store_true",
        help="If set, show placeholders when some analysis fields are empty",
    )
    args = ap.parse_args()

    data = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    meta = data.get("meta") or {}
    blocks = data.get("res") or []

    marker = meta.get("comment_marker") or "<!-- llm-merge-resolver -->"

    lines = []
    lines.append(marker)
    lines.append("# LLM 冲突消解建议（自动生成）")

    tool = meta.get("tool")
    model = meta.get("model")
    base_url = meta.get("base_url")
    generated_at = meta.get("generated_at")

    info = []
    if tool:
        info.append(f"工具：`{tool}`")
    if model:
        info.append(f"模型：`{model}`")
    if base_url:
        info.append(f"API：`{base_url}`")
    if generated_at:
        info.append(f"生成时间：`{generated_at}`")
    if meta.get("shaA") or meta.get("shaB"):
        info.append(f"SHA(A/B)：`{meta.get('shaA')}` / `{meta.get('shaB')}`")

    if info:
        lines.append("")
        lines.append(" | ".join(info))

    lines.append("")
    lines.append(f"- Diff blocks：**{len(blocks)}**")
    lines.append("")

    if not blocks:
        lines.append("> 未检测到可分析的差异块，或解析结果为空。")
        Path(args.output).write_text("\n".join(lines), encoding="utf-8")
        return

    max_blocks = max(1, args.max_blocks)
    max_text = max(200, args.max_text)
    max_code = max(500, args.max_code)

    for b in blocks[:max_blocks]:
        bid = b.get("id")
        fp = b.get("file_path_branchA") or b.get("file_path_branchB") or "(unknown)"
        locA = b.get("location_branchA") or {}
        locB = b.get("location_branchB") or {}

        mod_type = _truncate(b.get("modification_type") or "", 120)
        suggestion = _truncate(b.get("resolution_suggestion") or "", 240)
        reason = _truncate(b.get("resolution_suggestion_reason") or "", max_text)

        # 新增：把 content / influence 也拿出来渲染
        branchA_content = _truncate(b.get("branchA_content") or "", max_text)
        branchA_reason = _truncate(b.get("branchA_reason") or "", max_text)
        branchA_influence = _truncate(b.get("branchA_influence") or "", max_text)

        branchB_content = _truncate(b.get("branchB_content") or "", max_text)
        branchB_reason = _truncate(b.get("branchB_reason") or "", max_text)
        branchB_influence = _truncate(b.get("branchB_influence") or "", max_text)

        mixed = (b.get("mixed_code") or "").strip()
        if len(mixed) > max_code:
            mixed = mixed[: max_code - 1] + "…"

        lines.append(f"## Block {bid}: `{fp}`")
        if locA.get("startLine") or locA.get("endLine"):
            lines.append(f"- 位置(A)：{locA.get('startLine')}–{locA.get('endLine')}")
        if locB.get("startLine") or locB.get("endLine"):
            lines.append(f"- 位置(B)：{locB.get('startLine')}–{locB.get('endLine')}")
        if mod_type:
            lines.append(f"- 修改类型：{mod_type}")
        if suggestion:
            lines.append(f"- 解决建议：{suggestion}")

        if reason:
            lines.append("")
            lines.append("**建议理由（摘要）**")
            lines.append("")
            lines.append(reason)

        # 统一放进“分析要点”折叠区：内容 / 原因 / 影响
        details = []

        _append_section(details, "BranchA 修改内容（摘要）", branchA_content)
        _append_section(details, "BranchA 修改原因（摘要）", branchA_reason)
        _append_section(details, "BranchA 修改影响（摘要）", branchA_influence)

        _append_section(details, "BranchB 修改内容（摘要）", branchB_content)
        _append_section(details, "BranchB 修改原因（摘要）", branchB_reason)
        _append_section(details, "BranchB 修改影响（摘要）", branchB_influence)

        if args.show_empty:
            # 当你想明确区分“未生成” vs “未展示”时用这个开关
            if not branchA_content:
                _append_section(details, "BranchA 修改内容（摘要）", "_（为空/未生成）_")
            if not branchA_reason:
                _append_section(details, "BranchA 修改原因（摘要）", "_（为空/未生成）_")
            if not branchA_influence:
                _append_section(details, "BranchA 修改影响（摘要）", "_（为空/未生成）_")

            if not branchB_content:
                _append_section(details, "BranchB 修改内容（摘要）", "_（为空/未生成）_")
            if not branchB_reason:
                _append_section(details, "BranchB 修改原因（摘要）", "_（为空/未生成）_")
            if not branchB_influence:
                _append_section(details, "BranchB 修改影响（摘要）", "_（为空/未生成）_")

        if details:
            lines.append("")
            lines.append("<details><summary>分析要点（内容 / 原因 / 影响）</summary>")
            lines.append("")
            lines.extend(details)
            lines.append("")
            lines.append("</details>")

        if mixed:
            lang = _guess_lang(fp)
            lines.append("")
            lines.append("<details><summary>融合后代码（建议）</summary>")
            lines.append("")
            lines.append(f"```{lang}")
            lines.append(mixed)
            lines.append("```")
            lines.append("</details>")

        lines.append("")

    if len(blocks) > max_blocks:
        lines.append(f"_仅展示前 {max_blocks} 个块，完整内容请查看 workflow artifact（output/）。_")

    Path(args.output).write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
