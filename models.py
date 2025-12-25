from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Location:
    start_line: int
    end_line: int


@dataclass
class DiffHunk:
    file_path: str
    start_line: int
    end_line: int
    content: str


@dataclass
class DiffBlock:
    file_path_branchA: Optional[str] = None
    file_path_branchB: Optional[str] = None

    location_branchA: Optional[Location] = None
    location_branchB: Optional[Location] = None

    branchA_content: Optional[str] = None
    branchB_content: Optional[str] = None

    branchA_reason: Optional[str] = None
    branchB_reason: Optional[str] = None

    branchA_influence: Optional[str] = None
    branchB_influence: Optional[str] = None

    diff_ab_content: Optional[str] = None

    # 你的 Step6 新增字段
    content: Optional[str] = None
    id: Optional[int] = None
    resolution_suggestion: Optional[str] = None
    resolution_suggestion_reason: Optional[str] = None
    mixed_code: Optional[str] = None


@dataclass
class FileReport:
    file_path: str
    diff_blocks: List[DiffBlock]


@dataclass
class AnalysisReport:
    merge_base_commit: str
    file_reports: List[FileReport]
    summary: Optional[str] = None
