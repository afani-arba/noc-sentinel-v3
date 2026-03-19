import { useState, useEffect, useCallback, useRef } from "react";
import api from "@/lib/api";
import {
  PieChart, Pie, Cell, Tooltip as ReTooltip, ResponsiveContainer,
  LineChart, Line, XAxis, YAxis, CartesianGrid, Legend,
} from "recharts";
import {
  Radar, RefreshCw, ChevronDown, Globe, Activity, Wifi,
  TrendingUp, HardDrive, Radio, Server, AlertCircle, Users,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import PeeringPlatformModal from "@/components/PeeringPlatformModal";
import Highcharts from 'highcharts';
import HighchartsReact from 'highcharts-react-official';
import highcharts3d from 'highcharts/highcharts-3d';

if (typeof Highcharts === 'object') {
  highcharts3d(Highcharts);
}

// ── Format helpers ─────────────────────────────────────────────────────────────
function fmtBytes(b) {
  if (!b) return "0 B";
  if (b >= 1e9) return `${(b / 1e9).toFixed(2)} GB`;
  if (b >= 1e6) return `${(b / 1e6).toFixed(2)} MB`;
  if (b >= 1e3) return `${(b / 1e3).toFixed(1)} KB`;
  return `${b} B`;
}
function fmtNum(n) {
  if (!n) return "0";
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return String(n);
}

// ── Range Options ──────────────────────────────────────────────────────────────
const RANGES = [
  { value: "1h", label: "1 Jam" },
  { value: "6h", label: "6 Jam" },
  { value: "12h", label: "12 Jam" },
  { value: "24h", label: "24 Jam" },
  { value: "7d", label: "7 Hari" },
  { value: "30d", label: "30 Hari" },
];

// Highcharts natively handles 3D Pie Labels.

// ── Stat Card ──────────────────────────────────────────────────────────────────
function StatCard({ icon: Icon, label, value, sub, color = "text-primary" }) {
  return (
    <div className="bg-card border border-border rounded-sm px-4 py-3">
      <div className="flex items-center gap-2 mb-1">
        <Icon className={`w-3.5 h-3.5 ${color}`} />
        <span className="text-[10px] text-muted-foreground uppercase tracking-wide">{label}</span>
      </div>
      <p className={`text-xl font-bold font-mono ${color}`}>{value}</p>
      {sub && <p className="text-[10px] text-muted-foreground mt-0.5">{sub}</p>}
    </div>
  );
}

// ── BGP State Badge ────────────────────────────────────────────────────────────
function BgpBadge({ state }) {
  const map = {
    ESTABLISHED: "text-green-400 border-green-400/30",
    ACTIVE:      "text-yellow-400 border-yellow-400/30",
    IDLE:        "text-red-400 border-red-400/30",
    CONNECT:     "text-blue-400 border-blue-400/30",
  };
  return (
    <Badge variant="outline" className={`text-[9px] rounded-sm px-1.5 ${map[state] || "text-muted-foreground border-border"}`}>
      {state || "UNKNOWN"}
    </Badge>
  );
}

// ── No Data Placeholder ────────────────────────────────────────────────────────
function NoData({ message = "Belum ada data" }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-muted-foreground gap-2">
      <Radar className="w-10 h-10 opacity-20 animate-pulse" />
      <p className="text-sm">{message}</p>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN PAGE
// ═══════════════════════════════════════════════════════════════════════════════
const POLL_INTERVAL = 30_000;

export default function PeeringEyePage() {
  const [devices, setDevices]       = useState([]);
  const [selectedDev, setSelectedDev] = useState(null); // null = all
  const [range, setRange]           = useState("24h");
  const [summary, setSummary]       = useState(null);
  const [stats, setStats]           = useState(null);
  const [timeline, setTimeline]     = useState([]);
  const [topDomains, setTopDomains] = useState([]);
  const [topClients, setTopClients] = useState([]);
  const [bgpStatus, setBgpStatus]   = useState(null);
  const [loading, setLoading]       = useState(true);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [domainPlatform, setDomainPlatform] = useState("all");

  const [showDevDropdown, setShowDevDropdown] = useState(false);
  const [showRangeDropdown, setShowRangeDropdown] = useState(false);
  const [showDomainDropdown, setShowDomainDropdown] = useState(false);
  const [showPlatformsModal, setShowPlatformsModal] = useState(false);

  const intervalRef = useRef(null);

  // ── Fetch all data ───────────────────────────────────────────────────────────
  const fetchAll = useCallback(async (showLoader = false) => {
    if (showLoader) setLoading(true);
    const devId = selectedDev?.device_id || "";
    try {
      const [sumRes, statsRes, tlRes, domainsRes, clientsRes, bgpRes] = await Promise.allSettled([
        api.get(`/peering-eye/summary?device_id=${devId}&range=${range}`),
        api.get(`/peering-eye/stats?device_id=${devId}&range=${range}`),
        api.get(`/peering-eye/timeline?device_id=${devId}&range=${range}`),
        api.get(`/peering-eye/top-domains?device_id=${devId}&range=${range}&limit=20&platform=${domainPlatform}`),
        api.get(`/peering-eye/top-clients?device_id=${devId}&range=${range}&limit=20&platform=${domainPlatform}`),
        api.get("/peering-eye/bgp/status"),
      ]);

      if (sumRes.status    === "fulfilled") setSummary(sumRes.value.data);
      if (statsRes.status  === "fulfilled") setStats(statsRes.value.data);
      if (tlRes.status     === "fulfilled") setTimeline(tlRes.value.data.data || []);
      if (domainsRes.status === "fulfilled") setTopDomains(domainsRes.value.data.domains || []);
      if (clientsRes.status === "fulfilled") setTopClients(clientsRes.value.data.clients || []);
      if (bgpRes.status    === "fulfilled") setBgpStatus(bgpRes.value.data);
      setLastUpdate(new Date());
    } catch (e) {
      // silent
    } finally {
      setLoading(false);
    }
  }, [selectedDev, range, domainPlatform]);

  const handleBlock = async (targetType, target) => {
    if (!selectedDev?.device_id) {
      alert("Silakan pilih perangkat/router spesifik (bukan 'Semua Router') terlebih dahulu sebelum melakukan aksi blokir.");
      return;
    }
    const msg = targetType === "domain" 
      ? `Anda yakin ingin memblokir akses ke domain ${target}?` 
      : `Anda yakin ingin memblokir/mengisolir klien ${target}?`;
    
    if (!window.confirm(msg)) return;
    
    try {
      const res = await api.post("/peering-eye/block", {
        device_id: selectedDev.device_id,
        target_type: targetType,
        target: target
      });
      alert(res.data?.message || "Berhasil diblokir!");
    } catch (e) {
      alert("Gagal memblokir: " + (e.response?.data?.detail || e.message));
    }
  };

  // ── Load devices ─────────────────────────────────────────────────────────────
  useEffect(() => {
    api.get("/peering-eye/devices")
      .then(r => setDevices(r.data || []))
      .catch(() => {});
  }, []);

  // ── Poll ──────────────────────────────────────────────────────────────────────
  useEffect(() => {
    fetchAll(true);
    clearInterval(intervalRef.current);
    intervalRef.current = setInterval(() => fetchAll(false), POLL_INTERVAL);
    return () => clearInterval(intervalRef.current);
  }, [fetchAll]);

  // ── Build line chart series keys ─────────────────────────────────────────────
  const platformsInTimeline = timeline.length > 0
    ? Object.keys(timeline[0]).filter(k => k !== "time" && k !== "Others").slice(0, 10)
    : [];

  // ── Flatten timeline for recharts ────────────────────────────────────────────
  const chartData = timeline.map(row => {
    const flat = { time: row.time };
    platformsInTimeline.forEach(p => {
      flat[p] = (row[p]?.hits || 0);
    });
    return flat;
  });

  const rawPlatforms = stats?.platforms || [];
  const sortedRaw = [...rawPlatforms].sort((a, b) => b.bytes - a.bytes);
  
  const NEON_COLORS = [
    "#7cb5ec", "#00FFC4", "#90ed7d", "#f7a35c", "#8085e9", 
    "#f15c80", "#e4d354", "#2b908f", "#f45b5b", "#91e8e1"
  ];
  const platforms = sortedRaw.map((p, i) => ({
    ...p,
    color: i < 10 ? NEON_COLORS[i] : p.color
  }));
  const bgpPeers  = bgpStatus?.peers || [];

  return (
    <div className="space-y-4 pb-16">
      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold font-['Rajdhani'] tracking-tight flex items-center gap-2">
            <Radar className="w-6 h-6 text-cyan-400" />
            Sentinel Peering-Eye
            <span className="text-[9px] font-mono bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 px-1.5 py-0.5 rounded-sm">
              BETA
            </span>
          </h1>
          <p className="text-xs text-muted-foreground">
            Analitik traffic platform · Update setiap 30 detik
            {lastUpdate && (
              <span className="ml-2 opacity-60">
                · terakhir {lastUpdate.toLocaleTimeString("id-ID")}
              </span>
            )}
          </p>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-2">
          {/* Range Picker */}
          <div className="relative">
            <button
              onClick={() => { setShowRangeDropdown(v => !v); setShowDevDropdown(false); }}
              className="flex items-center gap-1.5 px-3 py-2 bg-card border border-border rounded-sm text-xs hover:bg-secondary/20 transition-colors"
            >
              {RANGES.find(r => r.value === range)?.label}
              <ChevronDown className="w-3 h-3 text-muted-foreground" />
            </button>
            {showRangeDropdown && (
              <div className="absolute right-0 top-full mt-1 z-50 bg-card border border-border rounded-sm shadow-xl min-w-[100px]">
                {RANGES.map(r => (
                  <button
                    key={r.value}
                    onClick={() => { setRange(r.value); setShowRangeDropdown(false); }}
                    className={`w-full text-left px-3 py-2 text-xs hover:bg-secondary/30 ${range === r.value ? "text-primary" : ""}`}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Device Picker */}
          <div className="relative">
            <button
              onClick={() => { setShowDevDropdown(v => !v); setShowRangeDropdown(false); }}
              className="flex items-center gap-2 px-3 py-2 bg-card border border-border rounded-sm text-xs hover:bg-secondary/20 transition-colors min-w-[160px] justify-between"
            >
              <div className="flex items-center gap-1.5 truncate">
                <Server className="w-3 h-3 text-muted-foreground flex-shrink-0" />
                <span className="truncate">{selectedDev ? selectedDev.device_name : "Semua Router"}</span>
              </div>
              <ChevronDown className="w-3 h-3 text-muted-foreground flex-shrink-0" />
            </button>
            {showDevDropdown && (
              <div className="absolute right-0 top-full mt-1 z-50 bg-card border border-border rounded-sm shadow-xl min-w-[220px] max-h-64 overflow-y-auto">
                <button
                  onClick={() => { setSelectedDev(null); setShowDevDropdown(false); }}
                  className={`w-full text-left px-3 py-2.5 text-xs hover:bg-secondary/30 flex items-center gap-2 ${!selectedDev ? "text-primary bg-primary/10" : ""}`}
                >
                  <Globe className="w-3 h-3" /> Semua Router
                </button>
                {devices.map(d => (
                  <button
                    key={d.device_id}
                    onClick={() => { setSelectedDev(d); setShowDevDropdown(false); }}
                    className={`w-full text-left px-3 py-2.5 text-xs hover:bg-secondary/30 flex items-center gap-2 justify-between ${selectedDev?.device_id === d.device_id ? "text-primary bg-primary/10" : ""}`}
                  >
                    <span className="truncate">{d.device_name}</span>
                    <span className="text-[9px] text-muted-foreground font-mono shrink-0">{fmtNum(d.total_hits)} hits</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <button
            onClick={() => fetchAll(true)}
            disabled={loading}
            className="p-2 bg-card border border-border rounded-sm hover:bg-secondary/20 transition-colors"
          >
            <RefreshCw className={`w-4 h-4 text-muted-foreground ${loading ? "animate-spin" : ""}`} />
          </button>
          
          <button
            onClick={() => setShowPlatformsModal(true)}
            className="flex items-center gap-1.5 px-3 py-2 bg-primary/10 border border-primary/30 text-primary rounded-sm text-xs font-semibold hover:bg-primary/20 transition-colors ml-2"
          >
            <Server className="w-3.5 h-3.5" /> Kelola Platform
          </button>
        </div>
      </div>

      {/* No data state */}
      {!loading && !summary?.total_hits && (
        <div className="flex items-start gap-3 p-4 bg-yellow-500/10 border border-yellow-500/20 rounded-sm">
          <AlertCircle className="w-4 h-4 text-yellow-400 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-xs font-semibold text-yellow-300">Belum ada data Peering-Eye</p>
            <p className="text-[11px] text-yellow-300/70 mt-0.5">
              Pastikan <code className="bg-black/30 px-1 rounded">sentinel_eye.py</code> berjalan di Ubuntu VPS dan
              Mikrotik sudah dikonfigurasi mengirim DNS syslog ke port 5514 &amp; NetFlow ke port 2055.
            </p>
          </div>
        </div>
      )}

      {/* ── Stat Cards ──────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard icon={Activity}   label="Total DNS Hits"    value={fmtNum(summary?.total_hits || 0)}       color="text-cyan-400" />
        <StatCard icon={TrendingUp} label="Top Platform"      value={summary?.top_platform || "—"}           sub={summary?.top_platform_icon}  color="text-emerald-400" />
        <StatCard icon={Globe}      label="Unique Platform"   value={summary?.unique_platforms || 0}         color="text-purple-400" />
        <StatCard icon={HardDrive}  label="Est. Traffic"      value={summary?.total_bytes_fmt || "0 B"}      color="text-yellow-400" />
      </div>

      {/* ── Charts Row ──────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        {/* Donut Chart */}
        <div className="lg:col-span-2 bg-[#09090b] border border-[#27272a]/70 rounded-xl p-4 relative overflow-hidden shadow-2xl">
          <div className="absolute top-0 right-0 w-48 h-48 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />
          <p className="text-xs font-bold mb-1 text-white z-10 relative">Distribusi Platform</p>
          <p className="text-[10px] text-muted-foreground mb-3 z-10 relative">Berdasarkan Total Estimasi Traffic</p>
          {platforms.length === 0 ? (
            <NoData message="Belum ada data platform" />
          ) : (
            <div className="z-10 relative mt-2 w-full h-[260px]">
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none z-10" style={{ transform: 'translateY(-10px)' }}>
                 <p className="text-white text-[15px] font-[800] font-['Rajdhani'] drop-shadow-md tracking-wide">TRAFFIC</p>
                 <p className="text-white text-[15px] font-[800] font-['Rajdhani'] drop-shadow-md tracking-wide">SHARES</p>
              </div>
              <HighchartsReact
                highcharts={Highcharts}
                options={{
                  chart: {
                    type: 'pie',
                    backgroundColor: 'transparent',
                    options3d: { enabled: true, alpha: 45 },
                    height: 260,
                    margin: [0, 0, 0, 0]
                  },
                  title: { text: '' },
                  tooltip: {
                    backgroundColor: "rgba(9, 9, 11, 0.95)",
                    borderColor: "#27272a",
                    style: { color: '#fff', fontSize: '12px' },
                    pointFormatter: function() {
                      return `<b>${this.name}</b>: ${fmtBytes(this.y)}`;
                    }
                  },
                  plotOptions: {
                    pie: {
                      innerSize: '60%',
                      depth: 35,
                      dataLabels: {
                        enabled: true,
                        useHTML: true,
                        format: '<div style="color:{point.color}; text-align:center; font-family:\'Rajdhani\',sans-serif; font-weight:800; font-size:12px; text-shadow: 0px 0px 6px {point.color}; line-height: 1.1;">{point.name}<br/>{point.percentage:.0f}%</div>',
                        style: {
                           textOutline: 'none'
                        },
                        connectorWidth: 1.5,
                        connectorPadding: 5,
                        distance: 35
                      }
                    }
                  },
                  series: [{
                    name: 'Traffic',
                    data: platforms.filter(p => p.platform !== "Others").slice(0, 10).map(p => ({
                       name: p.platform,
                       y: p.bytes,
                       color: p.color
                    }))
                  }],
                  credits: { enabled: false }
                }}
              />
            </div>
          )}
        </div>

        {/* Area Chart Timeline */}
        <div className="lg:col-span-3 bg-[#09090b] border border-[#27272a]/70 rounded-xl p-4 relative shadow-2xl">
          <div className="absolute top-0 left-0 w-64 h-64 bg-cyan-500/5 rounded-full blur-3xl pointer-events-none" />
          <p className="text-xs font-bold mb-1 text-white z-10 relative">Timeline Traffic</p>
          <p className="text-[10px] text-muted-foreground mb-3 z-10 relative">DNS hits per platform — {RANGES.find(r => r.value === range)?.label} terakhir</p>
          {chartData.length === 0 ? (
            <NoData message="Belum ada data timeline" />
          ) : (
            <ResponsiveContainer width="100%" height={260} className="z-10 relative">
              <LineChart data={chartData} margin={{ left: -10, right: 10, top: 15, bottom: 0 }}>
                <defs>
                  <filter id="neonLine" x="-50%" y="-50%" width="200%" height="200%">
                    <feGaussianBlur stdDeviation="2" result="blur" />
                    <feMerge>
                      <feMergeNode in="blur" />
                      <feMergeNode in="SourceGraphic" />
                    </feMerge>
                  </filter>
                </defs>
                <CartesianGrid strokeDasharray="5 5" stroke="#27272a" vertical={true} />
                <XAxis dataKey="time" tick={{ fill: "#a1a1aa", fontSize: 9 }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fill: "#a1a1aa", fontSize: 10, fontWeight: 500 }} tickLine={false} axisLine={false} width={65} tickFormatter={fmtBytes} />
                <ReTooltip
                  contentStyle={{ backgroundColor: "rgba(9, 9, 11, 0.95)", borderColor: "#27272a", borderRadius: "8px", fontSize: "12px", boxShadow: "0 0 20px rgba(0,0,0,0.8)", border: "1px solid rgba(255,255,255,0.1)" }}
                  formatter={(v, n) => [fmtBytes(v), n]}
                />
                <Legend iconSize={12} iconType="circle" wrapperStyle={{ fontSize: 11, paddingTop: 8, color: '#e4e4e7' }} />
                {platformsInTimeline.map((p, i) => {
                  const color = platforms.find(pl => pl.platform === p)?.color || "#64748b";
                  return (
                    <Line
                      key={p}
                      type="linear"
                      dataKey={p}
                      stroke={color}
                      strokeWidth={2.5}
                      dot={false}
                      filter="url(#neonLine)"
                      isAnimationActive={true}
                    />
                  );
                })}
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* ── Platform Table ──────────────────────────────────────────────────── */}
      <div className="bg-card border border-border rounded-sm p-4">
        <p className="text-xs font-semibold mb-1">Detail Platform Traffic</p>
        <p className="text-[10px] text-muted-foreground mb-3">Klasifikasi berdasarkan DNS syslog + NetFlow</p>
        {platforms.length === 0 ? (
          <NoData />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-border">
                  {["Platform", "DNS Hits", "Est. Traffic", "% Hits", "% Traffic", "Trend"].map(h => (
                    <th key={h} className="px-3 py-2 text-[10px] text-muted-foreground uppercase tracking-wider font-medium whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {platforms.map((p, i) => (
                  <tr key={p.platform} className="border-b border-border/20 hover:bg-secondary/10 transition-colors">
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: p.color }} />
                        <span className="text-base leading-none">{p.icon}</span>
                        <span className="text-xs font-semibold">{p.platform}</span>
                        {i === 0 && (
                          <Badge variant="outline" className="text-[8px] rounded-sm h-4 px-1 text-yellow-400 border-yellow-400/30 ml-1">TOP</Badge>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-xs font-mono text-cyan-300">{fmtNum(p.hits)}</td>
                    <td className="px-3 py-2.5 text-xs font-mono text-emerald-300">{p.bytes_fmt}</td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 bg-secondary rounded-full overflow-hidden">
                          <div className="h-full rounded-full" style={{ width: `${p.pct_hits}%`, backgroundColor: p.color }} />
                        </div>
                        <span className="text-[11px] font-mono text-muted-foreground">{p.pct_hits}%</span>
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 bg-secondary rounded-full overflow-hidden">
                          <div className="h-full rounded-full" style={{ width: `${p.pct_bytes}%`, backgroundColor: p.color }} />
                        </div>
                        <span className="text-[11px] font-mono text-muted-foreground">{p.pct_bytes}%</span>
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      <TrendingUp className="w-3 h-3 text-emerald-400" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Bottom Row: BGP Status + Top Domains + Top Clients ─────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* BGP Status Panel */}
        <div className="bg-card border border-border rounded-sm p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <p className="text-xs font-semibold flex items-center gap-1.5">
                <Radio className="w-3.5 h-3.5 text-purple-400" />
                BGP Peer Status
              </p>
              <p className="text-[10px] text-muted-foreground mt-0.5">
                {bgpStatus?.established || 0}/{bgpStatus?.total || 0} peers ESTABLISHED
              </p>
            </div>
            {bgpStatus?.updated_at && (
              <span className="text-[9px] text-muted-foreground font-mono">
                {new Date(bgpStatus.updated_at).toLocaleTimeString("id-ID")}
              </span>
            )}
          </div>

          {bgpPeers.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <Radio className="w-6 h-6 mx-auto mb-2 opacity-20" />
              <p className="text-xs">BGP belum terkonfigurasi</p>
              <p className="text-[10px] mt-1 opacity-60">Install sentinel_bgp.py di Ubuntu VPS</p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {bgpPeers.map((peer, i) => (
                <div key={i} className="flex items-center justify-between p-2 rounded-sm bg-secondary/20 hover:bg-secondary/30 transition-colors">
                  <div className="flex items-center gap-2 min-w-0">
                    <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${peer.state === "ESTABLISHED" ? "bg-green-500 animate-pulse" : "bg-red-500"}`} />
                    <div className="min-w-0">
                      <p className="text-xs font-mono font-semibold truncate">{peer.device_name || peer.neighbor_ip}</p>
                      <p className="text-[9px] text-muted-foreground font-mono">{peer.neighbor_ip} · AS{peer.peer_as}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 flex-shrink-0">
                    <div className="text-right">
                      <p className="text-[9px] text-muted-foreground">{peer.prefixes_rx || 0} pfx</p>
                      <p className="text-[9px] text-muted-foreground">{peer.uptime_fmt || "—"}</p>
                    </div>
                    <BgpBadge state={peer.state} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Top Domains Panel */}
        <div className="bg-card border border-border rounded-sm p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <p className="text-xs font-semibold flex items-center gap-1.5">
                <Globe className="w-3.5 h-3.5 text-cyan-400" />
                Top 20 Domain
              </p>
              <p className="text-[10px] text-muted-foreground mt-0.5">Filter raw domain per platform</p>
            </div>
            
            <div className="relative">
              <button
                onClick={() => setShowDomainDropdown(!showDomainDropdown)}
                className="flex items-center gap-2 px-2 py-1 bg-secondary/30 hover:bg-secondary/50 rounded border border-border/50 text-[10px] font-medium transition-colors"
                title="Filter by Platform"
              >
                {domainPlatform === "all" ? "Semua Platform" : domainPlatform}
                <ChevronDown className="w-3 h-3 text-muted-foreground" />
              </button>
              
              {showDomainDropdown && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setShowDomainDropdown(false)} />
                  <div className="absolute right-0 top-full mt-1 w-40 bg-card border border-border rounded-md shadow-xl z-50 overflow-hidden text-[10px] max-h-64 overflow-y-auto">
                    <button
                      onClick={() => { setDomainPlatform("all"); setShowDomainDropdown(false); fetchAll(true); }}
                      className={`w-full text-left px-3 py-2 hover:bg-secondary/40 transition-colors ${domainPlatform === "all" ? "text-primary font-semibold" : "text-muted-foreground"}`}
                    >
                      Semua Platform
                    </button>
                    {["Situs Dewasa", "Judi Online", "YouTube", "TikTok", "Facebook", "Instagram", "WhatsApp", "Telegram", "Netflix", "Google", "Shopee", "Tokopedia"].map(p => (
                      <button
                        key={p}
                        onClick={() => { setDomainPlatform(p); setShowDomainDropdown(false); fetchAll(true); }}
                        className={`w-full text-left px-3 py-2 hover:bg-secondary/40 transition-colors ${domainPlatform === p ? "text-primary font-semibold" : "text-muted-foreground"}`}
                      >
                        {p}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>

          {topDomains.length === 0 ? (
            <NoData message="Belum ada data domain" />
          ) : (
            <div className="space-y-1 max-h-[400px] overflow-y-auto pr-1">
              {topDomains.map((d, i) => (
                <div key={i} className="flex items-center justify-between gap-2 py-1.5 border-b border-border/20">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-[10px] text-muted-foreground font-mono w-5 text-right flex-shrink-0">{i + 1}</span>
                    <span className="text-base leading-none">{d.icon}</span>
                    <div className="min-w-0">
                      <p className="text-xs font-mono font-semibold truncate text-foreground">{d.domain}</p>
                      <p className="text-[9px]" style={{ color: d.color }}>{d.platform}</p>
                    </div>
                  </div>
                  <div className="flex-shrink-0 flex items-center gap-3">
                    <div className="text-right">
                      <p className="text-xs font-mono text-cyan-300">{fmtNum(d.hits)}</p>
                      <p className="text-[9px] text-muted-foreground">hits</p>
                    </div>
                    <button
                      onClick={() => handleBlock("domain", d.domain)}
                      className="p-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-500 rounded transition-colors"
                      title="Blokir Domain"
                    >
                      <AlertCircle className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Top Clients Panel */}
        <div className="bg-card border border-border rounded-sm p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <p className="text-xs font-semibold flex items-center gap-1.5">
                <Users className="w-3.5 h-3.5 text-emerald-400" />
                Top 20 Klien
              </p>
              <p className="text-[10px] text-muted-foreground mt-0.5">IP klien terbanyak mengakses</p>
            </div>
          </div>

          {topClients.length === 0 ? (
            <NoData message="Belum ada data klien" />
          ) : (
            <div className="space-y-1 max-h-[400px] overflow-y-auto pr-1">
              {topClients.map((c, i) => (
                <div key={i} className="flex items-center justify-between gap-2 py-1.5 border-b border-border/20">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-[10px] text-muted-foreground font-mono w-5 text-right flex-shrink-0">{i + 1}</span>
                    <span className="text-base leading-none">{c.icon}</span>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-mono font-semibold truncate text-foreground">
                        {c.name && c.name !== "Unknown" ? c.name : c.ip}
                      </p>
                      <div className="flex items-center gap-2">
                        <p className="text-[9px]" style={{ color: c.color }}>{c.platform}</p>
                        <p className="text-[9px] text-muted-foreground font-mono">{c.name && c.name !== "Unknown" ? c.ip : ""}{c.mac ? ` • ${c.mac}` : ""}</p>
                      </div>
                    </div>
                  </div>
                  <div className="flex-shrink-0 flex items-center gap-3">
                    <div className="text-right">
                      <p className="text-xs font-mono text-emerald-300">
                        {c.bytes > 0 ? fmtBytes(c.bytes) : `${fmtNum(c.hits)} hits`}
                      </p>
                      <p className="text-[9px] text-muted-foreground">
                        {c.bytes > 0 ? `${fmtNum(c.hits)} hits` : "DNS only"}
                      </p>
                    </div>
                    <button
                      onClick={() => handleBlock("client", c.name && c.name !== "Unknown" ? c.name : c.ip)}
                      className="p-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-500 rounded transition-colors"
                      title="Blokir/Isolir Klien"
                    >
                      <AlertCircle className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

      </div>

      {showPlatformsModal && (
        <PeeringPlatformModal 
          onClose={() => setShowPlatformsModal(false)} 
          onChange={() => fetchAll(true)} 
        />
      )}
    </div>
  );
}
