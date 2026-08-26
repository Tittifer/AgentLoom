import { useMemo } from "react";
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { NodeRunRead } from "../api/runs";
import type { WorkflowRead } from "../api/tasks";
import { getNodeStatusColor } from "../utils/workflow";

interface WorkflowGraphProps {
  workflow: WorkflowRead;
  nodeRuns?: NodeRunRead[];
  selectedNodeKey?: string;
  onSelectNode: (nodeKey: string) => void;
}

function calculateLayers(workflow: WorkflowRead): Map<string, number> {
  const nodesByKey = new Map(workflow.nodes.map((node) => [node.key, node]));
  const layers = new Map<string, number>();

  function visit(nodeKey: string, visiting = new Set<string>()): number {
    const known = layers.get(nodeKey);
    if (known !== undefined) {
      return known;
    }
    if (visiting.has(nodeKey)) {
      return 0;
    }
    const node = nodesByKey.get(nodeKey);
    if (!node || node.depends_on.length === 0) {
      layers.set(nodeKey, 0);
      return 0;
    }
    const nextVisiting = new Set(visiting).add(nodeKey);
    const layer = Math.max(...node.depends_on.map((key) => visit(key, nextVisiting))) + 1;
    layers.set(nodeKey, layer);
    return layer;
  }

  workflow.nodes.forEach((node) => visit(node.key));
  return layers;
}

export function WorkflowGraph({
  workflow,
  nodeRuns = [],
  selectedNodeKey,
  onSelectNode,
}: WorkflowGraphProps) {
  const graph = useMemo(() => {
    const layers = calculateLayers(workflow);
    const statusByKey = new Map(nodeRuns.map((nodeRun) => [nodeRun.node_key, nodeRun.status]));
    const nodesByLayer = new Map<number, typeof workflow.nodes>();
    workflow.nodes.forEach((node) => {
      const layer = layers.get(node.key) ?? 0;
      nodesByLayer.set(layer, [...(nodesByLayer.get(layer) ?? []), node]);
    });

    const nodes: Node[] = workflow.nodes.map((node) => {
      const layer = layers.get(node.key) ?? 0;
      const peers = (nodesByLayer.get(layer) ?? []).sort(
        (left, right) => left.sort_order - right.sort_order,
      );
      const row = peers.findIndex((peer) => peer.key === node.key);
      const status = statusByKey.get(node.key) ?? "pending";
      const selected = selectedNodeKey === node.key;
      return {
        id: node.key,
        position: { x: layer * 285, y: row * 145 },
        data: {
          label: (
            <div className="graph-node-label">
              <strong>{node.name}</strong>
              <span>{node.role}</span>
              {nodeRuns.length > 0 ? <small>{status}</small> : null}
            </div>
          ),
        },
        style: {
          width: 210,
          padding: 14,
          border: `2px solid ${selected ? "#172033" : getNodeStatusColor(status)}`,
          borderRadius: 12,
          background: "#ffffff",
          boxShadow: selected ? "0 0 0 4px rgb(49 91 214 / 14%)" : "0 8px 20px rgb(15 23 42 / 8%)",
        },
      };
    });

    const edges: Edge[] = workflow.edges.map((edge) => ({
      id: edge.id,
      source: edge.source_node_key,
      target: edge.target_node_key,
      markerEnd: { type: MarkerType.ArrowClosed },
      style: { stroke: "#94a3b8", strokeWidth: 1.6 },
    }));
    return { nodes, edges };
  }, [nodeRuns, selectedNodeKey, workflow]);

  const handleNodeClick: NodeMouseHandler = (_, node) => onSelectNode(node.id);

  return (
    <div className="workflow-graph" aria-label="Workflow dependency graph">
      <ReactFlow
        edges={graph.edges}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        nodes={graph.nodes}
        nodesConnectable={false}
        nodesDraggable={false}
        onNodeClick={handleNodeClick}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#d5deea" gap={22} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
