#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import chardet
import argparse
import json
import logging
import os
import datetime
from pathlib import Path
from parser import DiffParser
from analyzer import LLMAnalyzer
from report_generator import ReportGenerator, block_to_dict
from git_merge_diff_extractor import extract_merge_inputs
import subprocess


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def read_text_best_effort(file_path: str) -> str:
    """
    尝试用 UTF-8 / 自动识别编码方式读取文本文件，避免 Win 下 BOM/GBK 崩溃
    """
    with open(file_path, "rb") as f:
        raw = f.read()

    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass

    detected = chardet.detect(raw) or {}
    enc = detected.get("encoding") or ""

    try:
        return raw.decode(enc)
    except Exception:
        return raw.decode("utf-8", errors="replace")


class CodeDiffAnalyzer:
    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1"):
        self.parser = DiffParser()
        self.analyzer = LLMAnalyzer(api_key, base_url)
        self.report_generator = ReportGenerator()

    def analyze_diff_file(self, diff_file_path: str, output_path: str = None, meta=None) -> str:
        diff_content = read_text_best_effort(diff_file_path)
        return self.analyze_diff_content(diff_content, output_path, meta=meta)

    def analyze_diff_content(self, diff_content: str, output_path: str = None, meta=None) -> str:
        """单 diff 文件模式：构建 DiffBlocks -> LLM -> JSON 输出"""
        diff_blocks = self.parser.parse_diff(diff_content)
        return self.analyze_blocks(diff_blocks, output_path, meta=meta)

    def analyze_blocks(self, diff_blocks, output_path: str = None, meta=None) -> str:
        """对已解析的 DiffBlock 列表进行 LLM 分析并输出 JSON 报告（MR 模式/高级入口）"""

        analyzed_blocks = []
        batch_blocks = []
        part = 1

        # 输出目录前缀（目录 + 文件名前缀）
        if output_path:
            output_prefix = Path(output_path).parent / Path(output_path).stem
        else:
            output_prefix = Path("report")

        # LLM 分析 & 按 50 条分割输出（保持你原结构）
        for i, block in enumerate(diff_blocks, 1):
            analyzed_block = self.analyzer.analyze_diff_block(block)
            analyzed_blocks.append(analyzed_block)
            batch_blocks.append(analyzed_block)

            if len(batch_blocks) == 50:
                part_filename = f"{output_prefix}_part_{part}.json"
                with open(part_filename, "w", encoding="utf-8") as f:
                    json.dump({"res": [block_to_dict(b) for b in batch_blocks]},
                              f, ensure_ascii=False, indent=2)
                part += 1
                batch_blocks = []

        if batch_blocks:
            part_filename = f"{output_prefix}_part_{part}.json"
            with open(part_filename, "w", encoding="utf-8") as f:
                json.dump({"res": [block_to_dict(b) for b in batch_blocks]},
                          f, ensure_ascii=False, indent=2)

        # ---------------- 总报告输出 ----------------
        json_report = self.report_generator.generate_json_report(analyzed_blocks, meta=meta)
        summary_report = self.report_generator.generate_summary_report(analyzed_blocks)

        if output_path:
            json_file = str(Path(output_path).with_suffix('.json'))
            with open(json_file, 'w', encoding='utf-8') as f:
                f.write(json_report)

            summary_file = str(Path(output_path).with_suffix('.summary.md'))
            with open(summary_file, 'w', encoding='utf-8') as f:
                f.write(summary_report)

        return json_report


def run_git_diff_AB(repo_path: str, branchA: str, branchB: str) -> str:
    """独立的 git diff A↔B 工具（非 MR 模式使用）"""
    result = subprocess.run(
        ["git", "diff", branchA, branchB],
        cwd=repo_path,
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description='基于大模型的代码差异分析工具')

    parser.add_argument('diff_file', nargs='?', help='git diff文件路径')
    parser.add_argument('-o', '--output', help='输出文件路径')

    # API Key：默认从环境变量读取，避免硬编码泄露
    parser.add_argument(
        '--api-key',
        help='LLM API 密钥（优先从环境变量 OPENROUTER_API_KEY/OPENAI_API_KEY 读取，也可显式传入）',
        default=os.environ.get('OPENROUTER_API_KEY') or os.environ.get('OPENAI_API_KEY')
    )

    parser.add_argument('--base-url', help='API基础URL',
                        default='https://openrouter.ai/api/v1')

    parser.add_argument('--repo', help='仓库路径')
    parser.add_argument('--branchA', help='MR 分支 A')
    parser.add_argument('--branchB', help='MR 分支 B')

    args = parser.parse_args()
    if not args.api_key:
        logger.error('缺少 API Key：请在 GitHub Secrets/环境变量中设置 OPENROUTER_API_KEY（或通过 --api-key 传入）')
        raise SystemExit(2)

    analyzer = CodeDiffAnalyzer(args.api_key, args.base_url)

    # ====================================================================
    #                          MR 模式入口
    # ====================================================================
    if args.repo and args.branchA and args.branchB:
        logger.info("[MR 模式] 自动提取 merge-base / diffA / diffB / diffAB ...")

        # ---- 统一输出文件夹：根据 -o 生成 ----
        if args.output:
            output_dir = Path(args.output).with_suffix("")
        else:
            output_dir = Path("output")

        output_dir.mkdir(parents=True, exist_ok=True)

        merge_inputs = extract_merge_inputs(
            repo_path=args.repo,
            branchA=args.branchA,
            branchB=args.branchB,
            output_dir=str(output_dir)
        )

        base_content = read_text_best_effort(merge_inputs["base"])
        diffA_content = read_text_best_effort(merge_inputs["diffA"])
        diffB_content = read_text_best_effort(merge_inputs["diffB"])
        diffAB_content = read_text_best_effort(merge_inputs["diffAB"])

        analyzer.global_base = base_content
        analyzer.global_diffA = diffA_content
        analyzer.global_diffB = diffB_content
        analyzer.global_diffAB = diffAB_content

        file_reports = analyzer.parser.parse(
            merge_inputs["diffA"],
            merge_inputs["diffB"],
            merge_inputs["diffAB"]
        )
        diffblocks = []
        for fr in file_reports:
            diffblocks.extend(fr.diff_blocks)

        logger.info(f"[MR] 解析得到差异块数量：{len(diffblocks)}")

        # 将 BASE 内容注入到每个块（diffA/diffB/diffAB 的 hunk 级内容已在 parser.build_diff_blocks 中注入）
        for b in diffblocks:
            setattr(b, 'base_content', base_content)

        # -------- MR 模式输出到 output_dir/result.json --------
        result_json_path = output_dir / "result.json"

        # ---------------- 生成报告元信息（用于 GitHub Actions 幂等评论 & 追踪） ----------------
        def _git_rev_parse(ref: str):
            try:
                r = subprocess.run(["git", "rev-parse", ref], cwd=args.repo, capture_output=True, text=True)
                if r.returncode == 0:
                    return r.stdout.strip()
            except Exception:
                pass
            return None

        meta = {
            "tool": "llm-merge-resolver",
            "schema_version": "1.0",
            "comment_marker": "<!-- llm-merge-resolver -->",
            "mode": "mr",
            "repo": args.repo,
            "branchA": args.branchA,
            "branchB": args.branchB,
            "shaA": _git_rev_parse(args.branchA),
            "shaB": _git_rev_parse(args.branchB),
            "base_url": args.base_url,
            "model": getattr(analyzer.analyzer, "model", None),
            "generated_at": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }

        logger.info("[MR LLM 分析] 开始处理差异块…")
        _ = analyzer.analyze_blocks(diffblocks, str(result_json_path), meta=meta)
        return

    # ====================================================================
    #                  单 diff 文件模式（保持原逻辑）
    # ====================================================================
    if args.diff_file:
        meta = {
            "tool": "llm-merge-resolver",
            "schema_version": "1.0",
            "comment_marker": "<!-- llm-merge-resolver -->",
            "mode": "single_diff",
            "diff_file": args.diff_file,
            "base_url": args.base_url,
            "model": getattr(analyzer.analyzer, "model", None),
            "generated_at": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }
        _ = analyzer.analyze_diff_file(args.diff_file, args.output, meta=meta)
        return

    logger.error("请提供 diff_file 或 (--repo --branchA --branchB) 之一")


if __name__ == "__main__":
    main()
