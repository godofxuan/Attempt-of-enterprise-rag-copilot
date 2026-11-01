import { useEffect, useRef, useState } from "react";
import {
  useMutation,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import {
  api,
  ApiError,
  type Task,
  type Run,
  type JSONRecord,
  type Conversation,
} from "./client";

export async function retryConversationTurn(
  cid: string,
  turnId: string,
  knowledge = false,
) {
  if (knowledge) {
    const current = await api<Conversation>(`/api/conversations/${cid}`);
    if (!current.kb_id)
      throw new ApiError(
        "KNOWLEDGE_BASE_REQUIRED",
        "请先选择资料库后继续解释。",
        409,
      );
    // Explicit recovery also repairs old empty commands when the selected KB
    // has not changed. The host preserves completed and nonempty scopes.
    await api<Conversation>(`/api/conversations/${cid}`, "PATCH", {
      kb_id: current.kb_id,
    });
  }
  return api<Run>(
    `/api/product/conversations/${cid}/turns/${turnId}/retry`,
    "POST",
    {},
  );
}

export function refreshTaskScope(
  cache: QueryClient,
  id: string,
  cid?: string | null,
) {
  const keys: readonly unknown[][] = [
    ["task", id],
    ["alternatives", id],
    ["tasks"],
    ["conversations"],
  ];
  return Promise.all(
    [
      ...keys,
      ...(cid
        ? [
            ["conversation", cid],
            ["conversation-runs", cid],
          ]
        : []),
    ].map((queryKey) => cache.invalidateQueries({ queryKey })),
  );
}

export function refreshRunScope(cache: QueryClient, run: Run) {
  const input = JSON.parse(run.input_json || "{}");
  if (input.task_id)
    void refreshTaskScope(cache, input.task_id, run.conversation_id);
  else if (run.conversation_id) {
    void cache.invalidateQueries({
      queryKey: ["conversation", run.conversation_id],
    });
    void cache.invalidateQueries({
      queryKey: ["conversation-runs", run.conversation_id],
    });
  }
  void cache.invalidateQueries({ queryKey: ["conversations"] });
  void cache.invalidateQueries({ queryKey: ["status"] });
}

type Target = { id: string; revision: number };
type Feedback = { message: string; error?: unknown; detail?: unknown };

export function useTaskActions(
  id: string | null,
  onRun: (run: Run, cid?: string | null) => void,
) {
  const cache = useQueryClient();
  const currentId = useRef(id);
  currentId.current = id;
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  useEffect(() => setFeedback(null), [id]);
  const tell = (target: string, value: Feedback) => {
    if (currentId.current === target) setFeedback(value);
  };
  const accept = async (view: Task, message: string) => {
    // A successful write is authoritative immediately, before the next operation.
    await cache.cancelQueries({ queryKey: ["task", view.id], exact: true });
    cache.setQueryData(["task", view.id], view);
    tell(view.id, { message });
    void refreshTaskScope(cache, view.id, view.conversation_id);
  };
  const failed = (error: unknown, target: string) => {
    if (
      error instanceof ApiError &&
      ["RESOURCE_SELECTION_REQUIRED", "MISSING_FIELDS"].includes(error.code)
    ) {
      tell(target, {
        message:
          error.code === "RESOURCE_SELECTION_REQUIRED"
            ? "参数已保存，请选择设备。"
            : "参数已保存，请补充下方必填信息。",
        detail: error,
      });
    } else
      tell(target, { message: "已保存的内容保留；这一步尚未完成。", error });
    void refreshTaskScope(cache, target);
  };
  const prepareTask = useMutation({
    mutationFn: ({ id, revision }: Target) =>
      api<Task>(`/api/product/tasks/${id}/prepare`, "POST", {
        expected_facts_revision: revision,
      }),
    onSuccess: (view) => accept(view, "当前预览已生成，请核对实际内容。"),
    onError: (error, target) => failed(error, target.id),
  });
  const afterSaved = (view: Task) => {
    if (view.next_action?.kind === "input")
      tell(view.id, { message: "参数已保存，请补充下方必填信息。" });
    else if (view.next_action?.kind === "choice")
      tell(view.id, { message: "参数已保存，请选择设备。" });
    else if (view.can_edit && !view.receipt)
      prepareTask.mutate({ id: view.id, revision: view.revision });
  };
  const saveFacts = useMutation({
    mutationFn: ({
      id,
      revision,
      changes,
    }: Target & { changes: Record<string, unknown> }) =>
      api<Task>(`/api/product/tasks/${id}/facts`, "PATCH", {
        changes,
        expected_facts_revision: revision,
      }),
    onSuccess: (view) => accept(view, "参数已保存。"),
    onError: (error, target) => failed(error, target.id),
  });
  const selectAsset = useMutation({
    mutationFn: ({
      id,
      revision,
      assetId,
      shift,
    }: Target & { assetId: string; shift: number }) =>
      api<Task>(`/api/product/tasks/${id}/asset`, "POST", {
        asset_id: assetId,
        date_shift_days: shift,
        expected_facts_revision: revision,
      }),
    onSuccess: (view) => accept(view, "设备选择已保存。"),
    onError: (error, target) => failed(error, target.id),
  });
  const track = (run: Run) => {
    void refreshTaskScope(cache, run.target || "", run.conversation_id);
    if (run.target === currentId.current) onRun(run, run.conversation_id);
  };
  const continueTask = useMutation({
    mutationFn: (target: string) =>
      api<Run>(`/api/tasks/${target}/runs`, "POST", {}),
    onSuccess: track,
    onError: (error, target) => failed(error, target),
  });
  const retryTurn = useMutation({
    mutationFn: ({
      cid,
      turnId,
      knowledge,
    }: {
      id: string;
      cid: string;
      turnId: string;
      knowledge?: boolean;
    }) => retryConversationTurn(cid, turnId, knowledge),
    onSuccess: track,
    onError: (error, target) => failed(error, target.id),
  });
  const submitTask = useMutation({
    mutationFn: (view: Task) =>
      api<JSONRecord>(`/api/tasks/${view.id}/submit`, "POST", {
        proposal_id: view.preview!.proposal_id,
        content_digest: view.preview!.content_digest,
        expected_facts_revision: view.revision,
        accepted: true,
      }),
    onSuccess: (_, view) => {
      tell(view.id, { message: "已提交，正在读回实际工单。" });
      void refreshTaskScope(cache, view.id, view.conversation_id);
      void cache.invalidateQueries({ queryKey: ["desk"] });
    },
    onError: (error, view) => failed(error, view.id),
  });
  const cancelTask = useMutation({
    mutationFn: (view: Task) => api(`/api/tasks/${view.id}/cancel`, "POST", {}),
    onSuccess: (_, view) => {
      tell(view.id, { message: "事项已结束，已保存结果保留。" });
      void refreshTaskScope(cache, view.id, view.conversation_id);
    },
    onError: (error, view) => failed(error, view.id),
  });
  const stopRun = useMutation({
    mutationFn: ({ runId }: { id: string; runId: string }) =>
      api(`/api/runs/${runId}/cancel`, "POST", {}),
    onSuccess: (_, target) => {
      void refreshTaskScope(cache, target.id);
    },
    onError: (error, target) => failed(error, target.id),
  });
  const resolveUpdate = useMutation({
    mutationFn: (view: Task) =>
      api(`/api/tasks/${view.id}/resolve-update`, "POST", {
        execution_ceiling: view.ceiling,
        expected_facts_revision: view.revision,
        reviewed: true,
      }),
    onSuccess: (_, view) => {
      void refreshTaskScope(cache, view.id, view.conversation_id);
      continueTask.mutate(view.id);
    },
    onError: (error, view) => failed(error, view.id),
  });
  const busy = [
    saveFacts,
    prepareTask,
    selectAsset,
    continueTask,
    retryTurn,
    submitTask,
    cancelTask,
    stopRun,
    resolveUpdate,
  ].some((m) => m.isPending);
  return {
    feedback,
    clearFeedback: () => setFeedback(null),
    busy,
    saveFacts,
    prepareTask,
    selectAsset,
    continueTask,
    retryTurn,
    submitTask,
    cancelTask,
    stopRun,
    resolveUpdate,
    saveAndPrepare: (target: Target & { changes: Record<string, unknown> }) => {
      setFeedback(null);
      saveFacts.mutate(target, { onSuccess: afterSaved });
    },
    selectAndPrepare: (target: Target & { assetId: string; shift: number }) => {
      setFeedback(null);
      selectAsset.mutate(target, { onSuccess: afterSaved });
    },
  };
}
