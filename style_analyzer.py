#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from collections import Counter
from typing import Tuple, Dict

class StyleDetector:
    def __init__(self, code_snippet: str):
        # 过滤掉空行，避免干扰判断
        if not code_snippet:
            self.lines = []
        else:
            self.lines = [line for line in code_snippet.split('\n') if line.strip()]

    def detect(self) -> Dict:
        """
        自动检测代码片段的风格信息
        """
        if not self.lines:
            return {
                "base_indent": "",
                "indent_size": 4,
                "indent_char": " ",
                "indent_type_desc": "4 spaces",
                "one_unit_str": "    "
            }

        base_indent = self._get_base_indent()
        indent_size, indent_char = self._detect_indent_unit()
        
        indent_type_desc = "Tab" if indent_char == '\t' else "Space"
        one_unit_str = indent_char * indent_size

        return {
            "base_indent": base_indent,         # 基准缩进字符串（例如 "            "）
            "base_indent_len": len(base_indent),# 基准缩进长度
            "indent_size": indent_size,         # 缩进单位（例如 4）
            "indent_char": indent_char,         # 缩进字符
            "indent_type_desc": indent_type_desc, # 描述文字
            "one_unit_str": one_unit_str        # 单层缩进字符串
        }

    def _get_base_indent(self) -> str:
        """获取第一行代码的基准缩进（用于锚定）"""
        if not self.lines:
            return ""
        # 找到第一个非空行的缩进
        for line in self.lines:
            match = re.match(r"^(\s*)", line)
            if match:
                return match.group(1)
        return ""

    def _detect_indent_unit(self) -> Tuple[int, str]:
        """推断缩进单位"""
        indents = []
        for line in self.lines:
            match = re.match(r"^(\s*)", line)
            if match:
                indents.append(match.group(1))

        if not indents:
            return 4, " "

        # 1. 检测类型：Tab 还是 Space
        all_chars = "".join(indents)
        if not all_chars:
            return 4, " " # 默认
            
        if all_chars.count('\t') > all_chars.count(' '):
            indent_char = '\t'
        else:
            indent_char = ' '

        # 2. 检测步长
        lengths = [len(i) for i in indents]
        diffs = []
        for i in range(len(lengths) - 1):
            diff = abs(lengths[i+1] - lengths[i])
            if diff > 0:
                diffs.append(diff)
        
        if not diffs:
            # 简单启发式
            if lengths and lengths[0] > 0:
                return (4 if lengths[0] % 4 == 0 else 2), indent_char
            return 4, indent_char

        common_diff = Counter(diffs).most_common(1)[0][0]
        return common_diff, indent_char

    @staticmethod
    def generate_style_prompt(style_info: Dict) -> str:
        """
        根据检测到的风格，生成注入给 LLM 的 Prompt 文本
        """
        char_name = "Tab 制表符" if style_info['indent_char'] == '\t' else "Space 空格"
        
        return f"""
【严格代码风格约束（脚本自动提取）】
为了保持 Git Blame 连贯性，你必须**强制**执行以下格式规则：

1. **基准缩进 (Base Indent)**：
   - 生成代码的第一行（及其同级代码）必须严格以 **{style_info['base_indent_len']} 个{char_name}** 开头。
   - 参考基准前缀字符串："{style_info['base_indent']}" (请把引号内的空白作为起跑线)

2. **缩进层级 (Indent Unit)**：
   - 代码块内部每一层嵌套，必须增加 **{style_info['indent_size']} 个{char_name}**。
   - 禁止使用混合缩进（如混用 Tab 和 Space）。

3. **对齐锚点**：
   - 请确保输出的代码可以无缝填入以下结构中：
     {style_info['base_indent']}// 你的代码从这里开始
     {style_info['base_indent']}if (...) {{
     {style_info['base_indent']}{style_info['one_unit_str']}// 内部逻辑
     {style_info['base_indent']}}}
"""