import { useQuery } from "@tanstack/react-query";
import { Navigate, useParams } from "react-router-dom";

import { getColony } from "../api/colonies";
import { formatError } from "../utils/format";

/** Compatibility resolver: the actual workspace is always addressed by Session. */
export function ColonyWorkspacePage() {
  const { colonyId } = useParams();
  const colonyQuery = useQuery({
    queryKey: ["colony", colonyId],
    queryFn: () => getColony(requireId(colonyId)),
    enabled: Boolean(colonyId),
  });

  if (colonyQuery.isLoading) return <div className="panel loading-panel">正在打开 Colony…</div>;
  if (colonyQuery.isError || !colonyQuery.data) {
    return <div className="panel error-panel"><h2>无法打开 Colony</h2><p>{formatError(colonyQuery.error)}</p></div>;
  }
  return <Navigate replace to={`/sessions/${colonyQuery.data.session.id}`} />;
}

function requireId(value: string | undefined): string {
  if (!value) throw new Error("缺少 Colony 标识");
  return value;
}
