import { CircleFilled } from "@carbon/icons-react";
import type { AgentStatus } from "@/lib/types";

const STATE_LABEL: Record<AgentStatus["state"], string> = {
  working: "Working",
  idle: "Idle",
  alert: "Needs attention",
};

export default function AgentStatusStrip({ agents }: { agents: AgentStatus[] }) {
  return (
    <div className="agent-strip">
      {agents.map((agent) => (
        <div className={`agent-chip agent-chip--${agent.state}`} key={agent.id}>
          <CircleFilled size={8} className="agent-chip__dot" />
          <div className="agent-chip__text">
            <span className="agent-chip__label">{agent.label}</span>
            <span className="agent-chip__detail">{STATE_LABEL[agent.state]} &middot; {agent.detail}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
