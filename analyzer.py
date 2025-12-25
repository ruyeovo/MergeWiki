#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import logging
from typing import Dict
from openai import OpenAI
from models import DiffBlock
from style_analyzer import StyleDetector

logger = logging.getLogger(__name__)


class LLMAnalyzer:
    """大模型分析器"""

    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1"):
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
        )
        self.model = "openai/gpt-4o-mini"

    def analyze_diff_block(self, diff_block: DiffBlock) -> DiffBlock:
        """分析单个差异块"""
        try:
            prompt = self._create_analysis_prompt(diff_block)

            completion = self.client.chat.completions.create(
                extra_headers={
                    "HTTP-Referer": "https://code-diff-analyzer.local",
                    "X-Title": "Code Diff Analyzer",
                },
                model=self.model,
                messages=[
                    {"role": "system",
                    "content": "你是一个专业的代码评审专家，擅长分析代码开发Merge Request过程产生的代码冲突问题。请仔细分析代码差异，提供专业的分类和建议。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=4000
            )

            response = completion.choices[0].message.content

            analysis_result = self._parse_llm_response(response)

            diff_block.modification_type = analysis_result.get('modification_type', '未知修改类型')

            diff_block.branchA_content = analysis_result.get('branchA_content', '')
            diff_block.branchA_reason = analysis_result.get('branchA_reason', '')
            diff_block.branchA_influence = analysis_result.get('branchA_influence', '')

            diff_block.branchB_content = analysis_result.get('branchB_content', '')
            diff_block.branchB_reason = analysis_result.get('branchB_reason', '')
            diff_block.branchB_influence = analysis_result.get('branchB_influence', '')

            diff_block.resolution_suggestion = analysis_result.get('resolution_suggestion', '建议不可用')
            diff_block.resolution_suggestion_reason = analysis_result.get('resolution_suggestion_reason', '')

            # -----------------------------
            # ★★★ 关键新增：策略分流逻辑 ★★★
            # -----------------------------
            suggestion = diff_block.resolution_suggestion

            if "保留 branchA" in suggestion:
                diff_block.mixed_code = self._get_original_code_of_branch(diff_block, target="A")
                return diff_block

            if "保留 branchB" in suggestion:
                diff_block.mixed_code = self._get_original_code_of_branch(diff_block, target="B")
                return diff_block

            # ======================================================
            # 默认路径：进入两阶段生成（原逻辑保持不变）
            # ======================================================
            mixed_code_from_analysis = analysis_result.get('mixed_code', '').strip()

            if not mixed_code_from_analysis or mixed_code_from_analysis.lower() == "mixed_code":
                diff_block.mixed_code = self._generate_mixed_code(diff_block)
            else:
                diff_block.mixed_code = mixed_code_from_analysis

            return diff_block

        except Exception as e:
            diff_block.modification_type = "分析失败"
            diff_block.resolution_suggestion = "请手动分析此差异"
            diff_block.resolution_suggestion_reason = ""
            return diff_block


    # =====================================================================
    # ★★★ 最小化修改 —— 在原先 prompt 顶部插入 BASE/diffA/diffB/diffAB ★★★
    # =====================================================================
    def _create_analysis_prompt(self, diff_block: DiffBlock) -> str:

        # 由 main.py 注入的内容（你选择的方案 1）
        base_content = getattr(diff_block, "base_content", "(No BASE content)")
        diffA_raw = getattr(diff_block, "diffA_raw", "(No diffA)")
        diffB_raw = getattr(diff_block, "diffB_raw", "(No diffB)")
        diffAB_raw = getattr(diff_block, "diff_ab_content", "(No diffAB)")

        # === 第一部分：新增的四类输入（严格最小新增） ===
        prefix = f"""
==================== BASE（共同祖先版本） ====================
{base_content}

==================== DIFF A（BASE → branchA） ====================
{diffA_raw}

==================== DIFF B（BASE → branchB） ====================
{diffB_raw}

==================== DIFF AB（branchA ↔ branchB） ====================
{diffAB_raw}

"""
        # ===== One-shot 示例（不会影响 START/END 解析） =====
        example_oneshot = """
==================== 示例（One-Shot） ====================
以下是一个典型示例，展示你必须使用的回答格式：  
假设文件名为 calculator.py：
- BASE 内容（master）：含 add() / subtract()
- branchA：添加了 multiply()
- branchB：添加了 divide()
- 最终建议：将 multiply 与 divide 都融合进入最终版本
--------------------------------------
【示例输入差异】
BASE（master）:
    def add(a, b):
        return a + b

    def subtract(a, b):
        return a - b

branchA 修改内容（diffA）:
    + def multiply(a, b):
    +     return a * b

branchB 修改内容（diffB）:
    + def divide(a, b):
    +     return a / b

--------------------------------------
【示例输出（请严格按照此格式）】
MODIFICATION_TYPE_START
功能新增/删除
MODIFICATION_TYPE_END

MODIFICATION_CONTENT_START
branchA 修改内容：添加了 multiply(a, b) 函数，用于实现乘法功能。
MODIFICATION_CONTENT_END

MODIFICATION_REASON_START
branchA 修改原因：branchA 添加 multiply 的原因是扩展基础计算能力，使 calculator 支持乘法。
MODIFICATION_REASON_END

MODIFICATION_INFLUENCE_START
branchA 修改影响：branchA 的新增功能不会与 add/subtract 产生冲突，只会扩展接口。
MODIFICATION_INFLUENCE_END

INTRUSIVE_CONTENT_START
branchB 修改内容：添加了 divide(a, b) 函数，用于实现除法功能。
INTRUSIVE_CONTENT_END

INTRUSIVE_REASON_START
branchB 修改原因：branchB 添加 divide 的原因是进一步完善运算集，使其包含除法操作。
INTRUSIVE_REASON_END

INTRUSIVE_INFLUENCE_START
branchB 修改影响：branchB 的 divide 逻辑同样独立存在，但需要注意除零异常。
INTRUSIVE_INFLUENCE_END

SUGGESTION_START
branchA/branchB 融合：最终建议的融合版本应包含 add、subtract、multiply、divide 四个函数，同时建议为 divide 添加除零检测，确保健壮性。
SUGGESTION_END
==================== 示例结束 ====================
"""

        # === 第二部分：保持你原有 prompt 完整不动 ===
        body = f"""
请仔细分析以下代码差异，并提供完整详细的分析报告。

**重要说明：请务必理解git diff格式**
- 这是 branchA 与 branchB 的差异对比
- branchB 文件路径: {diff_block.file_path_branchB}
- branchA 文件路径: {diff_block.file_path_branchA}
- 位置信息：
  - branchB 修改位置: 第{diff_block.location_branchB.start_line}-{diff_block.location_branchB.end_line}行
  - branchA 修改位置: 第{diff_block.location_branchA.start_line}-{diff_block.location_branchA.end_line}行
- 在差异内容中：
  - 以"+"开头的行：表示 branchA 新增的内容
  - 以"-"开头的行：表示 branchB 原有但 branchA 删除的内容

**差异内容：**
{diff_block.content}

请严格按照以下格式回答，每个部分都必须提供完整内容，不要添加任何markdown格式符号：

MODIFICATION_TYPE_START
从以下类型中选择最合适的一个或多个：
参数相关修改|日志相关修改|安全相关修改|性能优化相关|功能新增/删除|配置文件修改|依赖库更新|构建系统修改|测试相关修改|文档修改|代码重构|Bug修复|兼容性修改|其他
MODIFICATION_TYPE_END

MODIFICATION_CONTENT_START
branchA 修改内容分析：branchA 新增与删除内容分别是什么？
MODIFICATION_CONTENT_END

MODIFICATION_REASON_START
branchA 修改原因分析：为什么 branchA 要进行这些修改？
MODIFICATION_REASON_END

MODIFICATION_INFLUENCE_START
branchA 修改影响分析：这些修改带来什么影响？
MODIFICATION_INFLUENCE_END

INTRUSIVE_CONTENT_START
branchB 修改内容分析：branchB 的内容是什么？是否属于侵入式？
INTRUSIVE_CONTENT_END

INTRUSIVE_REASON_START
branchB 修改原因分析：为什么 branchB 要进行这些修改？
INTRUSIVE_REASON_END

INTRUSIVE_INFLUENCE_START
branchB 修改影响分析：branchB 的内容对最终合并有何影响？
INTRUSIVE_INFLUENCE_END

SUGGESTION_START
请结合实际工程经验，选择最合理的建议：
[保留 branchA 代码|保留 branchB 代码|branchA/branchB 融合|需要手动审核]
并说明理由。
SUGGESTION_END
"""

        return prefix + example_oneshot + body

    # =====================================================================
    # 解析、二阶段生成保持不改（你的原逻辑）
    # =====================================================================
    def _parse_llm_response(self, response: str) -> Dict[str, str]:
        result = {}

        def extract(start, end):
            m = re.search(rf'{start}\s*(.*?)\s*{end}', response, re.DOTALL)
            return m.group(1).strip() if m else ""

        try:
            result["modification_type"] = extract("MODIFICATION_TYPE_START", "MODIFICATION_TYPE_END")

            result["branchA_content"] = extract("MODIFICATION_CONTENT_START", "MODIFICATION_CONTENT_END")
            result["branchA_reason"] = extract("MODIFICATION_REASON_START", "MODIFICATION_REASON_END")
            result["branchA_influence"] = extract("MODIFICATION_INFLUENCE_START", "MODIFICATION_INFLUENCE_END")

            result["branchB_content"] = extract("INTRUSIVE_CONTENT_START", "INTRUSIVE_CONTENT_END")
            result["branchB_reason"] = extract("INTRUSIVE_REASON_START", "INTRUSIVE_REASON_END")
            result["branchB_influence"] = extract("INTRUSIVE_INFLUENCE_START", "INTRUSIVE_INFLUENCE_END")

            suggestion_raw = extract("SUGGESTION_START", "SUGGESTION_END")
            if "：" in suggestion_raw:
                p = suggestion_raw.split("：", 1)
                result["resolution_suggestion"] = p[0].strip()
                result["resolution_suggestion_reason"] = p[1].strip()
            else:
                result["resolution_suggestion"] = suggestion_raw
                result["resolution_suggestion_reason"] = ""

        except Exception as e:
            logger.error(f"解析LLM响应时出错: {e}")

        return result

    def _get_original_code_of_branch(self, diff_block: DiffBlock, target="A") -> str:
        
        diff_text = diff_block.content
        if not diff_text:
            return ""

        raw_lines = []

        for line in diff_text.splitlines():
            if not line:
                continue

            # 跳过 @@ 行
            if line.startswith("@@"):
                continue

            prefix = line[0]
            content = line[1:]  # 去掉 + / - / 空格

            if target == "A":
                # branchA = 删除(-) + 上下文( )
                if prefix in ("-", " "):
                    raw_lines.append(content)

            elif target == "B":
                # branchB = 新增(+) + 上下文( )
                if prefix in ("+", " "):
                    raw_lines.append(content)

        return "\n".join(raw_lines)


    def _generate_mixed_code(self, diff_block: DiffBlock) -> str:
        try:
            # =========================================================
            # Helper: 从原始 diff 文本中还原出特定分支的代码样式
            # =========================================================
            def extract_raw_code_from_diff(diff_text: str, target: str) -> str:
                """
                target="A": 提取 (-) 行和 ( ) 上下文行
                target="B": 提取 (+) 行和 ( ) 上下文行
                """
                if not diff_text: return ""
                
                raw_lines = []
                for line in diff_text.splitlines():
                    if not line: continue
                    
                    # 跳过 diff 头信息 (@@ ... @@)
                    if line.startswith("@@"): continue
                    
                    prefix = line[0]
                    content = line[1:] # 去掉第一个字符 (+/-/空格)
                    
                    if target == "B":
                        # Branch B 由 (+) 和 (空格) 组成
                        if prefix in ('+', ' '):
                            raw_lines.append(content)
                    elif target == "A":
                        # Branch A 由 (-) 和 (空格) 组成
                        if prefix in ('-', ' '):
                            raw_lines.append(content)
                            
                return "\n".join(raw_lines)

            # ★★★ 1. 动态决定风格参考源 (严格关键词匹配) ★★★
            suggestion = diff_block.resolution_suggestion.strip()
            
            # 默认：从 Raw Diff 中提取 Branch B 的样子（通常 B 是为了合并进来的，保留 B 风格最安全）
            # 注意：这里我们使用 diff_block.content (这是 parser 读取的原始 diff，包含 + - 空格)
            raw_diff_text = diff_block.content
            target_branch = "B" # 默认取 B
            style_source_name = "Branch B (Default)"

            if "保留 branchA 代码" in suggestion:
                target_branch = "A"
                style_source_name = "Branch A"
            elif "保留 branchB 代码" in suggestion:
                target_branch = "B"
                style_source_name = "Branch B"
            elif "branchA/branchB 融合" in suggestion:
                # 融合情况：根据你之前的要求，优先参考 A 的风格
                target_branch = "A"
                style_source_name = "Branch A (Merge Strategy)"

            # ★ 关键修正：从原始 Diff 中还原代码，而不是用 LLM 的总结 ★
            reference_code = extract_raw_code_from_diff(raw_diff_text, target_branch)
            
            # 兜底：如果提取出来的代码是空的（比如纯删除操作），尝试取另一个分支
            if not reference_code.strip():
                fallback = "A" if target_branch == "B" else "B"
                reference_code = extract_raw_code_from_diff(raw_diff_text, fallback)
                style_source_name += f" (Fallback to {fallback})"

            logger.info(f"差异块 {diff_block.id} [{suggestion}] -> 风格提取源: {style_source_name}")

            # ★★★ 2. 调用风格提取器 ★★★
            # 现在的 reference_code 是带有原始缩进（例如 12 个空格）的纯代码文本
            detector = StyleDetector(reference_code)
            style_info = detector.detect()
            
            # 生成 Prompt 风格约束片段
            style_prompt_section = StyleDetector.generate_style_prompt(style_info)

            # ★★★ 3. 构建 Prompt (保持不变) ★★★
            prompt = f"""
下面是 branchA 与 branchB 的完整差异与分析结果，请输出最终应采用的完整代码。

【branchA 修改内容】
{diff_block.branchA_content}

【branchA 修改原因】
{diff_block.branchA_reason}

【branchB 修改内容】
{diff_block.branchB_content}

【branchB 修改原因】
{diff_block.branchB_reason}

【branchA 修改影响】
{diff_block.branchA_influence}

【branchB 修改影响】
{diff_block.branchB_influence}

【最终建议】
{diff_block.resolution_suggestion}

【理由】
{diff_block.resolution_suggestion_reason}

【原始差异内容 (供参考逻辑)】
{diff_block.content}

{style_prompt_section}

【代码生成任务】

请根据【最终建议】和【严格代码风格约束】生成融合后的代码：

1. **内容要求**：
   - 必须包含建议保留的所有逻辑。
   - 不要添加 markdown 标记（如 ```java）。
   - 只输出代码本身。

2. **格式要求 (CRITICAL)**：
   - 严格按照上文计算出的 `基准缩进` 和 `缩进层级` 进行排版。
   - **绝对禁止**自动格式化代码（如调整对齐、删除尾部空格）。
   - 保持原有的换行和括号风格。

请输出融合后的完整代码，并用以下格式包裹：

MIXED_CODE_START
（完整代码）
MIXED_CODE_END
"""

            completion = self.client.chat.completions.create(
                model=self.model,
                temperature=0.2, 
                messages=[
                    {"role": "system", "content": "你是一名代码合并专家，特别擅长精确控制代码缩进和格式。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=4000
            )

            response = completion.choices[0].message.content
            match = re.search(r'MIXED_CODE_START\s*(.*?)\s*MIXED_CODE_END', response, re.DOTALL)
            # 保留行首缩进
            return match.group(1).strip('\n') if match else ""

        except Exception as e:
            logger.error(f"生成融合代码失败: {e}")
            return ""