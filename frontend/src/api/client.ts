import type { components } from "./generated";
export type Task = components["schemas"]["TaskView"];
export type Conversation = components["schemas"]["ConversationView"];
export type ConversationSummary = components["schemas"]["ConversationSummary"];
export type Answer = components["schemas"]["PublishedAnswerView"];
export type Run = components["schemas"]["RunView"];
export type Library = {
  publications?: Record<
    string,
    {
      published_run_id: string | null;
      update_state: string;
      notice?: string;
      update_error?: string | null;
    }
  >;
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
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public data: JSONRecord = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const form = body instanceof FormData;
  const response = await fetch(path, {
    method,
    signal,
    headers: {
      "X-ESA-Request": "1",
      ...(!form ? { "Content-Type": "application/json" } : {}),
    },
    body: body === undefined ? undefined : form ? body : JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok)
    throw new ApiError(
      value.error?.code ||
        (typeof value.detail === "string"
          ? value.detail.split(":")[0]
          : "REQUEST_FAILED"),
      value.error?.message ||
        (typeof value.detail === "string"
          ? value.detail
          : JSON.stringify(value.detail || "请求未完成")),
      response.status,
      value.error?.data || {},
    );
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
  const raw =
    error instanceof ApiError
      ? error.code
      : error instanceof Error
        ? error.message
        : String(error);
  const known: Record<string, string> = {
    KNOWLEDGE_BASE_REQUIRED: "请先选择一个资料库。",
    KNOWLEDGE_BASE_EMPTY: "请先导入资料。",
    INDEX_REQUIRED: "资料还没有索引，请到资料库完成处理。",
    INDEX_OUTDATED: "资料已变更，请更新索引后重试。",
    TURN_ALREADY_RUNNING: "这条消息还在处理，请等待或停止本次执行。",
    TASK_CHANGED: "事项已更新，请核对最新参数后再保存。",
    SETTINGS_IN_USE: "先完成或停止当前运行，再更换模型。",
    STORAGE_BUSY: "本地数据正在保存。已保存内容保留，请稍后重试当前操作。",
    TRANSIENT_TOOL_FAILURE:
      "数据暂时忙碌。已保存的参数和预览仍在，请重试未完成项。",
    RESOURCE_SELECTION_REQUIRED: "请展开可选设备，选择实际设备后生成预览。",
    MISSING_FIELDS: "请补齐当前参数中的必填项，再生成预览。",
    USER_INPUT_REQUIRED: "请先补充必要信息或选择设备，当前无需重复运行。",
    EXISTING_TICKET: "已有本人未关闭的申请，请到“我的事项”查看原单。",
    NOT_ELIGIBLE: "当前业务记录不满足申请资格，尚未创建申请。",
    EXECUTION_CEILING: "当前操作超出你选择的范围，未执行。",
    INSTANCE_BUSY: "实例仍有运行中的任务，请先完成或明确停止该任务。",
  };
  return known[raw] || "这次操作没有完成。请查看原因后重试。";
}
