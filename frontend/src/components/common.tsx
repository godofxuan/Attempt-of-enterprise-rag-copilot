import { useRef, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { ApiError, failureMessage } from "../api/client";
export function ErrorNotice({ error }: { error: unknown }) {
  return (
    <div role="alert" className="error">
      <strong>{failureMessage(error)}</strong>
      <details>
        <summary>查看原因</summary>
        <pre>
          {error instanceof ApiError
            ? JSON.stringify(
                { code: error.code, message: error.message, data: error.data },
                null,
                2,
              )
            : error instanceof Error
              ? error.message
              : String(error)}
        </pre>
      </details>
    </div>
  );
}
export function Drawer({
  title,
  children,
  open,
  onClose,
  initialFocus,
}: {
  title: string;
  children: ReactNode;
  open: boolean;
  onClose: () => void;
  initialFocus?: string;
}) {
  const returnFocus = useRef<HTMLElement | null>(null);
  const content = useRef<HTMLDivElement | null>(null);
  return (
    <Dialog.Root open={open} onOpenChange={(v) => !v && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="overlay" />
        <Dialog.Content
          ref={content}
          className="drawer"
          onOpenAutoFocus={(event) => {
            returnFocus.current = document.activeElement as HTMLElement | null;
            const target = initialFocus
              ? content.current?.querySelector<HTMLElement>(initialFocus)
              : null;
            if (target) {
              event.preventDefault();
              target.focus();
            }
          }}
          onCloseAutoFocus={(event) => {
            if (returnFocus.current?.isConnected) {
              event.preventDefault();
              returnFocus.current.focus();
            }
          }}
        >
          <div className="drawer-heading">
            <Dialog.Title>{title}</Dialog.Title>
            <Dialog.Close aria-label="关闭详情">×</Dialog.Close>
          </div>
          <Dialog.Description className="sr-only">
            查看当前详情，关闭后继续原会话。
          </Dialog.Description>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
export function Parameters({ value }: { value: Record<string, unknown> }) {
  const names: Record<string, string> = {
    loan_start: "开始日期",
    loan_end: "结束日期",
    purpose: "用途",
    asset_id: "设备",
    description: "故障描述",
    impact: "影响程度",
    min_memory_gb: "最低内存（GB）",
    memory_gb: "内存（GB）",
    pickup_location: "领取地点",
    date_flex_days: "允许晚几天",
  };
  return (
    <dl className="parameters">
      {Object.entries(value)
        .filter(([, v]) => v != null)
        .map(([k, v]) => (
          <div key={k}>
            <dt>{names[k] || k}</dt>
            <dd>{String(v)}</dd>
          </div>
        ))}
    </dl>
  );
}
