import type { components } from "./generated";
export type Task = components["schemas"]["TaskView"];
export type Conversation = components["schemas"]["ConversationView"];
export type ConversationSummary = components["schemas"]["ConversationSummary"];
export type Answer = components["schemas"]["PublishedAnswerView"];
export type Run = {
  id: string;
  kind: string;
  status: string;
  error?: string | null;
  result?: unknown;
};
export type Library = {
  bases: { id: string; name: string }[];
  documents: {
    id: string;
    kb_id: string;
    name: string;
    version: number;
    active: boolean;
    status: string;
    error?: string;
    source_key?: string;
  }[];
  jobs: { id: string; kb_id: string; status: string; error?: string }[];
  directory_sources: {
    id: string;
    path: string;
    kb_id: string;
    last_scan?: string;
  }[];
};
export type Status = {
  onboarding_complete: boolean;
  configuration_error?: { message: string; detail: string } | null;
  mode: string;
  data_dir: string;
  models: { name: string }[];
  chat: { ready: boolean; model: string };
  embedding: { ready: boolean; model: string };
  model_error?: { message: string };
  generation_calls: number;
};
export type JSONRecord = Record<string, any>;
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const form = body instanceof FormData;
  const response = await fetch(path, {
    method,
    headers: {
      "X-ESA-Request": "1",
      ...(!form ? { "Content-Type": "application/json" } : {}),
    },
    body: body === undefined ? undefined : form ? body : JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok)
    throw Error(value.error?.message || value.detail || "请求未完成");
  return value;
}
export const label: Record<string, string> = {
  PENDING_APPROVAL: "待审批，尚未分配",
  RESERVED: "已预留，待领用",
  CHECKED_OUT: "已领用",
  RETURNED: "已归还",
  CANCELLED: "已结束",
  REJECTED: "已拒绝",
  OPEN: "待受理",
  IN_PROGRESS: "处理中",
  RESOLVED: "已解决",
  CLOSED: "已关闭",
  FAILED: "处理失败",
  PARSED: "已解析",
  SUCCEEDED: "可检索",
  RUNNING: "处理中",
  QUEUED: "排队中",
  INTERRUPTED: "执行中断",
};
export function failureMessage(error: unknown) {
  const raw = error instanceof Error ? error.message : String(error);
  const known: Record<string, string> = {
    KNOWLEDGE_BASE_REQUIRED: "请先选择一个资料库。",
    KNOWLEDGE_BASE_EMPTY: "请先导入资料。",
    INDEX_REQUIRED: "资料还没有索引，请到资料库完成处理。",
    INDEX_OUTDATED: "资料已变更，请更新索引后重试。",
    TURN_ALREADY_RUNNING: "这条消息还在处理，请等待或停止本次执行。",
    TASK_CHANGED: "事项已更新，请核对最新参数后再保存。",
    SETTINGS_IN_USE: "先完成或停止当前运行，再更换模型。",
  };
  return known[raw] || "这次操作没有完成。请查看原因后重试。";
}
