"""机坪巡查业务规则：状态流转、字段校验与筛选口径都收在这里。

口径约定（列表、按巡查区域汇总、运营总览三处共用同一份数据源）：
- 待处理：状态为「待派发」「巡查中」的巡查单；
- 已提交：状态为「已提交」；已作废：状态为「已作废」；
- 「提交结果」与「作废巡查」互斥，已提交或已作废后都是终态，不可再流转；
- 作废只改状态，不清除巡查项目、发现问题数等已登记明细。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "apron"
REQUIRED_FIELDS = ["巡查单号", "巡查区域", "巡查人员"]
# 登记时可一并填写的选填明细
OPTIONAL_FIELDS = ["巡查日期", "巡查项目", "发现问题数", "巡查时长"]
# 提交结果时允许补充/覆盖的明细字段
RESULT_FIELDS = ["巡查日期", "巡查项目", "发现问题数", "巡查时长", "巡查人员"]
STATUS_ORDER = ["待派发", "巡查中", "已提交", "已作废"]
PENDING_STATUSES = {"待派发", "巡查中"}
SUBMITTED = "已提交"
VOIDED = "已作废"
ACTION_RULES = {"派发巡查": "巡查中", "提交结果": SUBMITTED, "作废巡查": VOIDED}
# 每个当前状态允许执行的动作；已提交、已作废为终态，不放任何动作
ALLOWED_ACTIONS: dict[str, list[str]] = {
    "待派发": ["派发巡查", "作废巡查"],
    "巡查中": ["提交结果", "作废巡查"],
    SUBMITTED: [],
    VOIDED: [],
}


def _is_pending(status: Any) -> bool:
    return str(status or "") in PENDING_STATUSES


# 把待处理口径注册给数据仓库，运营总览与列表共用同一份状态定义
store.register_pending_statuses(MODULE, PENDING_STATUSES)


class ApronService:
    # ---- 筛选口径：列表、统计、导出共用，保证三处数字一致 ----
    def _filter(
        self,
        *,
        keyword: str | None = None,
        area: str | None = None,
        inspector: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
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
        rows = self._filter(keyword=keyword, area=area, inspector=inspector, status=status)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def stats(
        self,
        *,
        keyword: str | None = None,
        area: str | None = None,
        inspector: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """按当前筛选条件统计；按巡查区域分组时每条巡查单只归入它所属区域一次，不重复计数。"""
        rows = self._filter(keyword=keyword, area=area, inspector=inspector, status=status)
        area_map: dict[str, dict[str, int]] = {}
        for row in rows:
            row_status = str(row.get("status") or "")
            area_name = str(row.get("巡查区域") or "未填写区域")
            bucket = area_map.setdefault(
                area_name,
                {"area": area_name, "total": 0, "pending": 0, "submitted": 0, "voided": 0},
            )
            bucket["total"] += 1
            if _is_pending(row_status):
                bucket["pending"] += 1
            elif row_status == SUBMITTED:
                bucket["submitted"] += 1
            elif row_status == VOIDED:
                bucket["voided"] += 1
        return {
            "total": len(rows),
            "pending": sum(1 for row in rows if _is_pending(row.get("status"))),
            "submitted": sum(1 for row in rows if row.get("status") == SUBMITTED),
            "voided": sum(1 for row in rows if row.get("status") == VOIDED),
            "areas": list(area_map.values()),
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
            value = values.get(field)
            if value is not None and str(value).strip() != "":
                entry[field] = value
        entry["status"] = STATUS_ORDER[0]
        entry["巡查状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"巡查单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于机坪巡查可执行范围"

        current = str(entry.get("status") or "")
        # 终态拦截：作废与提交结果互斥，重复操作只保留第一次结果并给出说明
        if current == VOIDED:
            return None, "该巡查单已作废，首次作废结果已保留；重复作废不会再次生效，也不能再提交结果"
        if current == SUBMITTED:
            return None, "该巡查单已提交结果，提交结果与作废互斥；不能重复提交，也不能再作废"
        if action not in ALLOWED_ACTIONS.get(current, []):
            return None, f"巡查单当前为「{current}」状态，不允许执行「{action}」"

        if action == "提交结果":
            # 提交时把巡查结果明细并入巡查单，明细缺失的字段保留原值
            for field in RESULT_FIELDS:
                value = (values or {}).get(field)
                if value is not None and str(value).strip() != "":
                    entry[field] = value

        target = ACTION_RULES[action]
        entry["status"] = target
        entry["巡查状态"] = target
        entry["pending"] = _is_pending(target)
        entry["abnormal"] = target == VOIDED
        return entry, f"巡查单已{action}"
