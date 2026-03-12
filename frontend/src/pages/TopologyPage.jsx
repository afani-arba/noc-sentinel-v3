/**
 * TopologyPage — Network Map visualisasi topologi jaringan
 * Menggunakan pure SVG + force-directed simulation (tanpa library tambahan)
 * Node: warna berdasarkan status online/offline
 * Edges: berdasarkan ARP neighbors dari backend
 */
import { useState, useEffect, useRef, useCallback } from "react";
import api from "@/lib/api";
import { toast } from "sonner";
import {
  RefreshCw, ZoomIn, ZoomOut, Maximize2, Router, Server as ServerIcon,
  Wifi, WifiOff, Cpu, MemoryStick, Clock, Network, ChevronRight,
  GitBranch, Layers, Radio
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

// ── Force simulation (D3-style, vanilla JS) ────────────────────────────────────

function createForceSimulation(nodes, edges, width, height) {
  const REPULSION = 2500;
  const ATTRACTION = 0.03;
  const DAMPING = 0.85;
  const CENTER_X = width / 2;
  const CENTER_Y = height / 2;

  // Clone nodes dengan posisi awal melingkar
  const simNodes = nodes.map((n, i) => {
    const angle = (i / nodes.length) * 2 * Math.PI;
    const radius = Math.min(width, height) * 0.3;
    return {
      ...n,
      x: CENTER_X + radius * Math.cos(angle),
      y: CENTER_Y + radius * Math.sin(angle),
      vx: 0,
      vy: 0,
    };
  });

  // Build edge map
  const edgeSet = edges.map(e => ({
    source: simNodes.findIndex(n => n.id === e.source),
    target: simNodes.findIndex(n => n.id === e.target),
  })).filter(e => e.source >= 0 && e.target >= 0);

  const tick = () => {
    // Repulsion (setiap node tolak menolak)
    for (let i = 0; i < simNodes.length; i++) {
      for (let j = i + 1; j < simNodes.length; j++) {
        const dx = simNodes[j].x - simNodes[i].x;
        const dy = simNodes[j].y - simNodes[i].y;
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const force = REPULSION / (dist * dist);
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        simNodes[i].vx -= fx;
        simNodes[i].vy -= fy;
        simNodes[j].vx += fx;
        simNodes[j].vy += fy;
      }
    }

    // Attraction along edges
    for (const e of edgeSet) {
      const a = simNodes[e.source];
      const b = simNodes[e.target];
      if (!a || !b) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
      const idealDist = 180;
      const force = (dist - idealDist) * ATTRACTION;
      a.vx += (dx / dist) * force;
      a.vy += (dy / dist) * force;
      b.vx -= (dx / dist) * force;
      b.vy -= (dy / dist) * force;
    }

    // Center gravity
    for (const n of simNodes) {
      if (n.fixed) continue;
      n.vx += (CENTER_X - n.x) * 0.002;
      n.vy += (CENTER_Y - n.y) * 0.002;
      n.vx *= DAMPING;
      n.vy *= DAMPING;
      n.x += n.vx;
      n.y += n.vy;
      // Bounds
      n.x = Math.max(60, Math.min(width - 60, n.x));
      n.y = Math.max(60, Math.min(height - 60, n.y));
    }
  };

  return { nodes: simNodes, edgeSet, tick };
}

// ── Role icon ──────────────────────────────────────────────────────────────────

function RoleIcon({ role, size = 16 }) {
  const cls = `w-${size === 16 ? 4 : 3} h-${size === 16 ? 4 : 3}`;
  if (role === "router") return <Router className={cls} />;
  if (role === "switch") return <Layers className={cls} />;
  if (role === "ap") return <Radio className={cls} />;
  return <ServerIcon className={cls} />;
}

// ── Node Detail Panel ──────────────────────────────────────────────────────────

function NodeDetail({ node, onClose }) {
  if (!node) return null;

  const rows = [
    { label: "IP Address", value: node.ip || "—", mono: true },
    { label: "Model", value: node.model || "—" },
    { label: "Role", value: node.role || "device" },
    { label: "CPU", value: node.cpu != null ? `${node.cpu}%` : "—" },
    { label: "Memory", value: node.memory != null ? `${node.memory}%` : "—" },
    { label: "Uptime", value: node.uptime || "—" },
    { label: "Description", value: node.description || "—" },
  ];

  return (
    <div className="absolute right-3 top-3 w-56 bg-card/95 backdrop-blur-sm border border-border rounded-sm shadow-2xl z-20 text-xs">
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border">
        <div className="flex items-center gap-1.5">
          <div className={`w-2 h-2 rounded-full ${node.status === "online" ? "bg-green-500 animate-pulse" : "bg-red-500"}`} />
          <span className="font-semibold text-sm truncate max-w-[140px]">{node.label}</span>
        </div>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground ml-1">×</button>
      </div>
      <div className="p-3 space-y-1.5">
        {rows.map(r => (
          <div key={r.label} className="flex justify-between items-start gap-2">
            <span className="text-muted-foreground flex-shrink-0">{r.label}</span>
            <span className={`text-right ${r.mono ? "font-mono" : ""} truncate max-w-[110px]`} title={r.value}>{r.value}</span>
          </div>
        ))}
      </div>
      <div className="px-3 pb-3">
        <Badge variant="outline" className={`text-[10px] rounded-sm ${node.status === "online" ? "border-green-500/40 text-green-400" : "border-red-500/40 text-red-400"}`}>
          {node.status === "online" ? <><Wifi className="w-2.5 h-2.5 mr-1" />Online</> : <><WifiOff className="w-2.5 h-2.5 mr-1" />Offline</>}
        </Badge>
      </div>
    </div>
  );
}

// ── Canvas Topology ─────────────────────────────────────────────────────────────

function TopologyCanvas({ nodes, edges, onNodeClick, selectedNodeId }) {
  const svgRef = useRef(null);
  const containerRef = useRef(null);

  const [simNodes, setSimNodes] = useState([]);
  const [simEdges, setSimEdges] = useState([]);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(null);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });
  const simRef = useRef(null);
  const animRef = useRef(null);
  const [ticking, setTicking] = useState(true);
  const W = 900, H = 550;

  useEffect(() => {
    if (!nodes.length) return;
    const sim = createForceSimulation(nodes, edges, W, H);
    simRef.current = sim;
    setSimNodes([...sim.nodes]);
    setSimEdges(sim.edgeSet);

    let frame = 0;
    const animate = () => {
      if (frame < 150) {
        sim.tick();
        setSimNodes([...sim.nodes]);
        frame++;
        animRef.current = requestAnimationFrame(animate);
      } else {
        setTicking(false);
      }
    };
    animRef.current = requestAnimationFrame(animate);

    return () => cancelAnimationFrame(animRef.current);
  }, [nodes, edges]);

  const handleFitView = () => {
    if (!simNodes.length) return;
    const xs = simNodes.map(n => n.x);
    const ys = simNodes.map(n => n.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const padW = (W - (maxX - minX)) / 2;
    const padH = (H - (maxY - minY)) / 2;
    setPan({ x: padW - minX, y: padH - minY });
    setZoom(1);
  };

  const handleNodeMouseDown = (e, idx) => {
    e.stopPropagation();
    const n = simNodes[idx];
    setDragging(idx);
    setDragOffset({
      x: e.clientX / zoom - n.x,
      y: e.clientY / zoom - n.y,
    });
    if (simRef.current) simRef.current.nodes[idx].fixed = true;
  };

  const handleMouseMove = (e) => {
    if (dragging !== null) {
      const newX = e.clientX / zoom - dragOffset.x;
      const newY = e.clientY / zoom - dragOffset.y;
      setSimNodes(prev => {
        const updated = [...prev];
        updated[dragging] = { ...updated[dragging], x: newX, y: newY };
        if (simRef.current) {
          simRef.current.nodes[dragging].x = newX;
          simRef.current.nodes[dragging].y = newY;
        }
        return updated;
      });
    } else if (isPanning) {
      const dx = e.clientX - panStart.x;
      const dy = e.clientY - panStart.y;
      setPan(prev => ({ x: prev.x + dx / zoom, y: prev.y + dy / zoom }));
      setPanStart({ x: e.clientX, y: e.clientY });
    }
  };

  const handleMouseUp = (e) => {
    if (dragging !== null) {
      if (simRef.current) simRef.current.nodes[dragging].fixed = false;
      setDragging(null);
    }
    setIsPanning(false);
  };

  const handleSvgMouseDown = (e) => {
    if (e.target === svgRef.current || e.target.tagName === "line" || e.target.tagName === "svg") {
      setIsPanning(true);
      setPanStart({ x: e.clientX, y: e.clientY });
    }
  };

  const handleWheel = (e) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    setZoom(z => Math.max(0.3, Math.min(3, z * delta)));
  };

  const nodeRadius = 28;

  return (
    <div
      ref={containerRef}
      className="relative w-full bg-card/50 rounded-sm border border-border overflow-hidden select-none"
      style={{ height: 550 }}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      onWheel={handleWheel}
    >
      {/* Zoom controls */}
      <div className="absolute left-3 bottom-3 flex flex-col gap-1 z-10">
        <button onClick={() => setZoom(z => Math.min(3, z * 1.2))} className="w-7 h-7 bg-card border border-border rounded-sm flex items-center justify-center hover:bg-secondary/30 transition-colors text-xs font-bold">+</button>
        <button onClick={() => setZoom(z => Math.max(0.3, z * 0.8))} className="w-7 h-7 bg-card border border-border rounded-sm flex items-center justify-center hover:bg-secondary/30 transition-colors text-xs font-bold">−</button>
        <button onClick={handleFitView} className="w-7 h-7 bg-card border border-border rounded-sm flex items-center justify-center hover:bg-secondary/30 transition-colors" title="Fit View">
          <Maximize2 className="w-3 h-3" />
        </button>
      </div>

      {/* Ticking indicator */}
      {ticking && (
        <div className="absolute left-3 top-3 text-[10px] text-muted-foreground flex items-center gap-1 z-10">
          <RefreshCw className="w-2.5 h-2.5 animate-spin" /> Layouting...
        </div>
      )}

      <svg
        ref={svgRef}
        width="100%"
        height="100%"
        viewBox={`${-pan.x * zoom} ${-pan.y * zoom} ${W} ${H}`}
        style={{ cursor: isPanning ? "grabbing" : "grab" }}
        onMouseDown={handleSvgMouseDown}
        preserveAspectRatio="xMidYMid meet"
      >
        <defs>
          <filter id="glow-green">
            <feGaussianBlur stdDeviation="3" result="coloredBlur" />
            <feMerge><feMergeNode in="coloredBlur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id="glow-red">
            <feGaussianBlur stdDeviation="2" result="coloredBlur" />
            <feMerge><feMergeNode in="coloredBlur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id="node-shadow">
            <feDropShadow dx="0" dy="2" stdDeviation="4" floodColor="rgba(0,0,0,0.5)" />
          </filter>
        </defs>

        {/* Edges */}
        <g>
          {simEdges.map((e, i) => {
            const a = simNodes[e.source];
            const b = simNodes[e.target];
            if (!a || !b) return null;
            return (
              <line
                key={i}
                x1={a.x} y1={a.y}
                x2={b.x} y2={b.y}
                stroke="rgba(100,116,139,0.4)"
                strokeWidth={1.5}
                strokeDasharray="4 4"
              />
            );
          })}
        </g>

        {/* Nodes */}
        <g>
          {simNodes.map((n, idx) => {
            const isOnline = n.status === "online";
            const isSelected = n.id === selectedNodeId;
            const fill = isOnline ? "#052e16" : "#1f1315";
            const stroke = isOnline ? "#22c55e" : "#ef4444";
            const glowFilter = isOnline ? "url(#glow-green)" : "url(#glow-red)";

            return (
              <g
                key={n.id}
                transform={`translate(${n.x},${n.y})`}
                style={{ cursor: "pointer" }}
                onMouseDown={(e) => handleNodeMouseDown(e, idx)}
                onClick={() => onNodeClick(n)}
              >
                {/* Selection ring */}
                {isSelected && (
                  <circle r={nodeRadius + 6} fill="none" stroke="#60a5fa" strokeWidth={2} strokeDasharray="4 2" opacity={0.8} />
                )}

                {/* Pulse ring for online */}
                {isOnline && (
                  <circle r={nodeRadius + 3} fill="none" stroke="#22c55e" strokeWidth={1} opacity={0.3}>
                    <animate attributeName="r" from={nodeRadius} to={nodeRadius + 10} dur="2s" repeatCount="indefinite" />
                    <animate attributeName="opacity" from={0.4} to={0} dur="2s" repeatCount="indefinite" />
                  </circle>
                )}

                {/* Node circle */}
                <circle
                  r={nodeRadius}
                  fill={fill}
                  stroke={stroke}
                  strokeWidth={isSelected ? 2.5 : 1.5}
                  filter={glowFilter}
                />

                {/* CPU arc */}
                {isOnline && n.cpu > 0 && (
                  <circle
                    r={nodeRadius - 4}
                    fill="none"
                    stroke={n.cpu > 80 ? "#ef4444" : "#06b6d4"}
                    strokeWidth={3}
                    strokeDasharray={`${(n.cpu / 100) * (2 * Math.PI * (nodeRadius - 4))} ${2 * Math.PI * (nodeRadius - 4)}`}
                    strokeDashoffset={2 * Math.PI * (nodeRadius - 4) * 0.25}
                    opacity={0.6}
                  />
                )}

                {/* Node label */}
                <text
                  textAnchor="middle"
                  dy={nodeRadius + 14}
                  fontSize={10}
                  fill="#e2e8f0"
                  fontFamily="monospace"
                >
                  {n.label.length > 14 ? n.label.substring(0, 13) + "…" : n.label}
                </text>
                <text
                  textAnchor="middle"
                  dy={nodeRadius + 24}
                  fontSize={8}
                  fill="#64748b"
                  fontFamily="monospace"
                >
                  {n.ip}
                </text>

                {/* Status dot */}
                <circle cx={nodeRadius - 6} cy={-(nodeRadius - 6)} r={5} fill={stroke} />
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────────

export default function TopologyPage() {
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectedNode, setSelectedNode] = useState(null);
  const [filter, setFilter] = useState("all"); // all, online, offline

  const fetchTopology = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get("/topology");
      setNodes(r.data.nodes || []);
      setEdges(r.data.edges || []);
      setStats(r.data.stats || null);
    } catch (e) {
      toast.error("Gagal memuat data topology");
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchTopology(); }, [fetchTopology]);

  // Filter nodes
  const filteredNodes = nodes.filter(n => {
    if (filter === "all") return true;
    return n.status === filter;
  });

  const filteredEdges = edges.filter(e =>
    filteredNodes.some(n => n.id === e.source) &&
    filteredNodes.some(n => n.id === e.target)
  );

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
            Visualisasi topologi jaringan — {stats ? `${stats.total} device, ${stats.online} online, ${stats.offline} offline` : "Memuat..."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Filter */}
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

      {/* Stats Cards */}
      {stats && (
        <div className="flex gap-3 flex-wrap">
          {[
            { label: "Total Device", value: stats.total, color: "text-foreground" },
            { label: "Online", value: stats.online, color: "text-green-400" },
            { label: "Offline", value: stats.offline, color: "text-red-400" },
            { label: "Links Terdeteksi", value: edges.length, color: "text-cyan-400" },
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
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded-full bg-green-500 shadow shadow-green-500/50" />
          <span>Online</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded-full bg-red-500" />
          <span>Offline</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="border border-slate-500 border-dashed w-6 h-0" />
          <span>Link (ARP)</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded-full bg-cyan-500/40 border border-cyan-400" />
          <span>Arc = CPU usage</span>
        </div>
        <span className="text-[10px]">• Drag node untuk pindah • Scroll untuk zoom • Klik node untuk detail</span>
      </div>

      {/* Canvas */}
      <div className="relative">
        {loading && nodes.length === 0 ? (
          <div className="bg-card border border-border rounded-sm h-[550px] flex items-center justify-center">
            <div className="text-center">
              <GitBranch className="w-10 h-10 text-muted-foreground/30 mx-auto mb-3 animate-pulse" />
              <p className="text-muted-foreground text-sm">Memuat topology...</p>
            </div>
          </div>
        ) : filteredNodes.length === 0 ? (
          <div className="bg-card border border-border rounded-sm h-[550px] flex items-center justify-center">
            <div className="text-center">
              <Network className="w-10 h-10 text-muted-foreground/30 mx-auto mb-3" />
              <p className="text-muted-foreground text-sm">Tidak ada device ditemukan</p>
              <p className="text-[11px] text-muted-foreground mt-1">Tambah device di menu Devices terlebih dahulu</p>
            </div>
          </div>
        ) : (
          <>
            <TopologyCanvas
              nodes={filteredNodes}
              edges={filteredEdges}
              onNodeClick={n => setSelectedNode(prev => prev?.id === n.id ? null : n)}
              selectedNodeId={selectedNode?.id}
            />
            <NodeDetail node={selectedNode} onClose={() => setSelectedNode(null)} />
          </>
        )}
      </div>

      {/* Device List */}
      {nodes.length > 0 && (
        <div className="bg-card border border-border rounded-sm">
          <div className="px-4 py-3 border-b border-border">
            <p className="text-xs font-semibold">Daftar Device ({filteredNodes.length})</p>
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
                    onClick={() => setSelectedNode(prev => prev?.id === n.id ? null : n)}
                  >
                    <td className="px-3 py-2">
                      <div className={`w-2 h-2 rounded-full ${n.status === "online" ? "bg-green-500 animate-pulse" : "bg-red-500"}`} />
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
