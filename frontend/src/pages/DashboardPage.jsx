import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import {
  Server, ArrowDown, ArrowUp, Cpu, HardDrive, Activity, Monitor, Network,
  AlertTriangle, AlertCircle, Info, CheckCircle2, RefreshCw, Thermometer, Zap, Battery
} from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, Legend
} from "recharts";

const alertIcons = { warning: AlertTriangle, error: AlertCircle, info: Info, success: CheckCircle2 };
const alertColors = { warning: "text-yellow-500", error: "text-red-500", info: "text-blue-500", success: "text-green-500" };
const ttStyle = { contentStyle: { backgroundColor: "#121214", borderColor: "#27272a", borderRadius: "4px", color: "#fafafa", fontSize: "12px", fontFamily: "'JetBrains Mono', monospace" } };

export default function DashboardPage() {
  const [stats, setStats] = useState(null);
  const [devices, setDevices] = useState([]);
  const [selectedDevice, setSelectedDevice] = useState("all");
  const [interfaces, setInterfaces] = useState(["all"]);
  const [selectedInterface, setSelectedInterface] = useState("all");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/devices").then(r => {
      setDevices(r.data);
      // Set first device as default if available
      if (r.data.length > 0) {
        setSelectedDevice(r.data[0].id);
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (selectedDevice === "all") { setInterfaces(["all"]); setSelectedInterface("all"); return; }
    api.get("/dashboard/interfaces", { params: { device_id: selectedDevice } })
      .then(r => { setInterfaces(r.data); setSelectedInterface("all"); }).catch(() => {});
  }, [selectedDevice]);

  const fetchStats = useCallback(async () => {
    try {
      const params = {};
      if (selectedDevice !== "all") params.device_id = selectedDevice;
      if (selectedInterface !== "all") params.interface = selectedInterface;
      const r = await api.get("/dashboard/stats", { params });
      setStats(r.data);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [selectedDevice, selectedInterface]);

  useEffect(() => {
    fetchStats();
    const iv = setInterval(fetchStats, 30000);
    return () => clearInterval(iv);
  }, [fetchStats]);

  if (loading && !stats) return <div className="flex items-center justify-center h-64" data-testid="dashboard-loading"><span className="text-muted-foreground text-sm">Loading dashboard...</span></div>;
  if (!stats) return null;

  const td = stats.traffic_data || [];
  // Calculate averages only from non-zero values
  const pingValues = td.filter(d => d.ping > 0).map(d => d.ping);
  const jitterValues = td.filter(d => d.jitter > 0).map(d => d.jitter);
  const avgPing = pingValues.length ? Math.round(pingValues.reduce((s,v) => s+v, 0) / pingValues.length) : 0;
  const avgJitter = jitterValues.length ? (jitterValues.reduce((s,v) => s+v, 0) / jitterValues.length).toFixed(1) : "0";
  const sd = stats.selected_device;
  const noData = td.length === 0;

  return (
    <div className="space-y-4 pb-16" data-testid="dashboard-page">
      <div className="flex flex-col gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl md:text-3xl font-bold font-['Rajdhani'] tracking-tight">Dashboard</h1>
          <p className="text-xs sm:text-sm text-muted-foreground">Real-time network monitoring</p>
        </div>
        <div className="grid grid-cols-2 sm:flex sm:flex-row gap-2 sm:gap-3 sm:items-end">
          <div className="space-y-1">
            <label className="text-[10px] text-muted-foreground uppercase tracking-widest flex items-center gap-1"><Monitor className="w-3 h-3" /> Device</label>
            <Select value={selectedDevice} onValueChange={setSelectedDevice}>
              <SelectTrigger className="w-full sm:w-44 rounded-sm bg-card text-xs h-9" data-testid="dashboard-device-select"><SelectValue placeholder="All Devices" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all"><span className="flex items-center gap-2"><Server className="w-3 h-3 text-muted-foreground" /> All Devices</span></SelectItem>
                {devices.map(d => (
                  <SelectItem key={d.id} value={d.id}><span className="flex items-center gap-2"><div className={`w-1.5 h-1.5 rounded-full ${d.status==="online"?"bg-green-500":"bg-red-500"}`} /><span className="font-mono text-xs">{d.name}</span></span></SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <label className="text-[10px] text-muted-foreground uppercase tracking-widest flex items-center gap-1"><Network className="w-3 h-3" /> Interface</label>
            <Select value={selectedInterface} onValueChange={setSelectedInterface}>
              <SelectTrigger className="w-full sm:w-36 rounded-sm bg-card text-xs h-9" data-testid="dashboard-interface-select"><SelectValue /></SelectTrigger>
              <SelectContent>
                {interfaces.map(i => <SelectItem key={i} value={i}><span className="font-mono text-xs">{i==="all"?"All Interfaces":i}</span></SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <Button variant="outline" size="icon" className="h-9 w-9 rounded-sm col-span-2 sm:col-span-1 justify-self-end" onClick={fetchStats} data-testid="dashboard-refresh-btn"><RefreshCw className="w-4 h-4" /></Button>
        </div>
      </div>

      {sd && (
        <div className="flex flex-wrap items-center gap-2 sm:gap-4 px-3 py-2 bg-card border border-border rounded-sm text-[10px] sm:text-xs animate-fade-in" data-testid="device-info-bar">
          <div className={`w-2 h-2 rounded-full flex-shrink-0 ${sd.status==="online"?"bg-green-500 animate-pulse":"bg-red-500"}`} />
          <span className="font-semibold truncate max-w-[100px] sm:max-w-none">{sd.identity || sd.name}</span>
          <span className="text-muted-foreground font-mono hidden sm:inline">{sd.ip_address}</span>
          {sd.ros_version && <Badge variant="outline" className="rounded-sm text-[10px]">v{sd.ros_version}</Badge>}
          {sd.uptime && <span className="text-muted-foreground hidden sm:inline">Up: <span className="font-mono text-foreground">{sd.uptime}</span></span>}
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 gap-2 sm:gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {[
          { label: "Devices", value: `${stats.devices.online}/${stats.devices.total}`, sub: "online/total", icon: Server, color: "text-purple-500", bg: "bg-purple-500/10" },
          { label: "Download", value: `${stats.total_bandwidth.download}`, sub: "Mbps", icon: ArrowDown, color: "text-blue-500", bg: "bg-blue-500/10" },
          { label: "Upload", value: `${stats.total_bandwidth.upload}`, sub: "Mbps", icon: ArrowUp, color: "text-green-500", bg: "bg-green-500/10" },
          { label: "Avg Ping", value: `${avgPing}`, sub: "ms", icon: Activity, color: "text-cyan-500", bg: "bg-cyan-500/10" },
          { label: "Avg Jitter", value: avgJitter, sub: "ms", icon: Activity, color: "text-rose-500", bg: "bg-rose-500/10" },
        ].map((c,i) => (
          <div key={c.label} className="bg-card border border-border rounded-sm p-3 sm:p-4 opacity-0 animate-slide-up" style={{ animationDelay:`${i*0.04}s`, animationFillMode:'forwards' }} data-testid={`stat-card-${c.label.toLowerCase().replace(/\s/g,'-')}`}>
            <div className="flex items-start justify-between">
              <div><p className="text-[9px] sm:text-[10px] text-muted-foreground uppercase tracking-wider">{c.label}</p><p className="text-lg sm:text-xl font-bold font-['Rajdhani'] mt-0.5 sm:mt-1">{c.value} <span className="text-xs sm:text-sm font-normal text-muted-foreground">{c.sub}</span></p></div>
              <div className={`w-7 h-7 sm:w-8 sm:h-8 rounded-sm ${c.bg} flex items-center justify-center`}><c.icon className={`w-3.5 h-3.5 sm:w-4 sm:h-4 ${c.color}`} /></div>
            </div>
          </div>
        ))}
      </div>

      {noData && devices.length === 0 ? (
        <div className="bg-card border border-border rounded-sm p-12 text-center"><Server className="w-12 h-12 mx-auto mb-3 text-muted-foreground/30" /><p className="text-muted-foreground">No devices configured</p><p className="text-xs text-muted-foreground mt-1">Add a MikroTik device in the Devices page to start monitoring</p></div>
      ) : noData ? (
        <div className="bg-card border border-border rounded-sm p-12 text-center"><Activity className="w-12 h-12 mx-auto mb-3 text-muted-foreground/30" /><p className="text-muted-foreground">Waiting for data...</p><p className="text-xs text-muted-foreground mt-1">SNMP polling runs every 30 seconds. Traffic data will appear after 2 polling cycles.</p></div>
      ) : (
        <>
          {/* Traffic Chart */}
          <div className="bg-card border border-border rounded-sm p-3 sm:p-5" data-testid="traffic-chart">
            <h3 className="text-base sm:text-lg font-semibold font-['Rajdhani'] mb-3 sm:mb-4">Traffic History</h3>
            <div className="h-48 sm:h-64">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={td}>
                  <defs>
                    <linearGradient id="gDl" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3}/><stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/></linearGradient>
                    <linearGradient id="gUl" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#10b981" stopOpacity={0.3}/><stop offset="95%" stopColor="#10b981" stopOpacity={0}/></linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272a" /><XAxis dataKey="time" tick={{ fill:"#a1a1aa", fontSize:10 }} tickLine={false} axisLine={{ stroke:"#27272a" }} /><YAxis tick={{ fill:"#a1a1aa", fontSize:10 }} tickLine={false} axisLine={{ stroke:"#27272a" }} width={40} /><Tooltip {...ttStyle} />
                  <Area type="monotone" dataKey="download" stroke="#3b82f6" fill="url(#gDl)" strokeWidth={2} name="Download (Mbps)" />
                  <Area type="monotone" dataKey="upload" stroke="#10b981" fill="url(#gUl)" strokeWidth={2} name="Upload (Mbps)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div className="flex items-center gap-4 sm:gap-6 mt-2 sm:mt-3 text-[10px] sm:text-xs text-muted-foreground">
              <div className="flex items-center gap-1 sm:gap-2"><div className="w-3 h-[2px] bg-blue-500" /><ArrowDown className="w-3 h-3" /> Download</div>
              <div className="flex items-center gap-1 sm:gap-2"><div className="w-3 h-[2px] bg-green-500" /><ArrowUp className="w-3 h-3" /> Upload</div>
            </div>
          </div>

          {/* Ping & Jitter */}
          <div className="bg-card border border-border rounded-sm p-3 sm:p-5" data-testid="ping-jitter-chart">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-3 sm:mb-4 gap-2">
              <h3 className="text-base sm:text-lg font-semibold font-['Rajdhani']">Ping & Jitter</h3>
              <div className="flex items-center gap-2 sm:gap-3 text-[10px] sm:text-xs">
                <div className="flex items-center gap-1 sm:gap-2 px-2 py-1 rounded-sm bg-cyan-500/10 border border-cyan-500/20"><span className="text-cyan-400">Ping:</span><span className="font-mono text-cyan-300 font-semibold">{avgPing} ms</span></div>
                <div className="flex items-center gap-1 sm:gap-2 px-2 py-1 rounded-sm bg-rose-500/10 border border-rose-500/20"><span className="text-rose-400">Jitter:</span><span className="font-mono text-rose-300 font-semibold">{avgJitter} ms</span></div>
              </div>
            </div>
            {avgPing === 0 && avgJitter === "0" ? (
              <div className="h-48 flex items-center justify-center bg-secondary/20 rounded-sm border border-dashed border-border">
                <div className="text-center">
                  <Activity className="w-8 h-8 mx-auto mb-2 text-muted-foreground/30" />
                  <p className="text-sm text-muted-foreground">Ping data tidak tersedia</p>
                  <p className="text-xs text-muted-foreground/70 mt-1">Server monitoring tidak dapat menjangkau IP device via ICMP.<br/>Pastikan firewall MikroTik mengizinkan ICMP dari server monitoring.</p>
                </div>
              </div>
            ) : (
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={td}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#27272a" /><XAxis dataKey="time" tick={{ fill:"#a1a1aa", fontSize:11 }} tickLine={false} axisLine={{ stroke:"#27272a" }} /><YAxis tick={{ fill:"#a1a1aa", fontSize:11 }} tickLine={false} axisLine={{ stroke:"#27272a" }} domain={[0,'auto']} /><Tooltip {...ttStyle} />
                    <Legend iconType="line" wrapperStyle={{ fontSize:"11px", color:"#a1a1aa" }} />
                    <Line type="monotone" dataKey="ping" stroke="#06b6d4" strokeWidth={2} dot={false} name="Ping (ms)" />
                    <Line type="monotone" dataKey="jitter" stroke="#f43f5e" strokeWidth={2} dot={false} strokeDasharray="5 3" name="Jitter (ms)" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </>
      )}

      {/* Bottom Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-card border border-border rounded-sm p-5" data-testid="system-health">
          <h3 className="text-lg font-semibold font-['Rajdhani'] mb-4">System Health {sd && <span className="text-sm text-muted-foreground font-normal">- {sd.identity || sd.name}</span>}</h3>
          <div className="space-y-4">
            {/* CPU & Memory bars */}
            {[
              { label: "CPU Load", value: stats.system_health.cpu, icon: Cpu, unit: "%" },
              { label: "Memory", value: stats.system_health.memory, icon: HardDrive, unit: "%" },
            ].map(m => (
              <div key={m.label} className="flex items-center gap-3">
                <m.icon className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                <div className="flex-1">
                  <div className="flex items-center justify-between mb-1"><span className="text-xs text-muted-foreground">{m.label}</span><span className="text-xs font-mono" style={{ color: m.value>80?"#ef4444":m.value>60?"#f59e0b":"#10b981" }}>{m.value}{m.unit}</span></div>
                  <div className="w-full h-1.5 bg-secondary rounded-full overflow-hidden"><div className="h-full rounded-full transition-all duration-1000" style={{ width:`${m.value}%`, backgroundColor: m.value>80?"#ef4444":m.value>60?"#f59e0b":"#10b981" }} /></div>
                </div>
              </div>
            ))}
            
            {/* Temperature, Voltage, Power metrics */}
            <div className="grid grid-cols-2 gap-3 pt-2 border-t border-border/50">
              {stats.system_health.cpu_temp > 0 && (
                <div className="flex items-center gap-2 p-2 rounded-sm bg-secondary/30">
                  <Thermometer className="w-4 h-4 text-orange-500" />
                  <div>
                    <p className="text-[10px] text-muted-foreground">CPU Temp</p>
                    <p className="text-sm font-mono" style={{ color: stats.system_health.cpu_temp > 70 ? "#ef4444" : stats.system_health.cpu_temp > 50 ? "#f59e0b" : "#10b981" }}>{stats.system_health.cpu_temp}°C</p>
                  </div>
                </div>
              )}
              {stats.system_health.board_temp > 0 && (
                <div className="flex items-center gap-2 p-2 rounded-sm bg-secondary/30">
                  <Thermometer className="w-4 h-4 text-red-500" />
                  <div>
                    <p className="text-[10px] text-muted-foreground">Board Temp</p>
                    <p className="text-sm font-mono" style={{ color: stats.system_health.board_temp > 60 ? "#ef4444" : stats.system_health.board_temp > 45 ? "#f59e0b" : "#10b981" }}>{stats.system_health.board_temp}°C</p>
                  </div>
                </div>
              )}
              {stats.system_health.voltage > 0 && (
                <div className="flex items-center gap-2 p-2 rounded-sm bg-secondary/30">
                  <Zap className="w-4 h-4 text-yellow-500" />
                  <div>
                    <p className="text-[10px] text-muted-foreground">Voltage</p>
                    <p className="text-sm font-mono">{stats.system_health.voltage}V</p>
                  </div>
                </div>
              )}
              {stats.system_health.power > 0 && (
                <div className="flex items-center gap-2 p-2 rounded-sm bg-secondary/30">
                  <Battery className="w-4 h-4 text-green-500" />
                  <div>
                    <p className="text-[10px] text-muted-foreground">Power</p>
                    <p className="text-sm font-mono">{stats.system_health.power}W</p>
                  </div>
                </div>
              )}
            </div>
            
            {/* Show message if no extended metrics available */}
            {stats.system_health.cpu_temp === 0 && stats.system_health.board_temp === 0 && stats.system_health.voltage === 0 && stats.system_health.power === 0 && (
              <p className="text-xs text-muted-foreground/50 text-center pt-2">Extended metrics not available for this device</p>
            )}
          </div>
        </div>
        <div className="bg-card border border-border rounded-sm p-5" data-testid="recent-alerts">
          <h3 className="text-lg font-semibold font-['Rajdhani'] mb-4">Alerts</h3>
          <div className="space-y-3">
            {stats.alerts.map(a => { const Icon = alertIcons[a.type]||Info; return (
              <div key={a.id} className="flex items-start gap-3 p-2.5 rounded-sm bg-secondary/30 border border-border/50 hover:bg-secondary/50 transition-colors">
                <Icon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${alertColors[a.type]}`} />
                <div className="flex-1 min-w-0"><p className="text-sm text-foreground">{a.message}</p><p className="text-xs text-muted-foreground mt-0.5 font-mono">{a.time}</p></div>
              </div>
            );})}
          </div>
        </div>
      </div>
    </div>
  );
}
