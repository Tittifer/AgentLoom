import type { ColonyUiEvent } from "../hooks/useColonyEvents";

interface ColonyEventStripProps {
  connected: boolean;
  events: ColonyUiEvent[];
}

export function ColonyEventStrip({ connected, events }: ColonyEventStripProps) {
  const latest = events.slice(-5).reverse();
  return (
    <section className="event-strip" aria-label="实时事件">
      <span className={`live-indicator ${connected ? "connected" : "disconnected"}`}>
        {connected ? "实时连接" : "正在重连"}
      </span>
      <div className="event-strip-list">
        {latest.length === 0 ? <span>等待 Colony 事件…</span> : null}
        {latest.map((event) => (
          <span key={`${event.id}-${event.type}`}>
            <b>#{event.id}</b> {eventLabel(event.type)}
          </span>
        ))}
      </div>
    </section>
  );
}

function eventLabel(type: string) {
  const labels: Record<string, string> = {
    "colony.created": "Colony 已创建",
    "message.created": "收到用户消息",
    "message.completed": "智能体完成消息",
    "session.started": "会话开始运行",
    "session.idle": "Queen 等待新消息",
    "session.failed": "会话执行失败",
    "worker.queued": "Worker 已排队",
    "worker.started": "Worker 开始执行",
    "worker.reported": "Worker 已向 Queen 汇报",
    "worker.timed_out": "Worker 执行超时",
    "tool.completed": "工具调用完成",
    "judge.reviewed": "质量检查完成",
    "tracker.updated": "共享 Tracker 已更新",
    "task.created": "新增任务计划",
    "task.updated": "任务计划已更新",
  };
  return labels[type] ?? type;
}
