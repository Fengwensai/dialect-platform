from ..models.audit_log import AdminOperationLog


def log_admin_action(
    db,
    admin,
    action: str,
    target_type: str = "",
    target_id=None,
    summary: str = "",
    detail: list | None = None,
    ip: str = "",
):
    """记录一条管理员操作审计日志（与业务改动同一事务，原子落库）。

    约定：各被审端点在本 session 的 mutation 成功后、db.commit() 前调用。
    """
    db.add(
        AdminOperationLog(
            admin_id=admin.id,
            admin_name=admin.name or admin.username,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            summary=summary,
            detail=detail or [],
            ip=ip,
        )
    )
