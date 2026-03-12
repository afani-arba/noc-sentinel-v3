import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "@/lib/api";
import {
  ArrowLeft, Server, Wifi, WifiOff, RefreshCw, Cpu, HardDrive,
  Activity, TrendingDown, TrendingUp, Thermometer, Zap, Clock
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend
} from "recharts";

const ttStyle = {
  contentStyle: { backgroundColor: "#0f172a", borderColor: "#1e3a5f", borderRadius: "6px", fontSize: "11px" },
  labelStyle: { color: "#94a3b8" },
};

function MetricCard({ icon: Icon, label, value, unit, color, sub }) {
  return (
    <div className="bg-card border border-border rounded-sm p-3 sm:p-4">
      <div className="flex items-center gap-2 mb-2">
        <Icon className={`w-4 h-4 ${color}`} />
        <span className="text-xs text-muted-foreground uppercase tracking-wider">{label}</span>
      </div>
      <p className={`text-2xl sm:text-3xl font-bold font-['Rajdhani'] ${color}`}>
        {value ?? "—"}{unit && <span className="text-sm ml-1 font-normal">{unit}</span>}
      </p>
      {sub && <p className="text-[10px] text-muted-foreground mt-1">{sub}</p>}
    </div>
  );
}

function formatTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
  } catch { return ""; }
}

function formatBw(mbps) {
  if (!mbps && mbps !== 0) return "—";
  if (mbps >= 1000) return `${(mbps / 1000).toFixed(2)} Gbps`;
  if (mbps >= 1) return `${mbps.toFixed(1)} Mbps`;
  return `${(mbps * 1000).toFixed(0)} Kbps`;
}

export default function DeviceDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [device, setDevice] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [devRes, histRes] = await Promise.all([
        api.get(`/devices`),
        api.get(`/devices/${id}/traffic-history`, { params: { limit: 144 } }),
      ]);
      const dev = (devRes.data || []).find(d => d.id === id);
      setDevice(dev || null);
      const hist = histRes.data?.history || [];
      setHistory(hist.map(h => ({
        ...h,
        time: formatTime(h.timestamp),
      })));
    } catch (e) {
      console.error("Device detail fetch error:", e);
    }
    setLoading(false);
    setRefreshing(false);
  }, [id]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchData();
  };

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

  const isOnline = device.status === "online";
  const latestBw = history.length > 0 ? history[history.length - 1] : null;

  return (
    <div className="space-y-4 pb-16">
      {/* Header */}
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

      {/* Metric Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <MetricCard icon={Cpu} label="CPU" value={device.cpu_load ?? 0} unit="%" color={device.cpu_load > 80 ? "text-red-500" : device.cpu_load > 60 ? "text-yellow-500" : "text-green-500"} sub={`Threshold: 80%`} />
        <MetricCard icon={HardDrive} label="Memory" value={device.memory_usage ?? 0} unit="%" color={device.memory_usage > 85 ? "text-red-500" : device.memory_usage > 70 ? "text-yellow-500" : "text-blue-400"} sub={`Threshold: 85%`} />
        <MetricCard icon={Activity} label="Ping" value={device.ping_ms ?? 0} unit="ms" color={device.ping_ms > 100 ? "text-yellow-500" : "text-cyan-400"} sub={`Jitter monitoring`} />
        <MetricCard icon={TrendingDown} label="Download" value={latestBw ? formatBw(latestBw.download_mbps) : "—"} unit="" color="text-blue-400" sub="Current" />
        <MetricCard icon={TrendingUp} label="Upload" value={latestBw ? formatBw(latestBw.upload_mbps) : "—"} unit="" color="text-green-400" sub="Current" />
        <MetricCard icon={Clock} label="Uptime" value={device.uptime || "—"} unit="" color="text-purple-400" sub={device.identity || ""} />
      </div>

      {/* Bandwidth History Chart */}
      <div className="bg-card border border-border rounded-sm p-4">
        <h2 className="text-sm font-semibold font-['Rajdhani'] tracking-tight mb-1 flex items-center gap-2">
          <Activity className="w-4 h-4 text-blue-400" /> Bandwidth History
          <span className="text-xs text-muted-foreground font-normal ml-1">(last {history.length} samples)</span>
        </h2>
        {history.length === 0 ? (
          <div className="h-48 flex items-center justify-center text-muted-foreground text-sm">
            <p>Tidak ada data historis. Data akan tersedia setelah beberapa siklus polling.</p>
          </div>
        ) : (
          <div className="h-48 sm:h-60">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={history} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="gDl" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="gUl" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="time" tick={{ fontSize: 9, fill: "#64748b" }} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 9, fill: "#64748b" }} tickFormatter={v => `${v}M`} />
                <Tooltip {...ttStyle} formatter={(v, n) => [`${v} Mbps`, n === "download_mbps" ? "Download" : "Upload"]} />
                <Legend wrapperStyle={{ fontSize: "10px" }} formatter={v => v === "download_mbps" ? "Download" : "Upload"} />
                <Area type="monotone" dataKey="download_mbps" stroke="#3b82f6" fill="url(#gDl)" strokeWidth={2} dot={false} />
                <Area type="monotone" dataKey="upload_mbps" stroke="#22c55e" fill="url(#gUl)" strokeWidth={2} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* CPU + Memory History Chart */}
      <div className="bg-card border border-border rounded-sm p-4">
        <h2 className="text-sm font-semibold font-['Rajdhani'] tracking-tight mb-1 flex items-center gap-2">
          <Cpu className="w-4 h-4 text-yellow-400" /> CPU & Memory History
        </h2>
        {history.length === 0 ? (
          <div className="h-48 flex items-center justify-center text-muted-foreground text-sm">
            <p>Tidak ada data historis.</p>
          </div>
        ) : (
          <div className="h-48 sm:h-60">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={history} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="time" tick={{ fontSize: 9, fill: "#64748b" }} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 9, fill: "#64748b" }} tickFormatter={v => `${v}%`} domain={[0, 100]} />
                <Tooltip {...ttStyle} formatter={(v, n) => [`${v}%`, n === "cpu" ? "CPU" : "Memory"]} />
                <Legend wrapperStyle={{ fontSize: "10px" }} formatter={v => v === "cpu" ? "CPU" : "Memory"} />
                <Line type="monotone" dataKey="cpu" stroke="#f59e0b" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="memory" stroke="#a855f7" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Device Info */}
      <div className="bg-card border border-border rounded-sm p-4">
        <h2 className="text-sm font-semibold font-['Rajdhani'] tracking-tight mb-3 flex items-center gap-2">
          <Server className="w-4 h-4 text-primary" /> Device Info
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-2 text-xs">
          {[
            ["IP Address", device.ip_address],
            ["Identity", device.identity || device.sys_name || "—"],
            ["Model", device.model || "—"],
            ["RouterOS", device.ros_version ? `v${device.ros_version}` : "—"],
            ["Serial", device.serial || "—"],
            ["Last Poll", device.last_poll ? new Date(device.last_poll).toLocaleString("id-ID") : "—"],
            device.cpu_temp && ["CPU Temp", `${device.cpu_temp}°C`],
            device.voltage && ["Voltage", `${device.voltage}V`],
          ].filter(Boolean).map(([k, v]) => (
            <div key={k} className="flex flex-col gap-0.5">
              <span className="text-muted-foreground">{k}</span>
              <span className="font-mono font-medium">{v}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
