import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Status, type JSONRecord } from "../api/client";
import { ErrorNotice } from "../components/common";
export function SettingsPage() {
  const instance = useQuery({queryKey:["instance"], queryFn:()=>api<JSONRecord>("/api/instance")});
  const cache = useQueryClient();
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
  const mutation = useMutation({
    mutationFn: async () => {
      await api("/api/settings", "PATCH", draft);
      setDraft({});
      await cache.invalidateQueries();
    },
  });
  return (
    <div className="settings-page">
      <p className="eyebrow">次级工具</p>
      <h1>设置</h1>
      <section className="card"><h2>当前运行版本</h2>
        <p>版本 {instance.data?.version || "未知"}</p>
        <p className="muted">构建 {instance.data?.build_id || "未报告"}</p>
        {instance.data?.source_dirty && <p>源码工作区含未提交修改。</p>}
      </section>
      {!s.data?.onboarding_complete && (
        <p>
          首次配置：确认下方工作区，连接已有模型，再到资料库导入文件；需要业务演示时明确启用
          TEST 数据。
        </p>
      )}
      <h2>本地模型</h2>
      <p>
        {s.data?.chat.ready
          ? "聊天模型已连接"
          : "模型尚未就绪，仍可查看历史和设置。"}
      </p>
      {mutation.error && <ErrorNotice error={mutation.error} />}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
      >
        <label>
          Ollama 服务地址
          <input
            type="url"
            required
            value={settings.model_endpoint || ""}
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
              onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
            />
          </label>
        ))}
        <datalist id="installedModels">
          {s.data?.models.map((m) => (
            <option key={m.name} value={m.name} />
          ))}
        </datalist>
        <button className="primary" disabled={mutation.isPending}>
          保存连接设置
        </button>
        {mutation.isSuccess && <p role="status">设置已保存。</p>}
      </form>
      <p className="muted">
        只使用本机已有模型。本应用不会在日常启动时下载模型或安装依赖。
      </p>
      <details>
        <summary>模型没有连接时怎么办？</summary>
        <p>
          先启动本机 Ollama，在这里选择已经安装的模型。没有安装模型时，可自行在
          Ollama 官方应用中准备后回来连接。
        </p>
      </details>
      <h2>本地演示数据</h2>
      <p>启用合成设备、借用与报修规则，只在本地 TEST 数据中办理。</p>
      <button
        disabled={s.data?.mode === "SYNTHETIC_LOCAL"}
        onClick={async () => {
          await api("/api/product/setup-demo", "POST", {});
          await cache.invalidateQueries();
        }}
      >
        {s.data?.mode === "SYNTHETIC_LOCAL"
          ? "演示数据已启用"
          : "启用本地演示数据"}
      </button>
      <h2>当前工作区</h2>
      <p className="path">{s.data?.data_dir}</p>
      <p>
        文档、索引、会话和工单保存在同一目录，升级应用不会重建它。切换工作区使用启动器明确选择并重新打开。
      </p>
      <h2>诊断与恢复</h2>
      <button
        onClick={async () => {
          if (
            window.confirm("停止本地服务？资料和工单会保留，下次双击可继续。")
          )
            await api("/api/product/shutdown", "POST", {});
        }}
      >
        停止本地服务
      </button>
      <button onClick={() => cache.invalidateQueries()}>重新检查连接</button>
      {!s.data?.onboarding_complete && (
        <button
          onClick={async () => {
            await api("/api/product/setup-complete", "POST", {});
            await cache.invalidateQueries();
          }}
        >
          已了解，进入助理
        </button>
      )}
      <details>
        <summary>诊断详情</summary>
        <pre>{JSON.stringify(s.data, null, 2)}</pre>
      </details>
    </div>
  );
}
