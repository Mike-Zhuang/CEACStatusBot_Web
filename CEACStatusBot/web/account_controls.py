from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status

from .database import getConnection, utcNowIso
from .secrets import decryptIfNeeded, encryptSecret


ACCOUNT_STATUS_ACTIVE = "active"
ACCOUNT_STATUS_REVIEW = "review"
ACCOUNT_STATUS_SUSPENDED = "suspended"
ACCOUNT_STATUS_VALUES = {ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_REVIEW, ACCOUNT_STATUS_SUSPENDED}
RISK_GROUP_STATE_REVIEW = "review"
RISK_GROUP_STATE_ENFORCED = "enforced"

# 同设备本身可能来自家庭电脑、共享浏览器或公共设备，不能直接视为滥用。
# 只有账号数量较多且注册时间高度集中时，才限制新账号进入人工审核。
DEVICE_ASSOCIATION_WINDOW_DAYS = 30
DEVICE_ASSOCIATION_OBSERVE_ACCOUNT_COUNT = 3
DEVICE_ASSOCIATION_REVIEW_ACCOUNT_COUNT = 5
DEVICE_ASSOCIATION_BURST_WINDOW_HOURS = 24
DEVICE_ASSOCIATION_BURST_ACCOUNT_COUNT = 3

ACCOUNT_RESTRICTED_MESSAGE = "账号当前无法使用查询服务。如需协助，请提交申诉。"
GROUP_QUOTA_MESSAGE = "当前账号或关联账号已达到可用档案额度，请联系管理员处理。"


def _nowIso() -> str:
    return utcNowIso()


def _placeholders(values: Iterable[int]) -> tuple[str, tuple[int, ...]]:
    normalized = tuple(sorted({int(value) for value in values}))
    if not normalized:
        return "NULL", ()
    return ", ".join("?" for _ in normalized), normalized


def _decrypt(value: str | None) -> str:
    return decryptIfNeeded(value) or ""


def _encrypt(value: str | None) -> str:
    return encryptSecret(value or "")


def publicAccountFields(row: dict[str, Any]) -> dict[str, Any]:
    """只向普通用户返回是否可用，不暴露风控依据或管理员备注。"""
    accountStatus = str(row.get("account_status") or ACCOUNT_STATUS_ACTIVE)
    if accountStatus not in ACCOUNT_STATUS_VALUES:
        accountStatus = ACCOUNT_STATUS_REVIEW
    return {
        "account_status": accountStatus,
        "account_restricted": accountStatus != ACCOUNT_STATUS_ACTIVE,
    }


def ensureAccountCanUseService(user: dict[str, Any]) -> None:
    if user.get("role") == "admin":
        return
    if str(user.get("account_status") or ACCOUNT_STATUS_ACTIVE) != ACCOUNT_STATUS_ACTIVE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ACCOUNT_RESTRICTED_MESSAGE)


def isUserAccountActive(userId: int, connection: Any | None = None) -> bool:
    def readStatus(activeConnection: Any) -> bool:
        row = activeConnection.execute(
            "SELECT role, account_status FROM users WHERE id = ?",
            (userId,),
        ).fetchone()
        if not row:
            return False
        return row["role"] == "admin" or str(row.get("account_status") or ACCOUNT_STATUS_ACTIVE) == ACCOUNT_STATUS_ACTIVE

    if connection is not None:
        return readStatus(connection)
    with getConnection() as localConnection:
        return readStatus(localConnection)


def getQuotaScope(connection: Any, userId: int) -> dict[str, Any]:
    """返回用户实际共享的额度范围；仅确认关联的标准账号共享额度。"""
    user = connection.execute(
        "SELECT id, role, account_tier FROM users WHERE id = ?",
        (userId,),
    ).fetchone()
    if not user:
        raise ValueError("用户不存在")
    if user["role"] == "admin":
        return {"userIds": (userId,), "profileLimit": None, "scope": "admin", "accountTier": "admin"}
    if user["account_tier"] == "premium":
        return {"userIds": (userId,), "profileLimit": 5, "scope": "premium", "accountTier": "premium"}

    # 关联组可能因后续人工核对而重叠。这里按已启用组的连通分量计算，
    # 防止 A-B、B-C 两个组被拆开后绕过共享额度。
    groups = connection.execute(
        """
        WITH RECURSIVE related_standard_users(user_id) AS (
            SELECT ?
            UNION
            SELECT member.user_id
            FROM related_standard_users related
            JOIN account_risk_group_members anchor ON anchor.user_id = related.user_id
            JOIN account_risk_groups g
              ON g.id = anchor.group_id
             AND g.enforcement_state = ?
            JOIN account_risk_group_members member ON member.group_id = g.id
            JOIN users member_user ON member_user.id = member.user_id
            WHERE member_user.role != 'admin'
              AND member_user.account_tier = 'standard'
        )
        SELECT DISTINCT g.id, g.shared_standard_profile_limit
        FROM account_risk_groups g
        JOIN account_risk_group_members m ON m.group_id = g.id
        JOIN related_standard_users related ON related.user_id = m.user_id
        WHERE g.enforcement_state = ?
        ORDER BY g.id ASC
        """,
        (userId, RISK_GROUP_STATE_ENFORCED, RISK_GROUP_STATE_ENFORCED),
    ).fetchall()
    if not groups:
        return {"userIds": (userId,), "profileLimit": 1, "scope": "standard", "accountTier": "standard"}

    groupIds = tuple(int(group["id"]) for group in groups)
    groupPlaceholders, groupParams = _placeholders(groupIds)
    memberRows = connection.execute(
        f"""
        WITH RECURSIVE related_standard_users(user_id) AS (
            SELECT ?
            UNION
            SELECT member.user_id
            FROM related_standard_users related
            JOIN account_risk_group_members anchor ON anchor.user_id = related.user_id
            JOIN account_risk_groups g
              ON g.id = anchor.group_id
             AND g.enforcement_state = ?
            JOIN account_risk_group_members member ON member.group_id = g.id
            JOIN users member_user ON member_user.id = member.user_id
            WHERE member_user.role != 'admin'
              AND member_user.account_tier = 'standard'
        )
        SELECT DISTINCT m.user_id
        FROM account_risk_group_members m
        JOIN users u ON u.id = m.user_id
        JOIN related_standard_users related ON related.user_id = m.user_id
        WHERE m.group_id IN ({groupPlaceholders})
          AND u.role != 'admin'
          AND u.account_tier = 'standard'
        """,
        (userId, RISK_GROUP_STATE_ENFORCED, *groupParams),
    ).fetchall()
    memberIds = tuple(sorted({userId, *(int(row["user_id"]) for row in memberRows)}))
    limit = min(max(1, int(group["shared_standard_profile_limit"] or 1)) for group in groups)
    return {
        "userIds": memberIds,
        "profileLimit": limit,
        "scope": "linked_standard",
        "accountTier": "standard",
        "groupIds": groupIds,
    }


def countProfilesInScope(connection: Any, userIds: Iterable[int], *, enabledOnly: bool = False) -> int:
    placeholders, params = _placeholders(userIds)
    if not params:
        return 0
    enabledWhere = " AND is_enabled = 1" if enabledOnly else ""
    total = 0
    for tableName in ("ceac_cases", "ircc_cases", "korea_cases"):
        row = connection.execute(
            f"SELECT COUNT(*) AS count FROM {tableName} WHERE user_id IN ({placeholders}){enabledWhere}",
            params,
        ).fetchone()
        total += int(row["count"] if row else 0)
    return total


def enforceProfileCreationLimit(connection: Any, userId: int) -> None:
    scope = getQuotaScope(connection, userId)
    if scope["profileLimit"] is None:
        return
    if countProfilesInScope(connection, scope["userIds"]) >= int(scope["profileLimit"]):
        if scope["scope"] == "linked_standard":
            raise ValueError(GROUP_QUOTA_MESSAGE)
        raise ValueError(f"当前账号最多可添加 {scope['profileLimit']} 个档案，请联系管理员升级账号。")


def enforceProfileActivationLimit(connection: Any, userId: int, *, tableName: str, profileId: int) -> None:
    """启用已存在档案前检查关联账号的启用额度，防止停用后绕过限制。"""
    if tableName not in {"ceac_cases", "ircc_cases", "korea_cases"}:
        raise ValueError("不支持的档案类型")
    scope = getQuotaScope(connection, userId)
    if scope["profileLimit"] is None:
        return
    placeholders, params = _placeholders(scope["userIds"])
    total = 0
    for candidateTable in ("ceac_cases", "ircc_cases", "korea_cases"):
        exclusions = ""
        candidateParams: tuple[Any, ...] = params
        if candidateTable == tableName:
            exclusions = " AND id != ?"
            candidateParams = (*params, profileId)
        row = connection.execute(
            f"SELECT COUNT(*) AS count FROM {candidateTable} WHERE user_id IN ({placeholders}) AND is_enabled = 1{exclusions}",
            candidateParams,
        ).fetchone()
        total += int(row["count"] if row else 0)
    if total >= int(scope["profileLimit"]):
        if scope["scope"] == "linked_standard":
            raise ValueError(GROUP_QUOTA_MESSAGE)
        raise ValueError(f"当前账号最多只能启用 {scope['profileLimit']} 个自动查询档案，请先停止其他档案。")


def scopedUserIds(connection: Any, userId: int) -> tuple[int, ...]:
    return tuple(int(value) for value in getQuotaScope(connection, userId)["userIds"])


def _recordAccountEvent(
    connection: Any,
    *,
    eventType: str,
    userId: int | None,
    severity: str = "warning",
    detail: str = "",
) -> None:
    connection.execute(
        """
        INSERT INTO security_events (event_type, severity, user_id, detail, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (eventType, severity, userId, detail, _nowIso()),
    )


def _disableUserMonitoring(connection: Any, userId: int, nowIso: str) -> None:
    connection.execute(
        "UPDATE ceac_cases SET is_enabled = 0, next_check_at = NULL, updated_at = ? WHERE user_id = ?",
        (nowIso, userId),
    )
    connection.execute(
        "UPDATE ircc_cases SET is_enabled = 0, next_check_at = NULL, updated_at = ? WHERE user_id = ?",
        (nowIso, userId),
    )
    connection.execute(
        "UPDATE korea_cases SET is_enabled = 0, next_check_at = NULL, updated_at = ? WHERE user_id = ?",
        (nowIso, userId),
    )
    connection.execute(
        """
        UPDATE passport_slot_monitors
        SET is_enabled = 0, next_check_at = NULL, updated_at = ?
        WHERE case_id IN (SELECT id FROM ceac_cases WHERE user_id = ?)
        """,
        (nowIso, userId),
    )

    stoppedMessage = "账号当前不可用，待执行查询已停止。"
    stoppedResult = _encrypt('{"success": false, "changed": false, "error": "账号当前不可用，待执行查询已停止。"}')
    for tableName in ("query_jobs", "ircc_query_jobs", "korea_query_jobs"):
        caseTable = "ceac_cases" if tableName == "query_jobs" else "ircc_cases" if tableName == "ircc_query_jobs" else "korea_cases"
        connection.execute(
            f"""
            UPDATE {tableName}
            SET status = 'failed', error_message = ?, result_json = ?, finished_at = ?, updated_at = ?
            WHERE status = 'queued'
              AND case_id IN (SELECT id FROM {caseTable} WHERE user_id = ?)
            """,
            (stoppedMessage, stoppedResult, nowIso, nowIso, userId),
        )


def suspendUserAccount(
    connection: Any,
    *,
    userId: int,
    reasonCode: str,
    adminNote: str = "",
) -> bool:
    user = connection.execute("SELECT role FROM users WHERE id = ?", (userId,)).fetchone()
    if not user:
        return False
    if user["role"] == "admin":
        raise ValueError("不能暂停管理员账号")
    nowIso = _nowIso()
    connection.execute(
        """
        UPDATE users
        SET account_status = ?, suspended_at = ?, suspension_reason = ?, suspension_note_encrypted = ?, updated_at = ?
        WHERE id = ?
        """,
        (ACCOUNT_STATUS_SUSPENDED, nowIso, reasonCode, _encrypt(adminNote), nowIso, userId),
    )
    connection.execute(
        "UPDATE user_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
        (nowIso, userId),
    )
    _disableUserMonitoring(connection, userId, nowIso)
    _recordAccountEvent(
        connection,
        eventType="account_suspended",
        userId=userId,
        detail=reasonCode,
    )
    return True


def placeUserAccountUnderReview(
    connection: Any,
    *,
    userId: int,
    reasonCode: str,
    adminNote: str = "",
) -> bool:
    """将高风险新账号置于人工审核，并立即停止其现有查询活动。"""
    user = connection.execute("SELECT role FROM users WHERE id = ?", (userId,)).fetchone()
    if not user:
        return False
    if user["role"] == "admin":
        raise ValueError("不能限制管理员账号")
    nowIso = _nowIso()
    connection.execute(
        """
        UPDATE users
        SET account_status = ?, suspended_at = NULL, suspension_reason = ?,
            suspension_note_encrypted = ?, updated_at = ?
        WHERE id = ?
        """,
        (ACCOUNT_STATUS_REVIEW, reasonCode, _encrypt(adminNote), nowIso, userId),
    )
    connection.execute(
        "UPDATE user_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
        (nowIso, userId),
    )
    _disableUserMonitoring(connection, userId, nowIso)
    setUserRiskFlag(
        connection,
        userId=userId,
        riskLevel="review",
        reasonCode=reasonCode,
        adminNote=adminNote,
    )
    _recordAccountEvent(
        connection,
        eventType="account_review_required",
        userId=userId,
        detail=reasonCode,
    )
    return True


def restoreUserAccount(
    connection: Any,
    *,
    userId: int,
    removeFromEnforcedGroups: bool = False,
    reason: str = "admin_restore",
) -> bool:
    user = connection.execute("SELECT role FROM users WHERE id = ?", (userId,)).fetchone()
    if not user:
        return False
    if user["role"] == "admin":
        raise ValueError("管理员账号无需恢复")
    nowIso = _nowIso()
    connection.execute(
        """
        UPDATE users
        SET account_status = ?, suspended_at = NULL, suspension_reason = '', suspension_note_encrypted = '', updated_at = ?
        WHERE id = ?
        """,
        (ACCOUNT_STATUS_ACTIVE, nowIso, userId),
    )
    if removeFromEnforcedGroups:
        connection.execute(
            """
            DELETE FROM account_risk_group_members
            WHERE user_id = ?
              AND group_id IN (
                  SELECT id FROM account_risk_groups WHERE enforcement_state = ?
              )
            """,
            (userId, RISK_GROUP_STATE_ENFORCED),
        )
    _recordAccountEvent(connection, eventType="account_restored", userId=userId, severity="info", detail=reason)
    return True


def createRiskGroup(
    connection: Any,
    *,
    userIds: Iterable[int],
    label: str,
    reasonCode: str,
    adminNote: str,
    createdByUserId: int | None,
    enforcementState: str = RISK_GROUP_STATE_ENFORCED,
    sharedStandardProfileLimit: int = 1,
    suspendMembers: bool = False,
    evidenceType: str = "admin_review",
    evidenceReferenceHash: str = "",
) -> dict[str, Any]:
    normalizedIds = tuple(sorted({int(userId) for userId in userIds}))
    if not normalizedIds:
        raise ValueError("至少选择一个账号")
    if enforcementState not in {RISK_GROUP_STATE_REVIEW, RISK_GROUP_STATE_ENFORCED}:
        raise ValueError("关联组状态不支持")
    placeholders, params = _placeholders(normalizedIds)
    users = connection.execute(
        f"SELECT id, role FROM users WHERE id IN ({placeholders})",
        params,
    ).fetchall()
    if len(users) != len(normalizedIds):
        raise ValueError("存在不存在的账号")
    if any(user["role"] == "admin" for user in users):
        raise ValueError("关联组不能包含管理员账号")
    nowIso = _nowIso()
    cursor = connection.execute(
        """
        INSERT INTO account_risk_groups (
            label, reason_code, admin_note_encrypted, enforcement_state,
            shared_standard_profile_limit, created_by_user_id, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            label.strip() or "关联账号审核组",
            reasonCode.strip() or "admin_review",
            _encrypt(adminNote),
            enforcementState,
            max(1, sharedStandardProfileLimit),
            createdByUserId,
            nowIso,
            nowIso,
        ),
    )
    groupId = int(cursor.lastrowid)
    for userId in normalizedIds:
        connection.execute(
            """
            INSERT INTO account_risk_group_members (
                group_id, user_id, evidence_type, evidence_reference_hash, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (groupId, userId, evidenceType, evidenceReferenceHash, nowIso),
        )
        if suspendMembers:
            suspendUserAccount(connection, userId=userId, reasonCode=reasonCode, adminNote=adminNote)
    _recordAccountEvent(
        connection,
        eventType="risk_group_created",
        userId=createdByUserId,
        severity="warning" if suspendMembers else "info",
        detail=f"group={groupId};members={len(normalizedIds)};state={enforcementState}",
    )
    return getRiskGroup(connection, groupId) or {"id": groupId}


def getRiskGroup(connection: Any, groupId: int) -> dict[str, Any] | None:
    group = connection.execute("SELECT * FROM account_risk_groups WHERE id = ?", (groupId,)).fetchone()
    if not group:
        return None
    members = connection.execute(
        """
        SELECT u.id, u.email, u.account_tier, u.account_status, m.evidence_type, m.created_at
        FROM account_risk_group_members m
        JOIN users u ON u.id = m.user_id
        WHERE m.group_id = ?
        ORDER BY u.id ASC
        """,
        (groupId,),
    ).fetchall()
    return {
        "id": group["id"],
        "label": group["label"],
        "reasonCode": group["reason_code"],
        "adminNote": _decrypt(group["admin_note_encrypted"]),
        "enforcementState": group["enforcement_state"],
        "sharedStandardProfileLimit": int(group["shared_standard_profile_limit"] or 1),
        "createdByUserId": group["created_by_user_id"],
        "createdAt": group["created_at"],
        "updatedAt": group["updated_at"],
        "members": [
            {
                "id": member["id"],
                "email": member["email"],
                "accountTier": member["account_tier"],
                "accountStatus": member.get("account_status") or ACCOUNT_STATUS_ACTIVE,
                "evidenceType": member["evidence_type"],
                "addedAt": member["created_at"],
            }
            for member in members
        ],
    }


def listRiskGroups(connection: Any) -> list[dict[str, Any]]:
    rows = connection.execute("SELECT id FROM account_risk_groups ORDER BY updated_at DESC, id DESC").fetchall()
    return [group for row in rows if (group := getRiskGroup(connection, int(row["id"]))) is not None]


def setUserRiskFlag(
    connection: Any,
    *,
    userId: int,
    riskLevel: str,
    reasonCode: str,
    adminNote: str,
) -> bool:
    user = connection.execute("SELECT id, role FROM users WHERE id = ?", (userId,)).fetchone()
    if not user:
        return False
    if user["role"] == "admin":
        raise ValueError("不能标记管理员账号")
    nowIso = _nowIso()
    connection.execute(
        """
        INSERT INTO account_risk_flags (user_id, risk_level, reason_code, admin_note_encrypted, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            risk_level = excluded.risk_level,
            reason_code = excluded.reason_code,
            admin_note_encrypted = excluded.admin_note_encrypted,
            updated_at = excluded.updated_at
        """,
        (userId, riskLevel, reasonCode, _encrypt(adminNote), nowIso, nowIso),
    )
    _recordAccountEvent(connection, eventType="account_risk_flagged", userId=userId, detail=reasonCode)
    return True


def evaluateNewRegistrationAssociation(
    connection: Any,
    *,
    userId: int,
    deviceHash: str,
    ipHash: str,
) -> bool:
    """记录同设备关联；仅在数量和短时集中注册同时命中时进入人工审核。"""
    # 保留 IP 参数以兼容注册调用，但共享网络误伤率高，不参与自动限制判定。
    _ = ipHash
    if not deviceHash:
        return False
    now = datetime.now(UTC).replace(microsecond=0)
    cutoff = (now - timedelta(days=DEVICE_ASSOCIATION_WINDOW_DAYS)).isoformat()
    relatedRows = connection.execute(
        """
        SELECT DISTINCT u.id, u.created_at
        FROM users u
        LEFT JOIN user_sessions s ON s.user_id = u.id
        WHERE u.id != ?
          AND u.role = 'user'
          AND u.account_tier = 'standard'
          AND u.created_at >= ?
          AND (
              u.terms_acceptance_device_hash = ?
              OR s.device_hash = ?
          )
        """,
        (userId, cutoff, deviceHash, deviceHash),
    ).fetchall()
    relatedIds = tuple(sorted({int(row["id"]) for row in relatedRows}))
    relatedAccountCount = len(relatedIds) + 1
    if relatedAccountCount < DEVICE_ASSOCIATION_OBSERVE_ACCOUNT_COUNT:
        return False

    nowIso = _nowIso()
    burstCutoff = now - timedelta(hours=DEVICE_ASSOCIATION_BURST_WINDOW_HOURS)
    burstRelatedAccountCount = 1
    for row in relatedRows:
        createdAt = str(row["created_at"] or "")
        try:
            parsedCreatedAt = datetime.fromisoformat(createdAt.replace("Z", "+00:00"))
            if parsedCreatedAt.tzinfo is None:
                parsedCreatedAt = parsedCreatedAt.replace(tzinfo=UTC)
        except ValueError:
            continue
        if parsedCreatedAt >= burstCutoff:
            burstRelatedAccountCount += 1

    needsReview = (
        relatedAccountCount >= DEVICE_ASSOCIATION_REVIEW_ACCOUNT_COUNT
        and burstRelatedAccountCount >= DEVICE_ASSOCIATION_BURST_ACCOUNT_COUNT
    )
    if not needsReview:
        setUserRiskFlag(
            connection,
            userId=userId,
            riskLevel="watch",
            reasonCode="repeated_device_registration_watch",
            adminNote=(
                "自动观察规则：30 天内同一设备存在多个标准账号。"
                "仅记录关联，不限制新账号，也不启用关联额度。"
            ),
        )
        createRiskGroup(
            connection,
            userIds=(*relatedIds, userId),
            label="自动关联观察组",
            reasonCode="repeated_device_registration_watch",
            adminNote="仅同设备关联，未命中集中注册条件；不限制成员账号。",
            createdByUserId=None,
            enforcementState=RISK_GROUP_STATE_REVIEW,
            suspendMembers=False,
            evidenceType="shared_device",
        )
        _recordAccountEvent(
            connection,
            eventType="registration_association_observed",
            userId=userId,
            detail="repeated_device_registration_watch",
        )
        return True

    connection.execute(
        "UPDATE users SET account_status = ?, updated_at = ? WHERE id = ?",
        (ACCOUNT_STATUS_REVIEW, nowIso, userId),
    )
    setUserRiskFlag(
        connection,
        userId=userId,
        riskLevel="review",
        reasonCode="repeated_device_registration_high_velocity",
        adminNote=(
            "自动规则：30 天内同一设备注册多个标准账号，且 24 小时内存在集中注册，"
            "等待人工审核。"
        ),
    )
    createRiskGroup(
        connection,
        userIds=(*relatedIds, userId),
        label="自动关联审核组",
        reasonCode="repeated_device_registration_high_velocity",
        adminNote="自动规则命中；未自动限制既有账号，也未启用关联额度。",
        createdByUserId=None,
        enforcementState=RISK_GROUP_STATE_REVIEW,
        suspendMembers=False,
        evidenceType="shared_device",
    )
    _recordAccountEvent(
        connection,
        eventType="registration_review_required",
        userId=userId,
        detail="repeated_device_registration_high_velocity",
    )
    return True


def submitAccountAppeal(connection: Any, *, userId: int, message: str) -> dict[str, Any]:
    user = connection.execute("SELECT account_status FROM users WHERE id = ?", (userId,)).fetchone()
    if not user:
        raise ValueError("用户不存在")
    if str(user.get("account_status") or ACCOUNT_STATUS_ACTIVE) == ACCOUNT_STATUS_ACTIVE:
        raise ValueError("当前账号无需申诉")
    existing = connection.execute(
        """
        SELECT id FROM account_appeals
        WHERE user_id = ? AND status = 'pending'
        ORDER BY id DESC LIMIT 1
        """,
        (userId,),
    ).fetchone()
    if existing:
        raise ValueError("申诉已提交，请等待管理员处理。")
    nowIso = _nowIso()
    cursor = connection.execute(
        """
        INSERT INTO account_appeals (user_id, status, message_encrypted, submitted_at)
        VALUES (?, 'pending', ?, ?)
        """,
        (userId, _encrypt(message), nowIso),
    )
    _recordAccountEvent(connection, eventType="account_appeal_submitted", userId=userId, severity="info")
    return getLatestAccountAppeal(connection, userId, includeMessage=True) or {"id": int(cursor.lastrowid)}


def getLatestAccountAppeal(connection: Any, userId: int, *, includeMessage: bool = False, adminView: bool = False) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT a.*, reviewer.email AS reviewer_email
        FROM account_appeals a
        LEFT JOIN users reviewer ON reviewer.id = a.reviewed_by_user_id
        WHERE a.user_id = ?
        ORDER BY a.id DESC
        LIMIT 1
        """,
        (userId,),
    ).fetchone()
    if not row:
        return None
    appeal = {
        "id": row["id"],
        "userId": row["user_id"],
        "status": row["status"],
        "submittedAt": row["submitted_at"],
        "reviewedAt": row["reviewed_at"],
        "reviewedByUserId": row["reviewed_by_user_id"],
        "reviewedByEmail": row.get("reviewer_email") or "",
        "reviewNote": _decrypt(row.get("review_note_encrypted") or ""),
    }
    if includeMessage or adminView:
        appeal["message"] = _decrypt(row.get("message_encrypted") or "")
    if adminView:
        appeal["adminNote"] = _decrypt(row.get("admin_note_encrypted") or "")
    return appeal


def listAccountAppeals(connection: Any) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT user_id FROM account_appeals GROUP BY user_id ORDER BY MAX(id) DESC",
    ).fetchall()
    return [
        appeal
        for row in rows
        if (appeal := getLatestAccountAppeal(connection, int(row["user_id"]), includeMessage=True, adminView=True)) is not None
    ]


def reviewAccountAppeal(
    connection: Any,
    *,
    appealId: int,
    reviewerUserId: int,
    decision: str,
    reviewNote: str,
    adminNote: str,
    removeFromEnforcedGroups: bool,
) -> dict[str, Any] | None:
    if decision not in {"approved", "rejected"}:
        raise ValueError("申诉处理结果不支持")
    appeal = connection.execute("SELECT * FROM account_appeals WHERE id = ?", (appealId,)).fetchone()
    if not appeal:
        return None
    if appeal["status"] != "pending":
        raise ValueError("该申诉已处理")
    nowIso = _nowIso()
    connection.execute(
        """
        UPDATE account_appeals
        SET status = ?, review_note_encrypted = ?, admin_note_encrypted = ?, reviewed_at = ?, reviewed_by_user_id = ?
        WHERE id = ?
        """,
        (decision, _encrypt(reviewNote), _encrypt(adminNote), nowIso, reviewerUserId, appealId),
    )
    if decision == "approved":
        restoreUserAccount(
            connection,
            userId=int(appeal["user_id"]),
            removeFromEnforcedGroups=removeFromEnforcedGroups,
            reason="appeal_approved",
        )
    _recordAccountEvent(
        connection,
        eventType="account_appeal_reviewed",
        userId=int(appeal["user_id"]),
        severity="info",
        detail=decision,
    )
    return getLatestAccountAppeal(connection, int(appeal["user_id"]), includeMessage=True, adminView=True)


def getAccountRiskSummary(connection: Any, userId: int) -> dict[str, Any]:
    groups = connection.execute(
        """
        SELECT g.id, g.label, g.enforcement_state
        FROM account_risk_groups g
        JOIN account_risk_group_members m ON m.group_id = g.id
        WHERE m.user_id = ?
        ORDER BY g.id DESC
        """,
        (userId,),
    ).fetchall()
    flag = connection.execute(
        "SELECT risk_level, reason_code FROM account_risk_flags WHERE user_id = ?",
        (userId,),
    ).fetchone()
    latestAppeal = getLatestAccountAppeal(connection, userId)
    return {
        "riskGroups": [
            {"id": row["id"], "label": row["label"], "enforcementState": row["enforcement_state"]}
            for row in groups
        ],
        "riskLevel": flag["risk_level"] if flag else "",
        "riskReasonCode": flag["reason_code"] if flag else "",
        "latestAppealStatus": latestAppeal["status"] if latestAppeal else "",
    }
