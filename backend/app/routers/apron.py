"""机坪巡查接口：维护巡查单，覆盖派发巡查、提交结果、作废巡查等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.apron import ApronService

router = APIRouter(prefix="/api/apron", tags=["机坪巡查"])

service = ApronService()

LIST_FIELDS = ["巡查单号", "巡查区域", "巡查人员", "巡查日期", "巡查项目", "发现问题数", "巡查时长", "巡查状态"]
STATUSES = ["待派发", "巡查中", "已提交", "已作废"]


def _clean(value: str | None) -> str | None:
    """空白筛选条件按未填写处理，避免“ ”筛掉全部数据。"""
    if value is None:
        return None
    value = value.strip()
    return value or None


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按巡查单号检索"),
    area: str | None = Query(default=None, description="按巡查区域检索"),
    inspector: str | None = Query(default=None, description="按巡查人员检索"),
    status: str | None = Query(default=None, description="待派发、巡查中、已提交、已作废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按巡查单号、巡查区域、巡查人员与状态过滤机坪巡查列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=_clean(keyword),
        area=_clean(area),
        inspector=_clean(inspector),
        status=_clean(status),
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def entry_stats(
    keyword: str | None = Query(default=None, description="按巡查单号检索"),
    area: str | None = Query(default=None, description="按巡查区域检索"),
    inspector: str | None = Query(default=None, description="按巡查人员检索"),
    status: str | None = Query(default=None, description="待派发、巡查中、已提交、已作废"),
) -> dict[str, Any]:
    """待处理、已提交、已作废与按巡查区域分组汇总。

    与列表共用同一份筛选口径：传入与列表相同的筛选条件时，汇总数字必然等于列表条数，
    每条巡查单在区域分组里只计一次，不会重复显示。
    """
    return service.stats(
        keyword=_clean(keyword),
        area=_clean(area),
        inspector=_clean(inspector),
        status=_clean(status),
    )


@router.get("/export")
def export_entries(
    keyword: str | None = None,
    area: str | None = None,
    inspector: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """导出机坪巡查清单：返回当前筛选条件下的全量数据，口径与列表一致。"""
    items, total = service.list_entries(
        keyword=_clean(keyword),
        area=_clean(area),
        inspector=_clean(inspector),
        status=_clean(status),
        page=1,
        size=10000,
    )
    return {"module": "apron", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条巡查单明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"巡查单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条巡查单，缺字段时说明原因而不是静默丢弃；巡查单号为空直接报错。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        raise HTTPException(status_code=400, detail=f"缺少必填字段：{'、'.join(missing)}（巡查单号不可为空）")
    return ActionResult(ok=True, message="巡查单已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条巡查单执行派发巡查、提交结果、作废巡查。

    已提交与已作废互斥：进入任一终态后再操作会被拦下并说明原因；
    重复作废只保留第一次作废的结果，不清除已登记的巡查明细。
    """
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
