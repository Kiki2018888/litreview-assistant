// ============================================================================
// Signals / 机会工作台 API
// 一律带 project_id（裁决按项目隔离）
// ============================================================================

import { apiGet, apiPost, buildQuery } from "./client"
import type {
  AdjudicateRequest,
  CandidateGroup,
  CandidateGroupDetail,
  CandidateType,
  ClaimsListResponse,
  DiscoverResponse,
  JobStatusResponse,
  Signal,
  SignalDetail,
} from "../types"

export type TypeFilter = "all" | CandidateType

export interface CandidateListFilters {
  type?: TypeFilter
  status?: "pending" | "accepted" | "rejected"
  /** false = 仅主路径；true = 仅弱候选；omit = 全部 */
  is_weak?: boolean
  previously_rejected?: boolean
  run_id?: string
}

function adjQuery(
  projectId: string,
  extra: Record<string, string | number | boolean | null | undefined> = {},
): string {
  return buildQuery({ project_id: projectId, ...extra })
}

export function listCandidateGroups(
  projectId: string,
  filters: CandidateListFilters = {},
): Promise<CandidateGroup[]> {
  const type = filters.type && filters.type !== "all" ? filters.type : undefined
  return apiGet<CandidateGroup[]>(
    `/adjudication/candidate-groups${adjQuery(projectId, {
      type,
      status: filters.status,
      is_weak: filters.is_weak,
      previously_rejected: filters.previously_rejected,
      run_id: filters.run_id,
    })}`,
  )
}

export function getCandidateGroup(
  projectId: string,
  groupId: string,
): Promise<CandidateGroupDetail> {
  return apiGet<CandidateGroupDetail>(
    `/adjudication/candidate-groups/${groupId}${adjQuery(projectId)}`,
  )
}

export function listSignals(
  projectId: string,
  opts: { status?: "pending" | "accepted" | "rejected"; type?: TypeFilter } = {},
): Promise<Signal[]> {
  const type = opts.type && opts.type !== "all" ? opts.type : undefined
  return apiGet<Signal[]>(
    `/adjudication/signals${adjQuery(projectId, { status: opts.status, type })}`,
  )
}

export function getSignalDetail(
  projectId: string,
  signalId: string,
): Promise<SignalDetail> {
  return apiGet<SignalDetail>(
    `/adjudication/signals/${signalId}${adjQuery(projectId)}`,
  )
}

export function adjudicate(
  projectId: string,
  body: AdjudicateRequest,
): Promise<Signal> {
  return apiPost<Signal>(`/adjudication/signals${adjQuery(projectId)}`, body)
}

export function discoverOpportunities(
  projectId: string,
  force = false,
): Promise<DiscoverResponse> {
  return apiPost<DiscoverResponse>(`/projects/${projectId}/discover`, { force })
}

export function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  return apiGet<JobStatusResponse>(`/jobs/${jobId}/status`)
}

export function getProjectClaimsTotal(projectId: string): Promise<number> {
  return apiGet<ClaimsListResponse>(
    `/projects/${projectId}/claims${buildQuery({ limit: 1 })}`,
  ).then((res) => res.total)
}

/** 从 409 文案中解析已在跑的 discover job_id */
export function parseJobIdFromError(message: string): string | null {
  const match = message.match(/job_id=([0-9a-f-]{36})/i)
  return match?.[1] ?? null
}
