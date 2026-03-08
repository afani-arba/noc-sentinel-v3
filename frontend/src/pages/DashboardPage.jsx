import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import {
  Users, Wifi, Server, ArrowDown, ArrowUp, Cpu, HardDrive, Thermometer, Activity,
  AlertTriangle, AlertCircle, Info, CheckCircle2, Monitor, Network
} from "lucide-react";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, LineChart, Line, Legend
} from "recharts";

const CHART_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899"];

const alertIcons = {
  warning: AlertTriangle,
  error: AlertCircle,
  info: Info,
  success: CheckCircle2,
};
const alertColors = {
  warning: "text-yellow-500",
  error: "text-red-500",
  info: "text-blue-500",
  success: "text-green-500",
};

const tooltipStyle = {
  contentStyle: {
    backgroundColor: "#121214",
    borderColor: "#27272a",
    borderRadius: "4px",
    color: "#fafafa",
    fontSize: "12px",
    fontFamily: "'JetBrains Mono', monospace",
  },
};

export default function DashboardPage() {
  const [stats, setStats] = useState(null);
  const [devices, setDevices] = useState([]);
  const [selectedDevice, setSelectedDevice] = useState("all");
  const [interfaces, setInterfaces] = useState(["all"]);
  const [selectedInterface, setSelectedInterface] = useState("all");
  const [loading, setLoading] = useState(true);

  // Fetch devices list once
  useEffect(() => {
    const fetchDevices = async () => {
      try {
        const res = await api.get("/devices");
        setDevices(res.data);
      } catch (err) {
        console.error("Failed to fetch devices", err);
      }
    };
    fetchDevices();
  }, []);

  // Fetch interfaces when device changes
  useEffect(() => {
    const fetchInterfaces = async () => {
      try {
        const params = {};
        if (selectedDevice !== "all") params.device_id = selectedDevice;
        const res = await api.get("/dashboard/interfaces", { params });
        setInterfaces(res.data);
        setSelectedInterface("all");
      } catch (err) {
        console.error("Failed to fetch interfaces", err);
      }
    };
    fetchInterfaces();
  }, [selectedDevice]);

  // Fetch stats when device or interface changes
  const fetchStats = useCallback(async () => {
    try {
      const params = {};
      if (selectedDevice !== "all") params.device_id = selectedDevice;
      if (selectedInterface !== "all") params.interface = selectedInterface;
      const res = await api.get("/dashboard/stats", { params });
      setStats(res.data);
    } catch (err) {
      console.error("Failed to fetch dashboard stats", err);
    }
    setLoading(false);
  }, [selectedDevice, selectedInterface]);

  useEffect(() => {
    setLoading(true);
    fetchStats();
    const interval = setInterval(fetchStats, 30000);
    return () => clearInterval(interval);
  }, [fetchStats]);

  if (loading && !stats) {
    return (
      <div className="flex items-center justify-center h-64" data-testid="dashboard-loading">
        <div className="text-muted-foreground text-sm">Loading dashboard...</div>
      </div>
    );
  }

  if (!stats) return null;

  const selectedDeviceData = devices.find((d) => d.id === selectedDevice);

  const pieData = [
    { name: "PPPoE Active", value: stats.pppoe.active },
    { name: "Hotspot Active", value: stats.hotspot.active },
    { name: "PPPoE Inactive", value: Math.max(0, stats.pppoe.total - stats.pppoe.active) },
    { name: "Hotspot Inactive", value: Math.max(0, stats.hotspot.total - stats.hotspot.active) },
  ];

  // Compute averages for ping/jitter
  const avgPing = stats.traffic_data.length
    ? Math.round(stats.traffic_data.reduce((s, d) => s + d.ping, 0) / stats.traffic_data.length)
    : 0;
  const avgJitter = stats.traffic_data.length
    ? (stats.traffic_data.reduce((s, d) => s + d.jitter, 0) / stats.traffic_data.length).toFixed(1)
    : 0;

  return (
    <div className="space-y-6" data-testid="dashboard-page">
      {/* Header with Device & Interface Selectors */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold font-['Rajdhani'] tracking-tight">Dashboard</h1>
          <p className="text-sm text-muted-foreground mt-1">Network overview and real-time monitoring</p>
        </div>
        <div className="flex flex-col sm:flex-row gap-3">
          {/* Device Selector */}
          <div className="space-y-1">
            <label className="text-[10px] text-muted-foreground uppercase tracking-widest flex items-center gap-1">
              <Monitor className="w-3 h-3" /> Device
            </label>
            <Select value={selectedDevice} onValueChange={setSelectedDevice}>
              <SelectTrigger className="w-52 rounded-sm bg-card text-xs h-9" data-testid="dashboard-device-select">
                <SelectValue placeholder="All Devices" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">
                  <span className="flex items-center gap-2">
                    <Server className="w-3 h-3 text-muted-foreground" /> All Devices
                  </span>
                </SelectItem>
                {devices.map((d) => (
                  <SelectItem key={d.id} value={d.id}>
                    <span className="flex items-center gap-2">
                      <div className={`w-1.5 h-1.5 rounded-full ${d.status === "online" ? "bg-green-500" : "bg-red-500"}`} />
                      <span className="font-mono text-xs">{d.name}</span>
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Interface Selector */}
          <div className="space-y-1">
            <label className="text-[10px] text-muted-foreground uppercase tracking-widest flex items-center gap-1">
              <Network className="w-3 h-3" /> Interface
            </label>
            <Select value={selectedInterface} onValueChange={setSelectedInterface}>
              <SelectTrigger className="w-44 rounded-sm bg-card text-xs h-9" data-testid="dashboard-interface-select">
                <SelectValue placeholder="All Interfaces" />
              </SelectTrigger>
              <SelectContent>
                {interfaces.map((iface) => (
                  <SelectItem key={iface} value={iface}>
                    <span className="font-mono text-xs">{iface === "all" ? "All Interfaces" : iface}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      {/* Active device info bar */}
      {selectedDevice !== "all" && selectedDeviceData && (
        <div className="flex items-center gap-4 px-4 py-2.5 bg-card border border-border rounded-sm text-xs animate-fade-in" data-testid="device-info-bar">
          <div className={`w-2 h-2 rounded-full ${selectedDeviceData.status === "online" ? "bg-green-500 animate-pulse" : "bg-red-500"}`} />
          <span className="font-semibold">{selectedDeviceData.name}</span>
          <span className="text-muted-foreground font-mono">{selectedDeviceData.ip_address}</span>
          <Badge variant="outline" className="rounded-sm text-[10px]">{selectedDeviceData.model}</Badge>
          <span className="text-muted-foreground">Uptime: <span className="font-mono text-foreground">{selectedDeviceData.uptime}</span></span>
          {selectedInterface !== "all" && (
            <span className="text-muted-foreground">Interface: <span className="font-mono text-primary">{selectedInterface}</span></span>
          )}
        </div>
      )}

      {/* Stats Row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {[
          { label: "PPPoE Users", value: `${stats.pppoe.active}/${stats.pppoe.total}`, sub: "active/total", icon: Users, color: "text-blue-500", bg: "bg-blue-500/10" },
          { label: "Hotspot Users", value: `${stats.hotspot.active}/${stats.hotspot.total}`, sub: "active/total", icon: Wifi, color: "text-green-500", bg: "bg-green-500/10" },
          { label: "Devices", value: `${stats.devices.online}/${stats.devices.total}`, sub: "online/total", icon: Server, color: "text-purple-500", bg: "bg-purple-500/10" },
          { label: "Bandwidth", value: `${stats.total_bandwidth.download}`, sub: `Up: ${stats.total_bandwidth.upload} Mbps`, icon: Activity, color: "text-orange-500", bg: "bg-orange-500/10", suffix: " Mbps" },
          { label: "Avg Ping", value: `${avgPing}`, sub: "latency", icon: Activity, color: "text-cyan-500", bg: "bg-cyan-500/10", suffix: " ms" },
          { label: "Avg Jitter", value: `${avgJitter}`, sub: "variation", icon: Activity, color: "text-rose-500", bg: "bg-rose-500/10", suffix: " ms" },
        ].map((card, i) => (
          <div
            key={card.label}
            className="bg-card border border-border rounded-sm p-4 opacity-0 animate-slide-up transition-all hover:border-border/80"
            style={{ animationDelay: `${i * 0.04}s`, animationFillMode: 'forwards' }}
            data-testid={`stat-card-${card.label.toLowerCase().replace(/\s/g, '-')}`}
          >
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[10px] text-muted-foreground uppercase tracking-wider">{card.label}</p>
                <p className="text-xl font-bold font-['Rajdhani'] mt-1">{card.value}{card.suffix || ""}</p>
                <p className="text-[10px] text-muted-foreground mt-0.5">{card.sub}</p>
              </div>
              <div className={`w-8 h-8 rounded-sm ${card.bg} flex items-center justify-center`}>
                <card.icon className={`w-4 h-4 ${card.color}`} />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Traffic Chart */}
        <div className="lg:col-span-2 bg-card border border-border rounded-sm p-5" data-testid="traffic-chart">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold font-['Rajdhani']">
              Traffic History (24h)
              {selectedInterface !== "all" && (
                <span className="text-sm text-primary ml-2 font-mono font-normal">/ {selectedInterface}</span>
              )}
            </h3>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={stats.traffic_data}>
                <defs>
                  <linearGradient id="colorDown" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="colorUp" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                <XAxis dataKey="time" tick={{ fill: "#a1a1aa", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "#27272a" }} />
                <YAxis tick={{ fill: "#a1a1aa", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "#27272a" }} />
                <Tooltip {...tooltipStyle} />
                <Area type="monotone" dataKey="download" stroke="#3b82f6" fill="url(#colorDown)" strokeWidth={2} name="Download (Mbps)" />
                <Area type="monotone" dataKey="upload" stroke="#10b981" fill="url(#colorUp)" strokeWidth={2} name="Upload (Mbps)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="flex items-center gap-6 mt-3 text-xs text-muted-foreground">
            <div className="flex items-center gap-2">
              <div className="w-3 h-[2px] bg-blue-500" />
              <ArrowDown className="w-3 h-3" /> Download
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-[2px] bg-green-500" />
              <ArrowUp className="w-3 h-3" /> Upload
            </div>
          </div>
        </div>

        {/* Active Users Pie */}
        <div className="bg-card border border-border rounded-sm p-5" data-testid="users-pie-chart">
          <h3 className="text-lg font-semibold font-['Rajdhani'] mb-4">Active Users</h3>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={45}
                  outerRadius={70}
                  paddingAngle={3}
                  dataKey="value"
                >
                  {pieData.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip {...tooltipStyle} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="grid grid-cols-2 gap-2 mt-2">
            {pieData.map((item, i) => (
              <div key={item.name} className="flex items-center gap-2 text-xs">
                <div className="w-2 h-2 rounded-full" style={{ backgroundColor: CHART_COLORS[i] }} />
                <span className="text-muted-foreground truncate">{item.name}: <span className="text-foreground font-mono">{item.value}</span></span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Ping & Jitter Chart */}
      <div className="bg-card border border-border rounded-sm p-5" data-testid="ping-jitter-chart">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold font-['Rajdhani']">
            Ping & Jitter (24h)
            {selectedInterface !== "all" && (
              <span className="text-sm text-primary ml-2 font-mono font-normal">/ {selectedInterface}</span>
            )}
          </h3>
          <div className="flex items-center gap-4 text-xs">
            <div className="flex items-center gap-2 px-2 py-1 rounded-sm bg-cyan-500/10 border border-cyan-500/20">
              <span className="text-cyan-400">Avg Ping:</span>
              <span className="font-mono text-cyan-300 font-semibold">{avgPing} ms</span>
            </div>
            <div className="flex items-center gap-2 px-2 py-1 rounded-sm bg-rose-500/10 border border-rose-500/20">
              <span className="text-rose-400">Avg Jitter:</span>
              <span className="font-mono text-rose-300 font-semibold">{avgJitter} ms</span>
            </div>
          </div>
        </div>
        <div className="h-52">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={stats.traffic_data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
              <XAxis dataKey="time" tick={{ fill: "#a1a1aa", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "#27272a" }} />
              <YAxis
                tick={{ fill: "#a1a1aa", fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: "#27272a" }}
                domain={[0, 'auto']}
                label={{ value: 'ms', position: 'insideTopLeft', fill: '#a1a1aa', fontSize: 10, dx: -5 }}
              />
              <Tooltip {...tooltipStyle} />
              <Legend
                iconType="line"
                wrapperStyle={{ fontSize: "11px", color: "#a1a1aa", fontFamily: "'JetBrains Mono', monospace" }}
              />
              <Line
                type="monotone"
                dataKey="ping"
                stroke="#06b6d4"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, fill: "#06b6d4" }}
                name="Ping (ms)"
              />
              <Line
                type="monotone"
                dataKey="jitter"
                stroke="#f43f5e"
                strokeWidth={2}
                dot={false}
                strokeDasharray="5 3"
                activeDot={{ r: 4, fill: "#f43f5e" }}
                name="Jitter (ms)"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Bottom Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* System Health */}
        <div className="bg-card border border-border rounded-sm p-5" data-testid="system-health">
          <h3 className="text-lg font-semibold font-['Rajdhani'] mb-4">
            System Health
            {selectedDevice !== "all" && selectedDeviceData && (
              <span className="text-sm text-muted-foreground ml-2 font-normal">- {selectedDeviceData.name}</span>
            )}
          </h3>
          <div className="space-y-4">
            {[
              { label: "CPU Usage", value: stats.system_health.cpu, icon: Cpu, color: stats.system_health.cpu > 80 ? "#ef4444" : stats.system_health.cpu > 60 ? "#f59e0b" : "#10b981" },
              { label: "Memory", value: stats.system_health.memory, icon: HardDrive, color: stats.system_health.memory > 80 ? "#ef4444" : stats.system_health.memory > 60 ? "#f59e0b" : "#10b981" },
              { label: "Disk", value: stats.system_health.disk, icon: HardDrive, color: stats.system_health.disk > 80 ? "#ef4444" : stats.system_health.disk > 60 ? "#f59e0b" : "#10b981" },
              { label: "Temperature", value: stats.system_health.temperature, icon: Thermometer, color: stats.system_health.temperature > 60 ? "#ef4444" : stats.system_health.temperature > 45 ? "#f59e0b" : "#10b981", unit: "\u00b0C" },
            ].map((metric) => (
              <div key={metric.label} className="flex items-center gap-3">
                <metric.icon className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                <div className="flex-1">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-muted-foreground">{metric.label}</span>
                    <span className="text-xs font-mono" style={{ color: metric.color }}>
                      {metric.value}{metric.unit || "%"}
                    </span>
                  </div>
                  <div className="w-full h-1.5 bg-secondary rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-1000"
                      style={{ width: `${metric.value}%`, backgroundColor: metric.color }}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Alerts */}
        <div className="bg-card border border-border rounded-sm p-5" data-testid="recent-alerts">
          <h3 className="text-lg font-semibold font-['Rajdhani'] mb-4">Recent Alerts</h3>
          <div className="space-y-3">
            {stats.alerts.map((alert) => {
              const Icon = alertIcons[alert.type] || Info;
              return (
                <div
                  key={alert.id}
                  className="flex items-start gap-3 p-2.5 rounded-sm bg-secondary/30 border border-border/50 transition-colors hover:bg-secondary/50"
                >
                  <Icon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${alertColors[alert.type]}`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-foreground">{alert.message}</p>
                    <p className="text-xs text-muted-foreground mt-0.5 font-mono">{alert.time}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
