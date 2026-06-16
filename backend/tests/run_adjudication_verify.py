"""裁决闭环实测脚本：每一步打印真实 DB 行数据，不做主观判断。"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / ".." / ".."))
os.chdir(str(Path(__file__).resolve().parent / ".." / ".."))

from backend.config import settings
from backend.services.db import SessionLocal
from backend.models.tables import (
    CandidateGroup, CandidateGroupClaim,
    Signal, SignalClaim,
    Claim, Paper,
    SignalStatus, ClaimAddition,
)
from sqlalchemy import text
import uuid

BASE_URL = f"http://{settings.host}:{settings.port}"
ADJ = f"{BASE_URL}/api/v1/adjudication"
TEST_RUN_ID = str(uuid.uuid4())

def _uuid(): return str(uuid.uuid4())

def _api(method, path, body=None):
    url = f"{ADJ}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

def _section(title):
    print(f"\n{'#'*70}")
    print(f"#  {title}")
    print(f"{'#'*70}")

def _sub(title):
    print(f"\n  --- {title} ---")

# ============================================================
# Step 0: 种子数据 —— 从真实 claims 构造 3 个候选组落库
# ============================================================
_section("Step 0: 从 DB 取真实 claims，构造 3 个候选组落库")

db = SessionLocal()
claims = db.query(Claim).filter(Claim.is_limitation.is_(True)).limit(8).all()
print(f"DB 中 is_limitation=true 的 claims 总数: {db.query(Claim).filter(Claim.is_limitation.is_(True)).count()}")
print(f"取前 8 条用于构造候选组:")

for i, c in enumerate(claims):
    paper = db.get(Paper, c.paper_id)
    print(f"  [{i}] claim={c.id[:8]}... paper={paper.title[:50] if paper and paper.title else 'N/A'} quote={c.quote[:60] if c.quote else 'N/A'}...")

# 候选组1（采纳用）
cg1 = CandidateGroup(
    id=_uuid(), run_id=TEST_RUN_ID,
    group_label="测试A: 实验方法局限性-细胞培养",
    topic="manufacturing",
    grouping_method="topic + LLM",
    grouping_basis="讨论细胞培养与分选步骤的局限",
    cross_paper=True, claim_count=3,
)
db.add(cg1)
for i, c in enumerate(claims[:3], 1):
    db.add(CandidateGroupClaim(candidate_group_id=cg1.id, claim_id=c.id, claim_order=i))

# 候选组2（否决用）
cg2 = CandidateGroup(
    id=_uuid(), run_id=TEST_RUN_ID,
    group_label="测试B: 数据解释不确定性",
    topic="other",
    grouping_method="topic only",
    grouping_basis="探讨数据解释中的模糊性",
    cross_paper=False, claim_count=3,
)
db.add(cg2)
for i, c in enumerate(claims[3:6], 1):
    db.add(CandidateGroupClaim(candidate_group_id=cg2.id, claim_id=c.id, claim_order=i))

# 候选组3（待定）
cg3 = CandidateGroup(
    id=_uuid(), run_id=TEST_RUN_ID,
    group_label="测试C: 孤例-单论文",
    topic="mechanism",
    grouping_method="topic only",
    grouping_basis="确定性孤例",
    cross_paper=False, claim_count=1,
)
db.add(cg3)
db.add(CandidateGroupClaim(candidate_group_id=cg3.id, claim_id=claims[6].id, claim_order=1))

db.commit()
print(f"\n候选组落库完成:")
print(f"  cg1 (采纳用) = {cg1.id}, claims={cg1.claim_count}")
print(f"  cg2 (否决用) = {cg2.id}, claims={cg2.claim_count}")
print(f"  cg3 (待定)   = {cg3.id}, claims={cg3.claim_count}")

# 验证候选组内 claims 已落库
for cgid, label in [(cg1.id, "cg1"), (cg2.id, "cg2"), (cg3.id, "cg3")]:
    count = db.query(CandidateGroupClaim).filter(CandidateGroupClaim.candidate_group_id == cgid).count()
    print(f"  {label} candidate_group_claims 行数: {count}")
db.close()

# ============================================================
# Step 1: A1 采纳 —— 应该创建 signal + signal_claims
# ============================================================
_section("Step 1: A1 采纳候选组 cg1")

status, resp = _api("POST", "/signals", {
    "action": "accept",
    "candidate_group_id": cg1.id,
    "signal_name": "细胞培养步骤的实验方法局限性",
    "human_rationale": "三条都讨论细胞培养与分选步骤的局限，跨论文共性明确",
})
print(f"HTTP {status}")
print(f"响应: {json.dumps(resp, indent=2, ensure_ascii=False, default=str)}")

signal_accept_id = resp.get("id")

# 直接查 DB 打印真实行
db = SessionLocal()
sig = db.get(Signal, signal_accept_id)
print(f"\n>>> signals 表真实行:")
if sig:
    print(f"  id               = {sig.id}")
    print(f"  signal_name      = {sig.signal_name}")
    print(f"  status           = {sig.status}")
    print(f"  topic            = {sig.topic}")
    print(f"  candidate_group_id = {sig.candidate_group_id}")
    print(f"  human_rationale  = {sig.human_rationale}")
    print(f"  claim_count      = {sig.claim_count}")
    print(f"  created_at       = {sig.created_at}")
    print(f"  updated_at       = {sig.updated_at}")
    print(f"  adjudicated_at   = {sig.adjudicated_at}")
else:
    print("  [ERROR] signal 不存在！")

sc_rows = db.query(SignalClaim).filter(SignalClaim.signal_id == signal_accept_id).all()
print(f"\n>>> signal_claims 桥接表 ({len(sc_rows)} 行):")
for sc in sc_rows:
    c = db.get(Claim, sc.claim_id)
    p = db.get(Paper, c.paper_id) if c else None
    print(f"  signal_id={sc.signal_id[:8]}... claim_id={sc.claim_id[:8]}... "
          f"added_by={sc.added_by} quote={c.quote[:50] if c and c.quote else 'N/A'}... "
          f"paper={p.title[:40] if p and p.title else 'N/A'}")
db.close()

# ============================================================
# Step 2: A2 否决 —— 应该创建 signal(status=rejected)，signal_claims 为空
# ============================================================
_section("Step 2: A2 否决候选组 cg2")

status, resp = _api("POST", "/signals", {
    "action": "reject",
    "candidate_group_id": cg2.id,
    "human_rationale": "单论文内话题堆砌，不构成跨文献信号",
})
print(f"HTTP {status}")
print(f"响应: {json.dumps(resp, indent=2, ensure_ascii=False, default=str)}")

signal_reject_id = resp.get("id")

db = SessionLocal()
sig2 = db.get(Signal, signal_reject_id)
print(f"\n>>> signals 表真实行:")
if sig2:
    print(f"  id               = {sig2.id}")
    print(f"  signal_name      = {sig2.signal_name}")
    print(f"  status           = {sig2.status}")
    print(f"  claim_count      = {sig2.claim_count}")
    print(f"  adjudicated_at   = {sig2.adjudicated_at}")
else:
    print("  [ERROR] signal 不存在！")

sc_rows2 = db.query(SignalClaim).filter(SignalClaim.signal_id == signal_reject_id).all()
print(f"\n>>> signal_claims 桥接表: {len(sc_rows2)} 行 (否决的应为 0)")
for sc in sc_rows2:
    print(f"  signal_id={sc.signal_id[:8]}... claim_id={sc.claim_id[:8]}... added_by={sc.added_by}")
db.close()

# ============================================================
# Step 3: A3 踢出一条 claim
# ============================================================
_section("Step 3: A3 从采纳信号中踢出一条 claim")

# 先查当前信号详情
status, detail_before = _api("GET", f"/signals/{signal_accept_id}")
print(f"踢前 claim_count (API): {detail_before.get('claim_count')}")
print(f"踢前 claims 列表:")
for c in detail_before.get("claims", []):
    print(f"  claim_id={c['claim_id'][:8]}... added_by={c['added_by']} paper={c.get('paper_title','')[:40]}")

# 挑第一条 active claim 踢掉
target = None
for c in detail_before.get("claims", []):
    if c["added_by"] != "manual_remove":
        target = c
        break

if target:
    target_cid = target["claim_id"]
    print(f"\n踢出目标: claim_id={target_cid[:8]}...")
    status, kick_resp = _api("DELETE", f"/signals/{signal_accept_id}/claims/{target_cid}")
    print(f"HTTP {status}")
    print(f"踢出响应: {json.dumps(kick_resp, indent=2, ensure_ascii=False)}")

    # 直接查 DB 看 real state
    db = SessionLocal()
    sc_kicked = db.query(SignalClaim).filter(
        SignalClaim.signal_id == signal_accept_id,
        SignalClaim.claim_id == target_cid,
    ).first()
    print(f"\n>>> 被踢 claim 的 signal_claims 行 (DB 直接查):")
    if sc_kicked:
        print(f"  signal_id = {sc_kicked.signal_id}")
        print(f"  claim_id  = {sc_kicked.claim_id}")
        print(f"  added_by  = {sc_kicked.added_by}  <-- 应变成 manual_remove")
    else:
        print("  [ERROR] 行不存在 —— 被硬删了！不是留痕！")

    # 查 signal 的 claim_count 是否重算
    sig_after_kick = db.get(Signal, signal_accept_id)
    print(f"\n>>> signal.claim_count 重算后: {sig_after_kick.claim_count}")
    # 数一下活跃 claims
    active_count = db.query(SignalClaim).filter(
        SignalClaim.signal_id == signal_accept_id,
        SignalClaim.added_by != ClaimAddition.MANUAL_REMOVE.value,
    ).count()
    print(f"  活跃 signal_claims (非 manual_remove) 实际行数: {active_count}")
    # 验证被踢的仍在表中（留痕）
    all_sc = db.query(SignalClaim).filter(SignalClaim.signal_id == signal_accept_id).all()
    print(f"  signal_claims 总行数 (含留痕): {len(all_sc)}")
    print(f"  各 added_by 分布: ", {x: sum(1 for s in all_sc if s.added_by == x) for x in set(s.added_by for s in all_sc)})
    db.close()
else:
    print("  [SKIP] 没有可踢出的活跃 claim")

# ============================================================
# Step 4: A6 改裁决 rejected → accepted → 验证 adjudicated_at 不变
# ============================================================
_section("Step 4: A6 修改裁决: rejected → accepted")

# 先打印当前状态
db = SessionLocal()
sig_before = db.get(Signal, signal_reject_id)
print(f"改前 DB 状态:")
print(f"  status         = {sig_before.status}")
print(f"  signal_name    = {sig_before.signal_name}")
print(f"  adjudicated_at = {sig_before.adjudicated_at}")
first_adj_at = sig_before.adjudicated_at
db.close()

# 改为 accepted
status, resp = _api("PATCH", f"/signals/{signal_reject_id}", {
    "status": "accepted",
    "signal_name": "数据解释模糊性信号-经复核采纳",
    "human_rationale": "重新评估后确认这是有效信号",
})
print(f"\nHTTP {status}")
print(f"响应: {json.dumps(resp, indent=2, ensure_ascii=False, default=str)}")

db = SessionLocal()
sig_after = db.get(Signal, signal_reject_id)
print(f"\n改后 DB 状态:")
print(f"  status         = {sig_after.status}")
print(f"  signal_name    = {sig_after.signal_name}")
print(f"  updated_at     = {sig_after.updated_at}")
print(f"  adjudicated_at = {sig_after.adjudicated_at}")
if first_adj_at and sig_after.adjudicated_at:
    print(f"  adjudicated_at 是否被覆盖? {sig_after.adjudicated_at != first_adj_at} (首次={first_adj_at}, 现在={sig_after.adjudicated_at})")
db.close()

# 再改回 rejected 验证幂等
print(f"\n再改为 rejected:")
status, resp2 = _api("PATCH", f"/signals/{signal_reject_id}", {"status": "rejected"})
print(f"HTTP {status}")
db = SessionLocal()
sig_final = db.get(Signal, signal_reject_id)
print(f"  status         = {sig_final.status}")
print(f"  adjudicated_at = {sig_final.adjudicated_at} (应仍为首次时间)")
db.close()

# ============================================================
# Step 5: A5 待定 —— 确认 cg3 无对应 signal
# ============================================================
_section("Step 5: A5 待定 —— 候选组 cg3 不应有信号")

db = SessionLocal()
sig_for_cg3 = db.query(Signal).filter(Signal.candidate_group_id == cg3.id).first()
print(f"cg3.id = {cg3.id}")
print(f"对应 signal: {sig_for_cg3.id if sig_for_cg3 else 'None (待定，正确)'}")
if sig_for_cg3:
    print(f"  [WARN] 待定候选组不应有对应信号！status={sig_for_cg3.status}")

# API 列表查 cg3 的裁决状态
status, groups = _api("GET", "/candidate-groups")
cg3_in_list = [g for g in groups if g["id"] == cg3.id]
if cg3_in_list:
    print(f"\nAPI 列表中的 cg3 状态:")
    print(f"  adjudication_status = {cg3_in_list[0].get('adjudication_status')} (应为 null)")
    print(f"  signal_id           = {cg3_in_list[0].get('signal_id')} (应为 null)")
db.close()

# ============================================================
# Step 6: 数据库最终完整性快照
# ============================================================
_section("Step 6: 最终 DB 完整性快照")

db = SessionLocal()
# 所有候选组
cgs = db.query(CandidateGroup).filter(CandidateGroup.run_id == TEST_RUN_ID).all()
print(f"候选组 ({len(cgs)} 个):")
for c in cgs:
    cgc_count = db.query(CandidateGroupClaim).filter(
        CandidateGroupClaim.candidate_group_id == c.id
    ).count()
    sig = db.query(Signal).filter(Signal.candidate_group_id == c.id).first()
    print(f"  {c.group_label[:50]} | claims={c.claim_count} | cgc_rows={cgc_count} | "
          f"signal={sig.status if sig else 'None'}")

# 所有信号
sigs = db.query(Signal).order_by(Signal.created_at).all()
print(f"\n信号 ({len(sigs)} 个，全部显示):")
for s in sigs:
    sc_count = db.query(SignalClaim).filter(SignalClaim.signal_id == s.id).count()
    print(f"  id={s.id[:8]}... name={s.signal_name} status={s.status} "
          f"claim_count={s.claim_count} sc_rows={sc_count} adj_at={s.adjudicated_at}")

# signal_claims 分布
all_sc = db.query(SignalClaim).all()
by_type = {}
for sc in all_sc:
    by_type[sc.added_by] = by_type.get(sc.added_by, 0) + 1
print(f"\nsignal_claims 全部行分布: {by_type}")
db.close()

# ============================================================
# 清理
# ============================================================
_section("清理测试数据")
db = SessionLocal()
# 删 signal_claims
test_sig_ids = [s.id for s in db.query(Signal).join(
    CandidateGroup, Signal.candidate_group_id == CandidateGroup.id
).filter(CandidateGroup.run_id == TEST_RUN_ID).all()]
for sid in test_sig_ids:
    db.query(SignalClaim).filter(SignalClaim.signal_id == sid).delete()
    db.query(Signal).filter(Signal.id == sid).delete()
print(f"  删除 {len(test_sig_ids)} 个信号及其 claims")

# 删 candidate_group_claims
test_cg_ids = [r[0] for r in db.query(CandidateGroup.id).filter(
    CandidateGroup.run_id == TEST_RUN_ID
).all()]
for cgid in test_cg_ids:
    db.query(CandidateGroupClaim).filter(CandidateGroupClaim.candidate_group_id == cgid).delete()
    db.query(CandidateGroup).filter(CandidateGroup.id == cgid).delete()
print(f"  删除 {len(test_cg_ids)} 个候选组")

db.commit()
db.close()
print("清理完成。")

_section("实测完毕")
