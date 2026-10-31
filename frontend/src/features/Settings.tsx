import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Status, type JSONRecord } from "../api/client";
import { ErrorNotice } from "../components/common";
export function SettingsPage() {
  const cache = useQueryClient();
  const instance = useQuery({
    queryKey: ["instance"],
    queryFn: () => api<JSONRecord>("/api/instance"),
  });
  const q = useQuery({
    queryKey: ["settings"],
    queryFn: () => api<JSONRecord>("/api/settings"),
  });
  const s = useQuery({
    queryKey: ["status"],
    queryFn: () => api<Status>("/api/status"),
  });
  const [draft, setDraft] = useState<JSONRecord>({});
  const settings = { ...q.data, ...draft };
  const refresh = () =>
    Promise.all(
      [["settings"], ["status"], ["instance"]].map((queryKey) =>
        cache.invalidateQueries({ queryKey }),
      ),
    );
  const saveSettings = useMutation({
    mutationFn: () => api<JSONRecord>("/api/settings", "PATCH", draft),
    onSuccess: (value) => {
      cache.setQueryData(["settings"], value);
      setDraft({});
      void refresh();
    },
  });
  const enableDemo = useMutation({
    mutationFn: () => api("/api/product/setup-demo", "POST", {}),
    onSuccess: () => refresh(),
  });
  const completeSetup = useMutation({
    mutationFn: () => api("/api/product/setup-complete", "POST", {}),
    onSuccess: () => refresh(),
  });
  const shutdown = useMutation({
    mutationFn: () => api("/api/product/shutdown", "POST", {}),
  });
  return (
    <div className="settings-page">
      <div>
        <p className="eyebrow">次级工具</p>
        <h1>设置</h1>
      </div>
      <section className="card">
        <h2>当前工作区与版本</h2>
        <p className="path">{s.data?.data_dir}</p>
        <p>版本 {instance.data?.version || "未知"}</p>
        <p className="muted">
          文档、索引、会话和工单保存在同一目录。升级不重建它；切换工作区需在启动器明确选择。
        </p>
        <details>
          <summary>构建详情</summary>
          <p className="path">{instance.data?.build_id || "未报告"}</p>
          {instance.data?.source_dirty && <p>源码工作区含未提交修改。</p>}
        </details>
      </section>
      <section className="card">
        <h2>本地模型连接</h2>
        <p>
          {s.data?.chat.ready
            ? "聊天模型已连接"
            : "模型尚未就绪，仍可查看历史和设置。"}
        </p>
        {(q.error || s.error) && <ErrorNotice error={q.error || s.error} />}
        {saveSettings.error && <ErrorNotice error={saveSettings.error} />}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            saveSettings.mutate();
          }}
        >
          <label>
            Ollama 服务地址
            <input
              type="url"
              required
              value={settings.model_endpoint || ""}
              disabled={saveSettings.isPending}
              onChange={(e) =>
                setDraft({ ...draft, model_endpoint: e.target.value })
              }
            />
          </label>
          {[
            ["chat_model", "聊天模型"],
            ["embedding_model", "嵌入模型"],
          ].map(([key, title]) => (
            <label key={key}>
              {title}
              <input
                list="installedModels"
                required
                value={settings[key] || ""}
                disabled={saveSettings.isPending}
                onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
              />
            </label>
          ))}
          <datalist id="installedModels">
            {s.data?.models.map((m) => (
              <option key={m.name} value={m.name} />
            ))}
          </datalist>
          <details>
            <summary>高级连接选项</summary>
            <label>
              单次请求超时（秒）
              <input
                type="number"
                min={1}
                max={300}
                value={settings.request_timeout_seconds || 90}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    request_timeout_seconds: Number(e.target.value),
                  })
                }
              />
            </label>
            <p className="muted">
              新解释实验
              {settings.experimental_grounded_expression
                ? "已显式启用，仅供实验"
                : "保持关闭"}
              ，不作为稳定能力。
            </p>
          </details>
          <button className="primary" disabled={saveSettings.isPending}>
            保存连接设置
          </button>
          {saveSettings.isSuccess && <p role="status">设置已保存。</p>}
        </form>
        <p className="muted">
          只使用本机已有模型，日常启动不下载模型或安装依赖。
        </p>
        <details>
          <summary>模型没有连接时怎么办？</summary>
          <p>
            先启动本机Ollama，在这里选择已经安装的模型；没有安装模型时，可自行在官方应用中准备后回来连接。
          </p>
        </details>
      </section>
      <section className="card">
        <h2>本地合成演示</h2>
        <p>只在本地TEST数据中办理，不连接企业审批系统。</p>
        {enableDemo.error && <ErrorNotice error={enableDemo.error} />}
        <button
          disabled={s.data?.mode === "SYNTHETIC_LOCAL" || enableDemo.isPending}
          onClick={() => enableDemo.mutate()}
        >
          {s.data?.mode === "SYNTHETIC_LOCAL"
            ? "演示数据已启用"
            : "启用本地演示数据"}
        </button>
        {!s.data?.onboarding_complete && (
          <button onClick={() => completeSetup.mutate()}>
            已了解，进入助理
          </button>
        )}
      </section>
      <section className="card">
        <h2>诊断与恢复</h2>
        <button onClick={() => refresh()}>重新检查连接</button>
        <button
          onClick={() => {
            if (
              window.confirm("停止本地服务？资料和工单会保留，下次双击可继续。")
            )
              shutdown.mutate();
          }}
        >
          停止本地服务
        </button>
        {shutdown.error && <ErrorNotice error={shutdown.error} />}
        <details>
          <summary>诊断详情</summary>
          <pre>{JSON.stringify(s.data, null, 2)}</pre>
        </details>
      </section>
    </div>
  );
}
