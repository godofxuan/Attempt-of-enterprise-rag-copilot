import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, type Run } from "./client";
export function useRun(runId: string | null, onFinished: () => void) {
  const cache = useQueryClient();
  const [progress, setProgress] = useState("正在准备");
  useEffect(() => {
    if (!runId) return;
    let disposed = false,
      source: EventSource | undefined,
      reconnect: ReturnType<typeof setTimeout> | undefined;
    let cursor = Number(sessionStorage.getItem("esa-cursor-" + runId) || 0);
    let done = false;
    const finish = () => {
      if (disposed || done) return;
      done = true;
      source?.close();
      cache.invalidateQueries();
      onFinished();
    };
    const connect = async () => {
      try {
        const run = await api<Run>("/api/runs/" + runId);
        if (disposed) return;
        if (!["queued", "running"].includes(run.status)) {
          finish();
          return;
        }
        source = new EventSource(
          "/api/runs/" + runId + "/events?after_seq=" + cursor,
        );
        source.addEventListener("progress", (event) => {
          if (disposed) return;
          const row = JSON.parse((event as MessageEvent).data);
          cursor = row.seq;
          sessionStorage.setItem("esa-cursor-" + runId, String(cursor));
          setProgress(
            row.kind === "queued"
              ? "等待处理"
              : row.kind === "running"
                ? "正在检索资料或处理事项"
                : "正在读取结果",
          );
          if (
            ["finished", "failed", "cancelled", "interrupted"].includes(
              row.kind,
            )
          )
            finish();
        });
        source.onerror = () => {
          source?.close();
          if (!disposed && !done) reconnect = setTimeout(connect, 1200);
        };
      } catch {
        if (!disposed) reconnect = setTimeout(connect, 1500);
      }
    };
    connect();
    return () => {
      disposed = true;
      source?.close();
      clearTimeout(reconnect);
    };
  }, [runId, cache, onFinished]);
  return progress;
}
