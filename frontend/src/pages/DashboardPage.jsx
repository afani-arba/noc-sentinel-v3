import { useState, useEffect } from "react";
import api from "@/lib/api";
import {
  Users, Wifi, Server, ArrowDown, ArrowUp, Cpu, HardDrive, Thermometer, Activity,
  AlertTriangle, AlertCircle, Info, CheckCircle2
} from "lucide-react";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from "recharts";

const CHART_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899"];

const formatBytes = (bytes) => {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
};

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
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const res = await api.get("/dashboard/stats");
        setStats(res.data);
      } catch (err) {
        console.error("Failed to fetch dashboard stats", err);
      }
      setLoading(false);
    };
    fetchStats();
    const interval = setInterval(fetchStats, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64" data-testid="dashboard-loading">
        <div className="text-muted-foreground text-sm">Loading dashboard...</div>
      </div>
    );
  }

  if (!stats) return null;

  const pieData = [
    { name: "PPPoE Active", value: stats.pppoe.active },
    { name: "Hotspot Active", value: stats.hotspot.active },
    { name: "PPPoE Inactive", value: stats.pppoe.total - stats.pppoe.active },
    { name: "Hotspot Inactive", value: stats.hotspot.total - stats.hotspot.active },
  ];

  return (
    <div className="space-y-6" data-testid="dashboard-page">
      <div>
        <h1 className="text-3xl font-bold font-['Rajdhani'] tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground mt-1">Network overview and real-time monitoring</p>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          {
            label: "PPPoE Users",
            value: `${stats.pppoe.active}/${stats.pppoe.total}`,
            sub: "active / total",
            icon: Users,
            color: "text-blue-500",
            bg: "bg-blue-500/10",
          },
          {
            label: "Hotspot Users",
            value: `${stats.hotspot.active}/${stats.hotspot.total}`,
            sub: "active / total",
            icon: Wifi,
            color: "text-green-500",
            bg: "bg-green-500/10",
          },
          {
            label: "Devices",
            value: `${stats.devices.online}/${stats.devices.total}`,
            sub: "online / total",
            icon: Server,
            color: "text-purple-500",
            bg: "bg-purple-500/10",
          },
          {
            label: "Bandwidth",
            value: `${stats.total_bandwidth.download} Mbps`,
            sub: `Up: ${stats.total_bandwidth.upload} Mbps`,
            icon: Activity,
            color: "text-orange-500",
            bg: "bg-orange-500/10",
          },
        ].map((card, i) => (
          <div
            key={card.label}
            className="bg-card border border-border rounded-sm p-5 opacity-0 animate-slide-up transition-all hover:border-border/80"
            style={{ animationDelay: `${i * 0.05}s`, animationFillMode: 'forwards' }}
            data-testid={`stat-card-${card.label.toLowerCase().replace(/\s/g, '-')}`}
          >
            <div className="flex items-start justify-between">
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wider">{card.label}</p>
                <p className="text-2xl font-bold font-['Rajdhani'] mt-1">{card.value}</p>
                <p className="text-xs text-muted-foreground mt-0.5">{card.sub}</p>
              </div>
              <div className={`w-10 h-10 rounded-sm ${card.bg} flex items-center justify-center`}>
                <card.icon className={`w-5 h-5 ${card.color}`} />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Traffic Chart */}
        <div className="lg:col-span-2 bg-card border border-border rounded-sm p-5" data-testid="traffic-chart">
          <h3 className="text-lg font-semibold font-['Rajdhani'] mb-4">Traffic History (24h)</h3>
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

      {/* Bottom Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* System Health */}
        <div className="bg-card border border-border rounded-sm p-5" data-testid="system-health">
          <h3 className="text-lg font-semibold font-['Rajdhani'] mb-4">System Health</h3>
          <div className="space-y-4">
            {[
              { label: "CPU Usage", value: stats.system_health.cpu, icon: Cpu, color: stats.system_health.cpu > 80 ? "#ef4444" : stats.system_health.cpu > 60 ? "#f59e0b" : "#10b981" },
              { label: "Memory", value: stats.system_health.memory, icon: HardDrive, color: stats.system_health.memory > 80 ? "#ef4444" : stats.system_health.memory > 60 ? "#f59e0b" : "#10b981" },
              { label: "Disk", value: stats.system_health.disk, icon: HardDrive, color: stats.system_health.disk > 80 ? "#ef4444" : stats.system_health.disk > 60 ? "#f59e0b" : "#10b981" },
              { label: "Temperature", value: stats.system_health.temperature, icon: Thermometer, color: stats.system_health.temperature > 60 ? "#ef4444" : stats.system_health.temperature > 45 ? "#f59e0b" : "#10b981", unit: "°C" },
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
