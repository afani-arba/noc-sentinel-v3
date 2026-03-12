/**
 * TopologyPage — Network Map menggunakan Sigma.js v3 + Graphology
 * - ForceAtlas2 layout dari graphology-layout-forceatlas2
 * - Node warna: hijau=online, merah=offline, abu=unknown
 * - Zoom/pan native via Sigma.js (wheel + drag)
 * - Klik node untuk detail panel
 * - Filter: all / online / offline
 */
import { useState, useEffect, useRef, useCallback } from "react";
import Graph from "graphology";
import { Sigma } from "sigma";
import FA2Layout from "graphology-layout-forceatlas2/worker";
import circularLayout from "graphology-layout/circular";
import api from "@/lib/api";
import { toast } from "sonner";
import {
  RefreshCw, Maximize2, Wifi, WifiOff, GitBranch, Network,
  Activity, Cpu, MemoryStick, Clock, X, ZoomIn, ZoomOut,
  ChevronRight, Radio, Layers, Router, Server as ServerIcon
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

// ── Palette ───────────────────────────────────────────────────────────────────
const COLOR_ONLINE  = "#22c55e";
const COLOR_OFFLINE = "#ef4444";
const COLOR_UNKNOWN = "#6b7280";
const COLOR_BORDER_ONLINE  = "#16a34a";
const COLOR_BORDER_OFFLINE = "#b91c1c";
const COLOR_EDGE    = "#334155";

// ── NodeDetail Panel ──────────────────────────────────────────────────────────
function NodeDetail({ node, onClose }) {
  if (!node) return null;
  const rows = [
    { label: "IP Address", value: node.ip || "—", mono: true },
    { label: "Model",      value: node.model || "—" },
    { label: "Role",       value: node.role || "device" },
    { label: "CPU",        value: node.cpu != null ? `${node.cpu}%` : "—" },
    { label: "Memory",     value: node.memory != null ? `${node.memory}%` : "—" },
    { label: "Uptime",     value: node.uptime || "—" },
    { label: "Deskripsi",  value: node.description || "—" },
  ];
  return (
    <div className="absolute right-3 top-3 w-60 bg-card/95 backdrop-blur-sm border border-border rounded-sm shadow-2xl z-20 text-xs animate-in slide-in-from-right-2">
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border">
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full flex-shrink-0 ${node.status === "online" ? "bg-green-500 animate-pulse" : node.status === "offline" ? "bg-red-500" : "bg-gray-500"}`} />
          <span className="font-semibold text-sm truncate max-w-[160px]">{node.label}</span>
        </div>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground ml-1 flex-shrink-0">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      <div className="p-3 space-y-1.5">
        {rows.map(r => (
          <div key={r.label} className="flex justify-between items-start gap-2">
            <span className="text-muted-foreground flex-shrink-0">{r.label}</span>
            <span className={`text-right truncate max-w-[130px] ${r.mono ? "font-mono" : ""}`} title={r.value}>
              {r.value}
            </span>
          </div>
        ))}
      </div>
      <div className="px-3 pb-3">
        <Badge variant="outline" className={`text-[10px] rounded-sm w-full justify-center py-0.5 ${
          node.status === "online"
            ? "border-green-500/40 text-green-400 bg-green-500/5"
            : node.status === "offline"
            ? "border-red-500/40 text-red-400 bg-red-500/5"
            : "border-border text-muted-foreground"
        }`}>
          {node.status === "online"
            ? <><Wifi className="w-2.5 h-2.5 mr-1" />Online</>
            : node.status === "offline"
            ? <><WifiOff className="w-2.5 h-2.5 mr-1" />Offline</>
            : "Unknown"}
        </Badge>
      </div>
    </div>
  );
}

// ── SigmaContainer ─────────────────────────────────────────────────────────────
function SigmaContainer({ nodes, edges, onNodeClick, selectedId, filter }) {
  const containerRef = useRef(null);
  const sigmaRef     = useRef(null);
  const graphRef     = useRef(null);
  const layoutRef    = useRef(null);

  const buildGraph = useCallback(() => {
    const filteredNodes = nodes.filter(n => {
      if (filter === "all") return true;
      return n.status === filter;
    });
    const filteredIds = new Set(filteredNodes.map(n => n.id));
    const filteredEdges = edges.filter(e => filteredIds.has(e.source) && filteredIds.has(e.target));

    const g = new Graph({ multi: false, type: "undirected" });

    filteredNodes.forEach(n => {
      const isOnline  = n.status === "online";
      const isOffline = n.status === "offline";
      const color  = isOnline ? COLOR_ONLINE : isOffline ? COLOR_OFFLINE : COLOR_UNKNOWN;
      const border = isOnline ? COLOR_BORDER_ONLINE : isOffline ? COLOR_BORDER_OFFLINE : COLOR_UNKNOWN;
      g.addNode(n.id, {
        label:          n.label,
        color,
        borderColor:    border,
        size:           n.status === "online" ? 14 : 10,
        x:              Math.random(),
        y:              Math.random(),
        // extra data stored on node
        _status:        n.status,
        _ip:            n.ip,
        _model:         n.model,
        _role:          n.role,
        _cpu:           n.cpu,
        _memory:        n.memory,
        _uptime:        n.uptime,
        _description:   n.description,
      });
    });

    filteredEdges.forEach(e => {
      try {
        if (!g.hasNode(e.source) || !g.hasNode(e.target)) return;
        if (!g.hasEdge(e.source, e.target)) {
          g.addEdge(e.source, e.target, {
            size:  1.5,
            color: COLOR_EDGE,
          });
        }
      } catch (_) {}
    });

    return g;
  }, [nodes, edges, filter]);

  useEffect(() => {
    if (!containerRef.current || nodes.length === 0) return;

    // Cleanup previous
    if (layoutRef.current) { try { layoutRef.current.stop(); } catch (_) {} layoutRef.current = null; }
    if (sigmaRef.current)  { try { sigmaRef.current.kill(); } catch (_) {} sigmaRef.current = null; }

    const graph = buildGraph();
    graphRef.current = graph;

    // Initial circular layout to avoid all-at-origin
    circularLayout.assign(graph, { scale: 200 });

    // Create Sigma instance
    const sigma = new Sigma(graph, containerRef.current, {
      nodeProgramClasses: {},
      renderEdgeLabels:   false,
      labelSize:          11,
      labelColor:         { color: "#e2e8f0" },
      labelFont:          "JetBrains Mono, monospace",
      minCameraRatio:     0.1,
      maxCameraRatio:     10,
      defaultEdgeColor:   COLOR_EDGE,
      defaultEdgeType:    "line",
    });
    sigmaRef.current = sigma;

    // Node clicked
    sigma.on("clickNode", ({ node }) => {
      const attrs = graph.getNodeAttributes(node);
      onNodeClick({
        id:          node,
        label:       attrs.label,
        status:      attrs._status,
        ip:          attrs._ip,
        model:       attrs._model,
        role:        attrs._role,
        cpu:         attrs._cpu,
        memory:      attrs._memory,
        uptime:      attrs._uptime,
        description: attrs._description,
      });
    });

    // Stage click = deselect
    sigma.on("clickStage", () => onNodeClick(null));

    // Highlight selected node
    if (selectedId && graph.hasNode(selectedId)) {
      graph.setNodeAttribute(selectedId, "highlighted", true);
    }

    // ForceAtlas2 layout (Web Worker)
    if (graph.order > 1) {
      const layout = new FA2Layout(graph, {
        settings: {
          gravity:              1,
          scalingRatio:         4,
          strongGravityMode:    false,
          linLogMode:           false,
          barnesHutOptimize:    graph.order > 100,
          barnesHutTheta:       0.5,
          outboundAttractionDistribution: false,
          adjustSizes:          false,
          edgeWeightInfluence:  0,
          slowDown:             5,
        },
      });
      layoutRef.current = layout;
      layout.start();

      // Stop layout after 4s (settling)
      setTimeout(() => { try { layout.stop(); } catch (_) {} }, 4000);
    }

    return () => {
      if (layoutRef.current) { try { layoutRef.current.stop(); } catch (_) {} layoutRef.current = null; }
      if (sigmaRef.current)  { try { sigmaRef.current.kill(); } catch (_) {} sigmaRef.current = null; }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges, filter]);

  // Update highlighted node on selection change without full re-render
  useEffect(() => {
    const g = graphRef.current;
    if (!g || !sigmaRef.current) return;
    g.forEachNode(n => g.setNodeAttribute(n, "highlighted", n === selectedId));
    try { sigmaRef.current.refresh(); } catch (_) {}
  }, [selectedId]);

  const zoomIn  = () => { try { sigmaRef.current?.getCamera().animatedZoom({ duration: 300 }); } catch (_) {} };
  const zoomOut = () => { try { sigmaRef.current?.getCamera().animatedUnzoom({ duration: 300 }); } catch (_) {} };
  const fitView = () => { try { sigmaRef.current?.getCamera().animatedReset({ duration: 400 }); } catch (_) {} };

  return (
    <div className="relative w-full bg-[#0a0e1a] rounded-sm border border-border overflow-hidden" style={{ height: 560 }}>
      <div ref={containerRef} className="w-full h-full" />

      {/* Zoom controls */}
      <div className="absolute left-3 bottom-3 flex flex-col gap-1 z-10">
        <button onClick={zoomIn}  className="w-7 h-7 bg-card/80 border border-border rounded-sm flex items-center justify-center hover:bg-secondary/50 transition-colors text-sm font-bold text-foreground backdrop-blur-sm">+</button>
        <button onClick={zoomOut} className="w-7 h-7 bg-card/80 border border-border rounded-sm flex items-center justify-center hover:bg-secondary/50 transition-colors text-sm font-bold text-foreground backdrop-blur-sm">−</button>
        <button onClick={fitView} className="w-7 h-7 bg-card/80 border border-border rounded-sm flex items-center justify-center hover:bg-secondary/50 transition-colors backdrop-blur-sm" title="Fit View">
          <Maximize2 className="w-3 h-3" />
        </button>
      </div>

      {/* Hint */}
      <div className="absolute left-3 top-3 text-[9px] text-slate-500 z-10 pointer-events-none">
        Scroll: zoom · Drag: pan · Klik node: detail
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────────
export default function TopologyPage() {
  const [nodes,        setNodes]        = useState([]);
  const [edges,        setEdges]        = useState([]);
  const [stats,        setStats]        = useState(null);
  const [loading,      setLoading]      = useState(false);
  const [selectedNode, setSelectedNode] = useState(null);
  const [filter,       setFilter]       = useState("all");

  const fetchTopology = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get("/topology");
      setNodes(r.data.nodes || []);
      setEdges(r.data.edges || []);
      setStats(r.data.stats || null);
    } catch {
      toast.error("Gagal memuat data topology");
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchTopology(); }, [fetchTopology]);

  const handleNodeClick = useCallback((nodeData) => {
    setSelectedNode(prev => {
      if (nodeData === null) return null;
      return prev?.id === nodeData.id ? null : nodeData;
    });
  }, []);

  const filteredNodes = filter === "all" ? nodes : nodes.filter(n => n.status === filter);
  const filteredEdges = (() => {
    const ids = new Set(filteredNodes.map(n => n.id));
    return edges.filter(e => ids.has(e.source) && ids.has(e.target));
  })();

  return (
    <div className="space-y-4 pb-16">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold font-['Rajdhani'] tracking-tight flex items-center gap-2">
            <GitBranch className="w-6 h-6 text-primary" />
            Network Topology Map
          </h1>
          <p className="text-xs text-muted-foreground">
            Visualisasi topologi jaringan — powered by Sigma.js v3
            {stats ? ` · ${stats.total} device · ${stats.online} online · ${stats.offline} offline` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-sm border border-border overflow-hidden">
            {["all", "online", "offline"].map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-1.5 text-xs capitalize transition-colors ${
                  filter === f ? "bg-primary text-primary-foreground" : "hover:bg-secondary/30 text-muted-foreground"
                }`}
              >
                {f}
              </button>
            ))}
          </div>
          <Button variant="outline" size="sm" className="rounded-sm gap-2 h-8 text-xs" onClick={fetchTopology} disabled={loading}>
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Stats cards */}
      {stats && (
        <div className="flex gap-3 flex-wrap">
          {[
            { label: "Total Device",      value: stats.total,    color: "text-foreground" },
            { label: "Online",            value: stats.online,   color: "text-green-400" },
            { label: "Offline",           value: stats.offline,  color: "text-red-400" },
            { label: "Link Terdeteksi",   value: edges.length,   color: "text-cyan-400" },
          ].map(s => (
            <div key={s.label} className="bg-card border border-border rounded-sm px-4 py-2 flex flex-col items-center min-w-[90px]">
              <span className={`text-xl font-bold font-mono ${s.color}`}>{s.value}</span>
              <span className="text-[10px] text-muted-foreground uppercase tracking-wide">{s.label}</span>
            </div>
          ))}
        </div>
      )}

      {/* Legend */}
      <div className="flex items-center gap-4 text-[11px] text-muted-foreground flex-wrap">
        <div className="flex items-center gap-1.5"><div className="w-3 h-3 rounded-full bg-green-500 shadow shadow-green-500/50" /><span>Online</span></div>
        <div className="flex items-center gap-1.5"><div className="w-3 h-3 rounded-full bg-red-500" /><span>Offline</span></div>
        <div className="flex items-center gap-1.5"><div className="w-3 h-3 rounded-full bg-gray-500" /><span>Unknown</span></div>
        <div className="flex items-center gap-1.5"><div className="border border-slate-600 w-6 h-0" /><span>Link ARP</span></div>
        <span className="text-[10px]">Scroll=zoom · Drag node/canvas=pan · Klik node=detail</span>
      </div>

      {/* Sigma Canvas */}
      <div className="relative">
        {loading && nodes.length === 0 ? (
          <div className="bg-card border border-border rounded-sm h-[560px] flex items-center justify-center">
            <div className="text-center">
              <GitBranch className="w-10 h-10 text-muted-foreground/30 mx-auto mb-3 animate-pulse" />
              <p className="text-muted-foreground text-sm">Memuat topology...</p>
            </div>
          </div>
        ) : filteredNodes.length === 0 ? (
          <div className="bg-card border border-border rounded-sm h-[560px] flex items-center justify-center">
            <div className="text-center">
              <Network className="w-10 h-10 text-muted-foreground/30 mx-auto mb-3" />
              <p className="text-muted-foreground text-sm">Tidak ada device untuk ditampilkan</p>
              <p className="text-[11px] text-muted-foreground mt-1">Tambah device di menu Devices terlebih dahulu</p>
            </div>
          </div>
        ) : (
          <>
            <SigmaContainer
              nodes={filteredNodes}
              edges={filteredEdges}
              onNodeClick={handleNodeClick}
              selectedId={selectedNode?.id}
              filter={filter}
            />
            <NodeDetail node={selectedNode} onClose={() => setSelectedNode(null)} />
          </>
        )}
      </div>

      {/* Device Table */}
      {nodes.length > 0 && (
        <div className="bg-card border border-border rounded-sm">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between">
            <p className="text-xs font-semibold">Daftar Device ({filteredNodes.length})</p>
            {filter !== "all" && (
              <button onClick={() => setFilter("all")} className="text-[10px] text-primary hover:underline">Tampilkan semua</button>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-border">
                  {["Status", "Nama", "IP", "Role", "Model", "CPU", "Memory"].map(h => (
                    <th key={h} className="px-3 py-2 text-[10px] text-muted-foreground uppercase tracking-wider font-medium whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredNodes.map(n => (
                  <tr
                    key={n.id}
                    className={`border-b border-border/20 hover:bg-secondary/10 transition-colors cursor-pointer ${selectedNode?.id === n.id ? "bg-primary/5" : ""}`}
                    onClick={() => handleNodeClick(n)}
                  >
                    <td className="px-3 py-2">
                      <div className={`w-2 h-2 rounded-full ${n.status === "online" ? "bg-green-500 animate-pulse" : n.status === "offline" ? "bg-red-500" : "bg-gray-500"}`} />
                    </td>
                    <td className="px-3 py-2 text-xs font-semibold">{n.label}</td>
                    <td className="px-3 py-2 text-[11px] font-mono text-muted-foreground">{n.ip || "—"}</td>
                    <td className="px-3 py-2 text-[11px] capitalize text-muted-foreground">{n.role}</td>
                    <td className="px-3 py-2 text-[11px] text-muted-foreground">{n.model || "—"}</td>
                    <td className="px-3 py-2 text-[11px] font-mono">
                      <span className={n.cpu > 80 ? "text-red-400" : "text-foreground"}>{n.cpu != null ? `${n.cpu}%` : "—"}</span>
                    </td>
                    <td className="px-3 py-2 text-[11px] font-mono">
                      <span className={n.memory > 85 ? "text-red-400" : "text-foreground"}>{n.memory != null ? `${n.memory}%` : "—"}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
