import { useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  MiniMap,
  Panel,
  Position,
  ReactFlow,
  type AriaLabelConfig,
  type Edge,
  type Node,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { NodeRunRead } from "../api/runs";
import type { WorkflowRead } from "../api/tasks";
import { humanize } from "../utils/format";
import { getNodeStatusColor } from "../utils/workflow";

const ARIA_LABEL_CONFIG = {
  "node.a11yDescription.default": "按回车键或空格键选择节点。",
  "node.a11yDescription.keyboardDisabled": "按回车键或空格键选择节点。",
  "node.a11yDescription.ariaLiveMessage": () => "节点位置已更新。",
  "edge.a11yDescription.default": "按回车键或空格键选择连线。",
  "controls.ariaLabel": "流程图控制面板",
  "controls.zoomIn.ariaLabel": "放大",
  "controls.zoomOut.ariaLabel": "缩小",
  "controls.fitView.ariaLabel": "适应视图",
  "controls.interactive.ariaLabel": "切换交互模式",
  "minimap.ariaLabel": "工作流缩略图",
  "handle.ariaLabel": "连接点",
} satisfies Partial<AriaLabelConfig>;

const ACTIVE_STATUSES = new Set(["running", "reviewing", "retrying"]);
const HORIZONTAL_GAP = 330;
const VERTICAL_GAP = 172;

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

function buildNodePosition(
  layer: number,
  row: number,
  layerSize: number,
  largestLayerSize: number,
): { x: number; y: number } {
  const layerOffset = ((largestLayerSize - layerSize) * VERTICAL_GAP) / 2;
  return {
    x: layer * HORIZONTAL_GAP,
    y: layerOffset + row * VERTICAL_GAP,
  };
}

function edgeStatus(sourceStatus: string, targetStatus: string): "active" | "completed" | "pending" {
  if (targetStatus === "completed") {
    return "completed";
  }
  if (sourceStatus === "completed" && ACTIVE_STATUSES.has(targetStatus)) {
    return "active";
  }
  return "pending";
}

export function WorkflowGraph({
  workflow,
  nodeRuns = [],
  selectedNodeKey,
  onSelectNode,
}: WorkflowGraphProps) {
  const graph = useMemo(() => {
    const layers = calculateLayers(workflow);
    const runByKey = new Map(nodeRuns.map((nodeRun) => [nodeRun.node_key, nodeRun]));
    const nodesByLayer = new Map<number, typeof workflow.nodes>();
    workflow.nodes.forEach((node) => {
      const layer = layers.get(node.key) ?? 0;
      nodesByLayer.set(layer, [...(nodesByLayer.get(layer) ?? []), node]);
    });
    nodesByLayer.forEach((nodes) => nodes.sort((left, right) => left.sort_order - right.sort_order));
    const largestLayerSize = Math.max(1, ...[...nodesByLayer.values()].map((nodes) => nodes.length));

    const nodes: Node[] = workflow.nodes.map((node) => {
      const layer = layers.get(node.key) ?? 0;
      const peers = nodesByLayer.get(layer) ?? [];
      const row = peers.findIndex((peer) => peer.key === node.key);
      const nodeRun = runByKey.get(node.key);
      const status = nodeRun?.status ?? "pending";
      const statusLabel = nodeRun ? humanize(status) : "等待执行";
      const selected = selectedNodeKey === node.key;
      const isFinal = workflow.final_node === node.key;
      const dependencyLabel = node.depends_on.length > 0 ? `${node.depends_on.length} 项依赖` : "起始节点";
      const toolLabel = node.tools.length > 0 ? `${node.tools.length} 个工具` : "无需工具";

      return {
        id: node.key,
        ariaLabel: `${node.name}，${humanize(node.role)}，${statusLabel}`,
        className: [
          "workflow-node",
          `workflow-node--${status}`,
          selected ? "workflow-node--selected" : "",
          isFinal ? "workflow-node--final" : "",
        ]
          .filter(Boolean)
          .join(" "),
        position: buildNodePosition(layer, row, peers.length, largestLayerSize),
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        data: {
          label: (
            <div className="graph-node-card" title={node.description}>
              <div className="graph-node-heading">
                <span className="graph-node-stage">阶段 {layer + 1}</span>
                {isFinal ? <span className="graph-final-badge">最终输出</span> : null}
              </div>
              <strong>{node.name}</strong>
              <span className="graph-node-role">{humanize(node.role)}</span>
              <div className="graph-node-meta">
                <span className={`graph-status graph-status--${status}`}>
                  <i aria-hidden="true" />
                  {statusLabel}
                </span>
                {nodeRun && nodeRun.attempt > 1 ? <span>第 {nodeRun.attempt} 次尝试</span> : null}
              </div>
              <div className="graph-node-footnote">
                <span>{dependencyLabel}</span>
                <span>{toolLabel}</span>
              </div>
            </div>
          ),
        },
      };
    });

    const edges: Edge[] = workflow.edges.map((edge) => {
      const sourceStatus = runByKey.get(edge.source_node_key)?.status ?? "pending";
      const targetStatus = runByKey.get(edge.target_node_key)?.status ?? "pending";
      const phase = edgeStatus(sourceStatus, targetStatus);
      const stroke = phase === "completed" ? "#16a34a" : phase === "active" ? "#2563eb" : "#94a3b8";
      return {
        id: edge.id,
        source: edge.source_node_key,
        target: edge.target_node_key,
        ariaLabel: `从 ${edge.source_node_key} 到 ${edge.target_node_key} 的依赖连线`,
        animated: phase === "active",
        className: `workflow-edge workflow-edge--${phase}`,
        markerEnd: { type: MarkerType.ArrowClosed, color: stroke },
        style: {
          stroke,
          strokeDasharray: phase === "pending" ? "6 5" : undefined,
          strokeWidth: phase === "active" ? 2.6 : 2,
        },
      };
    });

    const statusCounts = nodeRuns.reduce<Record<string, number>>((counts, nodeRun) => {
      counts[nodeRun.status] = (counts[nodeRun.status] ?? 0) + 1;
      return counts;
    }, {});
    const activeCount = [...ACTIVE_STATUSES].reduce(
      (total, status) => total + (statusCounts[status] ?? 0),
      0,
    );

    return {
      activeCount,
      completedCount: statusCounts.completed ?? 0,
      failedCount: statusCounts.failed ?? 0,
      nodes,
      edges,
    };
  }, [nodeRuns, selectedNodeKey, workflow]);

  const handleNodeClick: NodeMouseHandler = (_, node) => onSelectNode(node.id);

  return (
    <div className="workflow-graph" aria-label="工作流依赖图">
      <ReactFlow
        ariaLabelConfig={ARIA_LABEL_CONFIG}
        edges={graph.edges}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        maxZoom={1.5}
        minZoom={0.35}
        nodes={graph.nodes}
        nodesConnectable={false}
        nodesDraggable={false}
        onNodeClick={handleNodeClick}
        onlyRenderVisibleElements
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#dce5f0" gap={24} size={1.2} variant={BackgroundVariant.Dots} />
        <Panel className="graph-summary" position="top-left">
          <span><strong>{workflow.nodes.length}</strong> 个节点</span>
          {nodeRuns.length > 0 ? (
            <>
              <span className="summary-completed"><strong>{graph.completedCount}</strong> 已完成</span>
              <span className="summary-active"><strong>{graph.activeCount}</strong> 执行中</span>
              {graph.failedCount > 0 ? <span className="summary-failed"><strong>{graph.failedCount}</strong> 失败</span> : null}
            </>
          ) : null}
        </Panel>
        <Panel className="graph-legend" position="bottom-left">
          <span><i className="legend-dot legend-dot--pending" />等待</span>
          <span><i className="legend-dot legend-dot--running" />执行</span>
          <span><i className="legend-dot legend-dot--reviewing" />审核</span>
          <span><i className="legend-dot legend-dot--completed" />完成</span>
          <span><i className="legend-dot legend-dot--failed" />失败</span>
        </Panel>
        <MiniMap
          aria-label="工作流缩略图"
          className="graph-minimap"
          maskColor="rgb(241 245 249 / 72%)"
          nodeColor={(node) => {
            const status = node.className?.toString().match(/workflow-node--([a-z]+)/)?.[1] ?? "pending";
            return getNodeStatusColor(status);
          }}
          pannable
          zoomable
        />
        <Controls aria-label="流程图控制面板" showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
