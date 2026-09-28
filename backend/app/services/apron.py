"""机坪巡查业务规则：状态流转、字段校验与筛选口径都收在这里。

列表、按区域汇总、运营概览的待处理/异常量全部走同一套口径（见
``is_pending`` / ``is_abnormal`` 与 ``_filter_rows``），保证三处数字一致。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "apron"
REQUIRED_FIELDS = ["巡查单号", "巡查区域", "巡查人员"]
# 提交结果时可登记的明细字段；作废不清空，保留首次登记的内容。
DETAIL_FIELDS = ["巡查日期", "巡查项目", "发现问题数", "巡查时长"]
STATUS_ORDER = ["待派发", "巡查中", "已提交", "已作废"]
DONE_STATUS = "已提交"
VOID_STATUS = "已作废"
# 终态：进入后不再接受任何流转动作（提交与作废互斥，也不能重复作废）。
TERMINAL_STATUSES = (DONE_STATUS, VOID_STATUS)
ACTION_RULES = {"派发巡查": "巡查中", "提交结果": "已提交", "作废巡查": "已作废"}


def is_pending(row: dict[str, Any]) -> bool:
    """待处理口径：待派发、巡查中算待处理；已提交、已作废都算办结。"""
    return row.get("status") not in TERMINAL_STATUSES


def is_abnormal(row: dict[str, Any]) -> bool:
    """异常量口径：已作废的巡查单算异常，其余状态都不算。"""
    return row.get("status") == VOID_STATUS


def _sync_flags(entry: dict[str, Any]) -> dict[str, Any]:
    """把冗余的 pending/abnormal 标志收敛到状态口径，避免各页数字打架。"""
    entry["pending"] = is_pending(entry)
    entry["abnormal"] = is_abnormal(entry)
    return entry


class ApronService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        area: str | None = None,
        inspector: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._filter_rows(keyword=keyword, area=area, inspector=inspector, status=status)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def area_summary(
        self,
        *,
        keyword: str | None = None,
        area: str | None = None,
        inspector: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """按巡查区域汇总；与列表共用同一份筛选结果，逐条入组不会重复计同一条。"""
        rows = self._filter_rows(keyword=keyword, area=area, inspector=inspector, status=status)
        groups: dict[str, dict[str, Any]] = {}
        for row in rows:
            name = str(row.get("巡查区域") or "").strip() or "未填写区域"
            group = groups.setdefault(
                name,
                {"巡查区域": name, "巡查单数": 0, "待处理": 0, "异常量": 0},
            )
            group["巡查单数"] += 1
            if is_pending(row):
                group["待处理"] += 1
            if is_abnormal(row):
                group["异常量"] += 1
        return list(groups.values())

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS + DETAIL_FIELDS:
            value = values.get(field)
            if str(value or "").strip():
                entry[field] = value
        entry["status"] = STATUS_ORDER[0]
        _sync_flags(entry)
        rows.append(entry)
        return entry, []

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"巡查单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于机坪巡查可执行范围"

        current = str(entry.get("status") or "")
        # 已提交与已作废互为终态：提交后不能作废、作废后不能提交，作废也只能做一次。
        if current == VOID_STATUS:
            if action == "作废巡查":
                return None, "巡查单已作废，重复作废不会再次生效；首次作废结果仍保留"
            return None, "巡查单已作废，作废与提交结果互斥，不能再执行「提交结果」"
        if current == DONE_STATUS:
            if action == "作废巡查":
                return None, "巡查单已提交结果，提交与作废互斥，不能再执行「作废巡查」"
            return None, "巡查单已提交结果，重复提交不会再次生效；首次提交结果仍保留"

        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        # 派发只能从待派发发起，防止越序流转。
        if action == "派发巡查" and current != "待派发":
            return None, f"巡查单当前状态为「{current}」，无需重复派发"

        if action == "提交结果":
            values = values or {}
            for field in DETAIL_FIELDS:
                value = values.get(field)
                if str(value or "").strip():
                    entry[field] = value
        # 作废只动状态与标志位，巡查项目、发现问题数等明细原样保留。

        entry["status"] = target
        _sync_flags(entry)
        return entry, f"巡查单已{action}"

    def _filter_rows(
        self,
        *,
        keyword: str | None,
        area: str | None,
        inspector: str | None,
        status: str | None,
    ) -> list[dict[str, Any]]:
        """列表与区域汇总共用的筛选口径，改口径只改这一处。"""
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("巡查单号", ""))]
        if area:
            rows = [row for row in rows if area in str(row.get("巡查区域", ""))]
        if inspector:
            rows = [row for row in rows if inspector in str(row.get("巡查人员", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows
