import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent } from "react";

import { createQueen, type QueenCreate, type QueenRead } from "../api/queens";
import { formatError } from "../utils/format";

interface QueenCreateDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated?: (queen: QueenRead) => void;
}

export function QueenCreateDialog({ open, onClose, onCreated }: QueenCreateDialogProps) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: createQueen,
    onSuccess: async (queen) => {
      await queryClient.invalidateQueries({ queryKey: ["queens"] });
      onCreated?.(queen);
      onClose();
    },
  });

  function closeDialog() {
    mutation.reset();
    onClose();
  }

  if (!open) return null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload: QueenCreate = {
      name: String(form.get("name") ?? "").trim(),
      description: String(form.get("description") ?? "").trim(),
      system_prompt: String(form.get("system_prompt") ?? "").trim(),
    };
    mutation.mutate(payload);
  }

  return (
    <div className="dialog-backdrop" onMouseDown={closeDialog} role="presentation">
      <section
        aria-labelledby="create-queen-title"
        aria-modal="true"
        className="queen-create-dialog"
        onMouseDown={(event) => event.stopPropagation()}
        role="dialog"
      >
        <header className="dialog-heading">
          <div>
            <span className="eyebrow">QUEEN BEE</span>
            <h2 id="create-queen-title">新建 Queen</h2>
            <p>创建身份配置，不会离开当前工作台。</p>
          </div>
          <button aria-label="关闭新建 Queen" className="icon-button" onClick={closeDialog} type="button">×</button>
        </header>
        <form onSubmit={submit}>
          <div className="queen-form-grid">
            <label className="form-field">
              <span>名称</span>
              <input autoFocus disabled={mutation.isPending} maxLength={100} name="name" required />
            </label>
            <label className="form-field">
              <span>描述</span>
              <input disabled={mutation.isPending} maxLength={1000} name="description" />
            </label>
            <label className="form-field queen-form-wide">
              <span>系统提示词</span>
              <textarea disabled={mutation.isPending} maxLength={20000} name="system_prompt" rows={4} />
            </label>
          </div>
          {mutation.isError ? <div className="form-error" role="alert">{formatError(mutation.error)}</div> : null}
          <div className="form-actions">
            <button className="secondary-button" disabled={mutation.isPending} onClick={closeDialog} type="button">取消</button>
            <button className="primary-button" disabled={mutation.isPending} type="submit">
              {mutation.isPending ? "正在创建…" : "创建 Queen"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
