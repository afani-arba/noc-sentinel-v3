import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "@/lib/api";
import {
  ArrowLeft, Server, Wifi, WifiOff, RefreshCw, Cpu,
  Activity, Clock, Network, BarChart2, Heart
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend, ComposedChart, Brush
} from "recharts";

/* ── Tooltip shared style ─────────────────────────────────────────── */
const ttStyle = {
  contentStyle: {
    backgroundColor: "#0c1526", borderColor: "#1e3a5f", borderRadius: "6px",
    fontSize: "11px", fontFamily: "'JetBrains Mono', monospace",
    boxShadow: "0 4px 24px rgba(0,0,0,0.6)"
  },
  labelStyle: { color: "#94a3b8", marginBottom: "4px" },
  itemStyle: { padding: "1px 0" },
};

/* ── Brush shared style ───────────────────────────────────────────── */
const brushStyle = {
  stroke: "#334155",
  fill: "#0f172a",
  travellerWidth: 6,
};

const RANGE_OPTIONS = [
  { label: "1J", value: "1h" },
  { label: "12J", value: "12h" },
  { label: "24J", value: "24h" },
];

function formatTime(iso) {
  if (!iso) return "";
  try { return new Date(iso).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }); }
  catch { return ""; }
}

function formatBw(mbps) {
  if (mbps == null) return "—";
  if (mbps >= 1000) return `${(mbps / 1000).toFixed(2)} Gbps`;
  if (mbps >= 1) return `${mbps.toFixed(2)} Mbps`;
  return `${(mbps * 1000).toFixed(0)} Kbps`;
}

function formatBwTooltip(v) {
  if (v == null) return "—";
  const n = Number(v);
  if (n >= 1000) return `${(n / 1000).toFixed(2)} Gbps`;
  if (n >= 1) return `${n.toFixed(2)} Mbps`;
  return `${(n * 1000).toFixed(0)} Kbps`;
}

/* ── Chart card wrapper ───────────────────────────────────────────── */
function ChartCard({ title, icon: Icon, iconColor, children, height = 260 }) {
  return (
    <div className="bg-card border border-border rounded-sm overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border/60 bg-black/20">
        <Icon className={`w-3.5 h-3.5 ${iconColor}`} />
        <span className="text-xs font-semibold uppercase tracking-wider font-['Rajdhani']">{title}</span>
        <span className="ml-auto text-[10px] text-muted-foreground opacity-60">scroll / drag to zoom</span>
      </div>
      <div style={{ height }} className="p-2 sm:p-3">{children}</div>
    </div>
  );
}

/* ── Compact metric chip ──────────────────────────────────────────── */
function MetricChip({ label, value, color }) {
  return (
    <div className="px-2.5 py-1.5 rounded-sm bg-card border border-border flex flex-col gap-0.5 min-w-[70px]">
      <span className="text-[9px] text-muted-foreground uppercase tracking-wider">{label}</span>
      <span className={`text-sm font-bold font-mono ${color}`}>{value}</span>
    </div>
  );
}

/* ── Empty state ──────────────────────────────────────────────────── */
function NoData() {
  return (
    <div className="h-full flex flex-col items-center justify-center gap-2 text-muted-foreground">
      <BarChart2 className="w-8 h-8 opacity-20" />
      <p className="text-xs">Belum ada data historis</p>
      <p className="text-[10px] opacity-60">Data akan muncul setelah beberapa siklus polling</p>
    </div>
  );
}

/* ── Custom Brush tick (lightweight label) ───────────────────────── */
const BrushTick = ({ x, y, payload }) => (
  <text x={x} y={y} dy={10} fill="#475569" fontSize={8} textAnchor="middle">
    {payload?.value}
  </text>
);

/* ═══════════════════════════════════════════════════════════════════ */
export default function DeviceDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [device, setDevice] = useState(null);
  const [history, setHistory] = useState([]);
  const [availableIfaces, setAvailableIfaces] = useState([]);
  const [ispIfaces, setIspIfaces] = useState([]);     // interface ISP dari comment detection
  const [selectedIface, setSelectedIface] = useState("all");
  const [range, setRange] = useState("24h");
  const [dateFilter, setDateFilter] = useState(""); // YYYY-MM-DD
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  /* ── Fetch data ─────────────────────────────────────────────────── */
  const fetchData = useCallback(async () => {
    try {
      const params = { device_id: id, interface: selectedIface, range };
      if (dateFilter) params.date = dateFilter;

      const [devRes, histRes, ifaceRes] = await Promise.all([
        api.get(`/devices`),
        api.get(`/dashboard/traffic-history`, { params }),
        api.get(`/dashboard/interfaces`, { params: { device_id: id } }),
      ]);
      const dev = (devRes.data || []).find(d => d.id === id);
      setDevice(dev || null);

      // Interface list dari /dashboard/interfaces
      const ifData = ifaceRes.data || {};
      const ifaces = ifData.interfaces || [];
      const ispList = ifData.isp_interfaces || [];
      if (ifaces.length > 0) {
        setAvailableIfaces(ifaces);
      }
      setIspIfaces(ispList);

      // Traffic history dari /dashboard/traffic-history
      const hist = Array.isArray(histRes.data) ? histRes.data : [];

      // Normalise field names
      setHistory(hist.map(h => ({
        ...h,
        time: dateFilter ? (h.date_label || h.time) : h.time,
        download_mbps: h.download_mbps ?? h.download ?? 0,
        upload_mbps:   h.upload_mbps  ?? h.upload  ?? 0,
        cpu:    h.cpu    ?? h.cpu_load      ?? 0,
        memory: h.memory ?? h.memory_percent ?? 0,
        ping:   h.ping   ?? h.ping_ms        ?? 0,
        jitter: h.jitter ?? h.jitter_ms      ?? 0,
      })));
    } catch (e) {
      console.error("Device detail fetch error:", e);
    }
    setLoading(false);
    setRefreshing(false);
  }, [id, selectedIface, range, dateFilter]);


  useEffect(() => { fetchData(); }, [fetchData]);

  const handleRefresh = () => { setRefreshing(true); fetchData(); };

  /* ── Computed ─────────────────────────────────────────────────── */
  const latestH = history.length > 0 ? history[history.length - 1] : null;
  const isOnline = device?.status === "online";

  // Brush default start index: show last 60 points (30 min equiv) on initial load
  const brushStartIdx = Math.max(0, history.length - 60);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <RefreshCw className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!device) {
    return (
      <div className="space-y-4 pb-16">
        <Button variant="ghost" size="sm" onClick={() => navigate("/devices")} className="gap-2">
          <ArrowLeft className="w-4 h-4" /> Back to Devices
        </Button>
        <div className="text-center py-20 text-muted-foreground">Device not found</div>
      </div>
    );
  }

  return (
    <div className="space-y-4 pb-16">

      {/* ── Header ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={() => navigate("/devices")} className="h-8 w-8 rounded-sm">
            <ArrowLeft className="w-4 h-4" />
          </Button>
          <div className={`w-9 h-9 rounded-sm flex items-center justify-center ${isOnline ? "bg-green-500/10" : "bg-red-500/10"}`}>
            {isOnline ? <Wifi className="w-5 h-5 text-green-500" /> : <WifiOff className="w-5 h-5 text-red-500" />}
          </div>
          <div>
            <h1 className="text-xl sm:text-2xl font-bold font-['Rajdhani'] tracking-tight">{device.name}</h1>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-mono text-muted-foreground">{device.ip_address}</span>
              {device.model && <span className="text-xs text-muted-foreground">· {device.model}</span>}
              {device.ros_version && <span className="text-xs text-muted-foreground">· v{device.ros_version}</span>}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-sm text-xs font-bold border ${isOnline ? "bg-green-500/10 text-green-500 border-green-500/20" : "bg-red-500/10 text-red-500 border-red-500/20"}`}>
            {isOnline && <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />}
            {(device.status || "unknown").toUpperCase()}
          </span>
          <Button variant="outline" size="icon" onClick={handleRefresh} disabled={refreshing} className="h-8 w-8 rounded-sm">
            <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      {/* ── Live Metric Chips ── */}
      <div className="flex flex-wrap gap-2">
        <MetricChip label="CPU" value={`${device.cpu_load ?? "—"}%`} color={device.cpu_load > 80 ? "text-red-400" : device.cpu_load > 60 ? "text-yellow-400" : "text-green-400"} />
        <MetricChip label="Memory" value={`${device.memory_usage ?? "—"}%`} color={device.memory_usage > 85 ? "text-red-400" : device.memory_usage > 70 ? "text-yellow-400" : "text-blue-400"} />
        <MetricChip label="Ping" value={device.ping_ms != null ? `${device.ping_ms} ms` : "—"} color={device.ping_ms > 100 ? "text-yellow-400" : "text-cyan-400"} />
        <MetricChip label="Download" value={latestH ? formatBw(latestH.download_mbps) : "—"} color="text-blue-400" />
        <MetricChip label="Upload" value={latestH ? formatBw(latestH.upload_mbps) : "—"} color="text-emerald-400" />
        <MetricChip label="Uptime" value={device.uptime || "—"} color="text-purple-400" />
        {device.cpu_temp > 0 && <MetricChip label="CPU Temp" value={`${device.cpu_temp}°C`} color={device.cpu_temp > 70 ? "text-red-400" : "text-orange-400"} />}
      </div>

      {/* ── Controls: Interface + Range + Date ── */}
      <div className="flex flex-wrap items-center gap-2 p-3 bg-card border border-border rounded-sm">
        {/* Interface selector */}
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <Network className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Interface</span>
        </div>
        <div className="flex flex-wrap gap-1">
          {(availableIfaces.length > 0 ? availableIfaces : ["all"]).map((iface) => {
            const isISP = ispIfaces.includes(iface);
            return (
              <button
                key={iface}
                onClick={() => setSelectedIface(iface)}
                className={`px-2.5 py-1 rounded-sm text-[10px] font-mono font-semibold border transition-all flex items-center gap-1 ${
                  selectedIface === iface
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-transparent text-muted-foreground border-border hover:border-primary/50 hover:text-foreground"
                }`}
              >
                {iface === "all" ? "All" : iface}
                {isISP && (
                  <span className="text-[8px] px-1 py-0.5 rounded bg-amber-500/20 text-amber-400 border border-amber-500/30 font-bold">
                    ISP
                  </span>
                )}
              </button>
            );
          })}
        </div>
        {ispIfaces.length > 0 && (
          <span className="text-[9px] text-amber-400/70 ml-1">
            📡 {ispIfaces.length} ISP interface terdeteksi
          </span>
        )}


        <div className="w-px h-5 bg-border hidden sm:block" />

        {/* Time range */}
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <Clock className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Range</span>
        </div>
        <div className="flex gap-1">
          {RANGE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => { setRange(opt.value); setDateFilter(""); }}
              className={`px-2.5 py-1 rounded-sm text-[10px] font-bold border transition-all ${
                range === opt.value && !dateFilter
                  ? "bg-blue-600 text-white border-blue-600"
                  : "bg-transparent text-muted-foreground border-border hover:border-blue-500/50 hover:text-foreground"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>

        <div className="w-px h-5 bg-border hidden sm:block" />

        {/* Date picker */}
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-muted-foreground uppercase tracking-wider flex-shrink-0">Tanggal</span>
          <input
            type="date"
            value={dateFilter}
            max={new Date().toISOString().slice(0, 10)}
            onChange={(e) => { setDateFilter(e.target.value); if (e.target.value) setRange(""); }}
            className="h-7 px-2 text-[10px] font-mono bg-background border border-border rounded-sm text-foreground focus:outline-none focus:border-blue-500 w-32"
          />
          {dateFilter && (
            <button
              onClick={() => { setDateFilter(""); setRange("24h"); }}
              className="text-[10px] text-muted-foreground hover:text-red-400 transition-colors"
            >✕</button>
          )}
        </div>

        <div className="ml-auto text-[10px] text-muted-foreground font-mono">
          {history.length} sampel · drag grafik untuk zoom
        </div>
      </div>

      {/* ── Bandwidth Chart ── */}
      <ChartCard title="Bandwidth History" icon={Activity} iconColor="text-blue-400" height={280}>
        {history.length === 0 ? <NoData /> : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={history} margin={{ top: 8, right: 8, left: -4, bottom: 28 }}>
              <defs>
                <linearGradient id="gDl2" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#eab308" stopOpacity={0.5} />
                  <stop offset="95%" stopColor="#eab308" stopOpacity={0.05} />
                </linearGradient>
                <linearGradient id="gUl2" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#22c55e" stopOpacity={0.5} />
                  <stop offset="95%" stopColor="#22c55e" stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
              <XAxis dataKey="time" tick={{ fontSize: 9, fill: "#64748b" }} interval="preserveStartEnd" minTickGap={40} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 9, fill: "#64748b" }} tickFormatter={v => v >= 1000 ? `${(v/1000).toFixed(1)} Gbps` : v >= 1 ? `${v.toFixed(0)} Mbps` : `${(v*1000).toFixed(0)} Kbps`} width={50} tickLine={false} axisLine={false} />
              <Tooltip {...ttStyle} formatter={(v, n) => [formatBwTooltip(v), n === "download_mbps" ? "Download" : "Upload"]} />
              <Legend wrapperStyle={{ fontSize: "10px", paddingTop: "6px" }} formatter={v => v === "download_mbps" ? "Download" : "Upload"} />
              <Area type="linear" dataKey="download_mbps" stroke="#eab308" strokeWidth={1.5} fill="url(#gDl2)" dot={false} activeDot={{ r: 4 }} name="download_mbps" />
              <Area type="linear" dataKey="upload_mbps" stroke="#22c55e" strokeWidth={1.5} fill="url(#gUl2)" dot={false} activeDot={{ r: 4 }} name="upload_mbps" />
              <Brush
                dataKey="time"
                height={18}
                startIndex={brushStartIdx}
                {...brushStyle}
                tick={<BrushTick />}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </ChartCard>

      {/* ── CPU & Memory Chart ── */}
      <ChartCard title="CPU & Memory" icon={Cpu} iconColor="text-yellow-400" height={240}>
        {history.length === 0 ? <NoData /> : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={history} margin={{ top: 8, right: 8, left: -10, bottom: 28 }}>
              <CartesianGrid strokeDasharray="2 4" stroke="rgba(255,255,255,0.04)" />
              <XAxis dataKey="time" tick={{ fontSize: 9, fill: "#475569" }} interval="preserveStartEnd" minTickGap={40} />
              <YAxis tick={{ fontSize: 9, fill: "#475569" }} tickFormatter={v => `${v}%`} domain={[0, 100]} width={34} />
              <Tooltip {...ttStyle} formatter={(v, n) => [`${v?.toFixed?.(1) ?? v}%`, n === "cpu" ? "🔧 CPU" : "💾 Memory"]} />
              <Legend wrapperStyle={{ fontSize: "10px", paddingTop: "2px" }} formatter={v => v === "cpu" ? "CPU" : "Memory"} />
              <Line type="monotone" dataKey="cpu" stroke="#f59e0b" strokeWidth={1.5} dot={false} activeDot={{ r: 3 }} />
              <Line type="monotone" dataKey="memory" stroke="#a855f7" strokeWidth={1.5} dot={false} activeDot={{ r: 3 }} />
              <Brush
                dataKey="time"
                height={18}
                startIndex={brushStartIdx}
                {...brushStyle}
                tick={<BrushTick />}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </ChartCard>

      {/* ── Ping & Jitter Chart ── */}
      <ChartCard title="Ping & Jitter" icon={Heart} iconColor="text-rose-400" height={240}>
        {history.length === 0 ? <NoData /> : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={history} margin={{ top: 8, right: 8, left: -10, bottom: 28 }}>
              <defs>
                <linearGradient id="gJitter" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.25} />
                  <stop offset="95%" stopColor="#f43f5e" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="2 4" stroke="rgba(255,255,255,0.04)" />
              <XAxis dataKey="time" tick={{ fontSize: 9, fill: "#475569" }} interval="preserveStartEnd" minTickGap={40} />
              <YAxis tick={{ fontSize: 9, fill: "#475569" }} tickFormatter={v => `${v}ms`} width={40} />
              <Tooltip
                {...ttStyle}
                formatter={(v, n) => [
                  `${v?.toFixed?.(1) ?? v} ms`,
                  n === "ping" ? "📡 Ping" : "〰 Jitter"
                ]}
              />
              <Legend wrapperStyle={{ fontSize: "10px", paddingTop: "2px" }} formatter={v => v === "ping" ? "Ping (ms)" : "Jitter (ms)"} />
              <Area type="monotone" dataKey="jitter" stroke="#f43f5e" strokeWidth={1} fill="url(#gJitter)" dot={false} activeDot={{ r: 3 }} />
              <Line type="monotone" dataKey="ping" stroke="#06b6d4" strokeWidth={2} dot={false} activeDot={{ r: 4, fill: "#06b6d4" }} />
              <Brush
                dataKey="time"
                height={18}
                startIndex={brushStartIdx}
                {...brushStyle}
                tick={<BrushTick />}
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </ChartCard>

      {/* ── Device Info ── */}
      <div className="bg-card border border-border rounded-sm overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border/60 bg-black/20">
          <Server className="w-3.5 h-3.5 text-primary" />
          <span className="text-xs font-semibold uppercase tracking-wider font-['Rajdhani']">Device Info</span>
        </div>
        <div className="p-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-x-8 gap-y-3 text-xs">
          {[
            ["IP Address", device.ip_address],
            ["Identity", device.identity || device.sys_name || "—"],
            ["Model", device.model || "—"],
            ["RouterOS", device.ros_version ? `v${device.ros_version}` : "—"],
            ["Serial", device.serial || "—"],
            ["Last Poll", device.last_poll ? new Date(device.last_poll).toLocaleString("id-ID") : "—"],
            device.cpu_temp && ["CPU Temp", `${device.cpu_temp}°C`],
            device.voltage && ["Voltage", `${device.voltage}V`],
            device.uptime && ["Uptime", device.uptime],
          ].filter(Boolean).map(([k, v]) => (
            <div key={k} className="flex flex-col gap-0.5">
              <span className="text-muted-foreground text-[10px] uppercase tracking-wider">{k}</span>
              <span className="font-mono font-medium break-words">{v}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
