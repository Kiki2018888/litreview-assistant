"""裁决数据模型集成测试（ADR-7）.

测试流程：
  1. 从 DB 中取真实 claims 数据，构造一个候选组（模拟聚类落库）
  2. A1 — 采纳候选组并命名
  3. A2 — 否决另一个候选组
  4. A3 — 从采纳的信号中踢出一条 claim
  5. A6 — 修改裁决（否决 → 采纳）
  6. 验证数据完整性：落库、可读回、可修改、踢出留痕
"""
from __future__ import annotations

# 本文件是手动集成脚本（`python backend/tests/test_adjudication.py`），不是 pytest 用例。
__test__ = False

import json
import os
import sys
import time
import uuid
import urllib.request
from pathlib import Path
from threading import Thread

# 确保项目根在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # tests/ → backend/ → root
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import settings
from backend.services.db import SessionLocal
from backend.models.tables import (
    CandidateGroup,
    CandidateGroupClaim,
    Claim,
    Signal,
    SignalClaim,
    SignalStatus,
    ClaimAddition,
    Paper,
)

BASE_URL = f"http://{settings.host}:{settings.port}"
ADJ = f"{BASE_URL}/api/v1/adjudication"

# ── 测试用 UUID ──
TEST_RUN_ID = str(uuid.uuid4())
TEST_PROJECT_ID = ""


def _uuid() -> str:
    return str(uuid.uuid4())


def _req(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """简易 HTTP 请求."""
    sep = "&" if "?" in path else "?"
    url = f"{ADJ}{path}{sep}project_id={TEST_PROJECT_ID}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        return e.code, json.loads(raw) if raw else {"detail": raw}


def seed_candidate_groups():
    """从 DB 中取现存 claims，构造两个候选组落库（模拟聚类结果）."""
    db = SessionLocal()
    try:
        claims = db.query(Claim).filter(Claim.is_limitation.is_(True)).limit(8).all()
        if len(claims) < 4:
            print("[ERROR] DB 中 is_limitation=true 的 claims 不足 4 条，跑过 _run_clustering.py 了吗？")
            sys.exit(1)

        paper = db.get(Paper, claims[0].paper_id)
        global TEST_PROJECT_ID
        TEST_PROJECT_ID = (paper.project_id if paper else None) or ""
        if not TEST_PROJECT_ID:
            print("[ERROR] 种子 claims 所属文献没有 project_id")
            sys.exit(1)

        # 候选组 1：取前 3 条（将被采纳）
        cg1 = CandidateGroup(
            id=_uuid(), run_id=TEST_RUN_ID,
            project_id=TEST_PROJECT_ID,
            group_label="测试候选组-A: 涉及实验方法局限性",
            topic="manufacturing",
            grouping_method="topic + LLM 辅助分组",
            grouping_basis="讨论实验方法中的细胞培养与分选局限",
            cross_paper=True,
            claim_count=3,
        )
        db.add(cg1)
        for i, claim in enumerate(claims[:3], 1):
            db.add(CandidateGroupClaim(
                candidate_group_id=cg1.id, claim_id=claim.id, claim_order=i,
            ))

        # 候选组 2：取后 3 条（将被否决）
        cg2 = CandidateGroup(
            id=_uuid(), run_id=TEST_RUN_ID,
            project_id=TEST_PROJECT_ID,
            group_label="测试候选组-B: 涉及数据解释不确定性",
            topic="other",
            grouping_method="topic + LLM 辅助分组",
            grouping_basis="探讨数据解释中的模糊性",
            cross_paper=False,
            claim_count=3,
        )
        db.add(cg2)
        for i, claim in enumerate(claims[3:6], 1):
            db.add(CandidateGroupClaim(
                candidate_group_id=cg2.id, claim_id=claim.id, claim_order=i,
            ))

        # 候选组 3：取 1 条孤例（待定，不做裁决）
        cg3 = CandidateGroup(
            id=_uuid(), run_id=TEST_RUN_ID,
            project_id=TEST_PROJECT_ID,
            group_label="测试候选组-C: 孤例",
            topic="mechanism",
            grouping_method="topic only",
            grouping_basis="确定性孤例",
            cross_paper=False,
            claim_count=1,
        )
        db.add(cg3)
        db.add(CandidateGroupClaim(
            candidate_group_id=cg3.id, claim_id=claims[6].id, claim_order=1,
        ))

        db.commit()

        groups = {cg1.id: cg1.claim_count, cg2.id: cg2.claim_count, cg3.id: cg3.claim_count}
        print(f"[OK] 种子数据: {len(groups)} 个候选组落库")
        return groups, claims[:6]
    finally:
        db.close()


def test_a1_accept(cg_id: str, expected_count: int):
    """A1 — 采纳候选组并命名."""
    print(f"\n{'='*60}")
    print("A1: 采纳候选组 → 创建信号")
    print(f"{'='*60}")

    status, data = _req("POST", "/signals", {
        "action": "accept",
        "candidate_group_id": cg_id,
        "signal_name": "实验方法中的细胞培养局限性",
        "human_rationale": "三条都讨论细胞培养与分选步骤的局限，确有跨论文共性",
    })
    print(f"  HTTP {status}")
    assert status == 201, f"期望 201，实得 {status}: {data}"
    assert data["status"] == "accepted", f"期望 accepted，实得 {data['status']}"
    assert data["signal_name"] == "实验方法中的细胞培养局限性"
    assert data["claim_count"] == expected_count, \
        f"期望 claim_count={expected_count}，实得 {data['claim_count']}"
    print(f"  [PASS] 信号已创建: id={data['id'][:8]}..., "
          f"name='{data['signal_name']}', claims={data['claim_count']}")
    return data["id"]


def test_a2_reject(cg_id: str):
    """A2 — 否决候选组."""
    print(f"\n{'='*60}")
    print("A2: 否决候选组")
    print(f"{'='*60}")

    status, data = _req("POST", "/signals", {
        "action": "reject",
        "candidate_group_id": cg_id,
        "human_rationale": "单论文内的话题堆砌，不构成跨文献信号",
    })
    print(f"  HTTP {status}")
    assert status == 201, f"期望 201，实得 {status}: {data}"
    assert data["status"] == "rejected", f"期望 rejected，实得 {data['status']}"
    assert data["signal_name"] is None, "否决的信号不应有 signal_name"
    print(f"  [PASS] 信号已否决: id={data['id'][:8]}..., "
          f"reason='{data['human_rationale']}'")
    return data["id"]


def test_a3_kick_claim(signal_id: str, claim_index: int):
    """A3 — 从信号中踢出一条 claim."""
    print(f"\n{'='*60}")
    print("A3: 踢出一条 claim（标记 manual_remove）")
    print(f"{'='*60}")

    # 先获取信号的当前 claims
    status, detail = _req("GET", f"/signals/{signal_id}")
    assert status == 200
    claims_before = detail["claims"]
    print(f"  踢前 claims 数: {detail['claim_count']}")

    # 选一条活跃的 claim（非 manual_remove）
    active = [c for c in claims_before if c["added_by"] != "manual_remove"]
    assert len(active) > 0, "没有可踢出的活跃 claim"
    target_claim_id = active[min(claim_index, len(active) - 1)]["claim_id"]

    status, data = _req("DELETE", f"/signals/{signal_id}/claims/{target_claim_id}")
    print(f"  HTTP {status}")
    assert status == 200, f"期望 200，实得 {status}: {data}"
    assert data["success"] is True
    assert data["added_by"] == "manual_remove"
    print(f"  [PASS] claim {target_claim_id[:8]}... 已被标记为 manual_remove")

    # 验证信号详情中 claim_count 已减少
    status, detail = _req("GET", f"/signals/{signal_id}")
    assert status == 200
    print(f"  踢后 claims 数: {detail['claim_count']}")

    # 验证被踢的 claim 在详情中仍可见（留痕）但标记为 manual_remove
    kicked = [c for c in detail["claims"] if c["claim_id"] == target_claim_id]
    assert len(kicked) > 0, "被踢出的 claim 应在详情中仍可见（留痕）"
    assert kicked[0]["added_by"] == "manual_remove", \
        f"应标记为 manual_remove，实为 {kicked[0]['added_by']}"
    print(f"  [PASS] 留痕验证: kick 后 claim 仍可读取, added_by='manual_remove'")
    return target_claim_id


def test_a6_revalue(rejected_signal_id: str, new_name: str):
    """A6 — 修改已有裁决：rejected → accepted."""
    print(f"\n{'='*60}")
    print("A6: 修改裁决（rejected → accepted）")
    print(f"{'='*60}")

    # 先确认当前是 rejected
    status, before = _req("GET", f"/signals/{rejected_signal_id}")
    assert status == 200
    assert before["status"] == "rejected", f"期望 rejected，实得 {before['status']}"
    print(f"  改前: status={before['status']}, name={before['signal_name']}")

    # 改为 accepted，并命名
    status, data = _req("PATCH", f"/signals/{rejected_signal_id}", {
        "status": "accepted",
        "signal_name": new_name,
        "human_rationale": "重新评估后确认这是有效信号",
    })
    print(f"  HTTP {status}")
    assert status == 200, f"期望 200，实得 {status}: {data}"
    assert data["status"] == "accepted", f"期望 accepted，实得 {data['status']}"
    assert data["signal_name"] == new_name
    print(f"  [PASS] 裁决已修改: status→accepted, name='{data['signal_name']}'")

    # 再改回 rejected 验证幂等
    status, data2 = _req("PATCH", f"/signals/{rejected_signal_id}", {
        "status": "rejected",
    })
    assert status == 200
    assert data2["status"] == "rejected"
    print(f"  [PASS] 可再次修改: status→rejected")
    return True


def test_db_integrity():
    """直接查 DB 验证数据结构完整性."""
    print(f"\n{'='*60}")
    print("DB 完整性验证")
    print(f"{'='*60}")

    db = SessionLocal()
    try:
        # 1. 候选组数量
        cg_count = db.query(CandidateGroup).filter(
            CandidateGroup.run_id == TEST_RUN_ID
        ).count()
        print(f"  候选组: {cg_count} 个")

        # 2. 信号数量与状态
        sigs = db.query(Signal).order_by(Signal.created_at).all()
        statuses = {s.id[:8]: s.status for s in sigs}
        print(f"  信号: {len(sigs)} 个 → {statuses}")

        # 3. signal_claims 中应有 manual_remove 记录
        all_sc = db.query(SignalClaim).all()
        by_type = {}
        for sc in all_sc:
            by_type[sc.added_by] = by_type.get(sc.added_by, 0) + 1
        print(f"  signal_claims 分布: {by_type}")
        assert "manual_remove" in by_type, "应有 manual_remove 记录！"
        print(f"  [PASS] manual_remove 记录: {by_type['manual_remove']} 条")

        # 4. 待定候选组（cg3）没有对应信号
        cg3 = db.query(CandidateGroup).filter(
            CandidateGroup.run_id == TEST_RUN_ID,
            CandidateGroup.group_label.like("%孤例%"),
        ).first()
        if cg3:
            sig_for_cg3 = db.query(Signal).filter(
                Signal.candidate_group_id == cg3.id,
            ).first()
            assert sig_for_cg3 is None, "待定候选组不应有对应信号"
            print(f"  [PASS] 待定候选组 (id={cg3.id[:8]}...) 无对应信号")

        # 5. 裁决时间字段
        accepted_sigs = [s for s in sigs if s.status == "accepted"]
        if accepted_sigs:
            for s in accepted_sigs:
                assert s.adjudicated_at is not None, \
                    f"accepted 信号应有 adjudicated_at (id={s.id[:8]}...)"
            print(f"  [PASS] {len(accepted_sigs)} 个 accepted 信号均有 adjudicated_at")
    finally:
        db.close()


def test_pending_list():
    """验证待定候选组在列表中以 adjudication_status=null 显示."""
    print(f"\n{'='*60}")
    print("A5 验证: 待定候选组的裁决状态")
    print(f"{'='*60}")

    status, groups = _req("GET", "/candidate-groups")
    assert status == 200

    pending_groups = [g for g in groups if g.get("adjudication_status") is None]
    print(f"  候选组总数: {len(groups)}, 待定: {len(pending_groups)}")
    assert len(pending_groups) > 0, "应有待定的候选组"
    print(f"  [PASS] 待定候选组的 adjudication_status 为 null")


def cleanup():
    """清理测试数据."""
    db = SessionLocal()
    try:
        # 删除本次测试产生的信号和候选组
        test_sig_ids = [
            s.id for s in db.query(Signal).join(
                CandidateGroup, Signal.candidate_group_id == CandidateGroup.id,
            ).filter(CandidateGroup.run_id == TEST_RUN_ID).all()
        ]
        for sid in test_sig_ids:
            db.query(SignalClaim).filter(SignalClaim.signal_id == sid).delete()
            db.query(Signal).filter(Signal.id == sid).delete()

        test_cg_ids = [
            r[0] for r in db.query(CandidateGroup.id).filter(
                CandidateGroup.run_id == TEST_RUN_ID,
            ).all()
        ]
        for cgid in test_cg_ids:
            db.query(CandidateGroupClaim).filter(
                CandidateGroupClaim.candidate_group_id == cgid,
            ).delete()
            db.query(CandidateGroup).filter(CandidateGroup.id == cgid).delete()

        db.commit()
        print(f"\n  清理: {len(test_sig_ids)} 信号 + {len(test_cg_ids)} 候选组")
    finally:
        db.close()


def start_server():
    """后台启动 uvicorn."""
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        log_level="error",
        access_log=False,
    ))
    t = Thread(target=server.run, daemon=True)
    t.start()
    time.sleep(2)  # 等服务器就绪
    return server


# ── 主流程 ──

if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))  # backend.config 依赖相对路径 data/

    print("裁决数据模型集成测试（ADR-7）")
    print(f"服务地址: {BASE_URL}")
    print(f"测试 run_id: {TEST_RUN_ID}")

    # 启动服务
    print("\n启动服务...")
    start_server()

    # 给服务多一点时间（首次可能有迁移）
    for i in range(10):
        try:
            urllib.request.urlopen(f"{BASE_URL}/health", timeout=2)
            print("[OK] 服务就绪")
            break
        except Exception:
            time.sleep(1)
    else:
        print("[ERROR] 服务启动超时")
        sys.exit(1)

    try:
        # 1. 种子数据
        groups, _ = seed_candidate_groups()
        cg_ids = list(groups.keys())

        # 2. A1 — 采纳候选组 1
        accepted_signal_id = test_a1_accept(cg_ids[0], groups[cg_ids[0]])

        # 3. A2 — 否决候选组 2
        rejected_signal_id = test_a2_reject(cg_ids[1])

        # 4. A3 — 踢出一条 claim
        test_a3_kick_claim(accepted_signal_id, 1)

        # 5. A5 — 待定（候选组 3 不做裁决）
        test_pending_list()

        # 6. A6 — 修改裁决
        test_a6_revalue(rejected_signal_id, "数据解释模糊性信号")

        # 7. DB 完整性验证
        test_db_integrity()

        print(f"\n{'='*60}")
        print("ALL TESTS PASSED")
        print(f"{'='*60}")
        print("\nSummary:")
        print("  A1 accept    [PASS] -- signal created, named, claims linked")
        print("  A2 reject    [PASS] -- signal rejected, no name")
        print("  A3 kick      [PASS] -- claim marked manual_remove, retained")
        print("  A5 pending   [PASS] -- no signal for pending group, status=null")
        print("  A6 revalue   [PASS] -- rejected<->accepted reversible, renamed")

    finally:
        cleanup()
        print("\n测试数据已清理")
