import { useState, useEffect, useRef, useCallback } from "react";
import api from "@/lib/api";
import {
  Server, Cpu, HardDrive, Activity, Wifi, WifiOff, AlertTriangle,
  CheckCircle2, RefreshCw, Monitor, ZapOff, TrendingUp, TrendingDown,
  Power, ExternalLink, X, Loader2, Info, Clock
} from "lucide-react";
import { AreaChart, Area, ResponsiveContainer, Tooltip } from "recharts";
import { toast } from "sonner";

const REFRESH_INTERVAL = 5000; // 5 seconds

// Glow color by alert level
function getGlowStyle(level, status) {
  if (status === "offline" || level === "critical") {
    return {
      borderColor: "rgba(239,68,68,0.6)",
      boxShadow: "0 0 20px rgba(239,68,68,0.4), inset 0 0 20px rgba(239,68,68,0.05)",
    };
  }
  if (level === "warning") {
    return {
      borderColor: "rgba(234,179,8,0.6)",
      boxShadow: "0 0 20px rgba(234,179,8,0.3), inset 0 0 20px rgba(234,179,8,0.05)",
    };
  }
  return {
    borderColor: "rgba(34,197,94,0.5)",
    boxShadow: "0 0 16px rgba(34,197,94,0.25), inset 0 0 16px rgba(34,197,94,0.04)",
  };
}

function StatusBadge({ status }) {
  if (status === "online") {
    return (
      <span className="flex items-center gap-1 text-green-400 text-xs font-semibold">
        <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
        ONLINE
      </span>
    );
  }
  if (status === "offline") {
    return (
      <span className="flex items-center gap-1 text-red-400 text-xs font-semibold">
        <span className="w-2 h-2 rounded-full bg-red-400 animate-pulse" />
        OFFLINE
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-gray-400 text-xs font-semibold">
      <span className="w-2 h-2 rounded-full bg-gray-400" />
      UNKNOWN
    </span>
  );
}

function MetricBar({ value, max = 100, color }) {
  const pct = Math.min(100, Math.max(0, value));
  const barColor = value > 80 ? "#ef4444" : value > 60 ? "#eab308" : color;
  return (
    <div className="w-full h-1.5 rounded-full bg-white/10">
      <div
        className="h-full rounded-full transition-all duration-700"
        style={{ width: `${pct}%`, backgroundColor: barColor }}
      />
    </div>
  );
}

// ── Device Action Modal ───────────────────────────────────────────────────────
function DeviceActionModal({ device, onClose }) {
  const [rebooting, setRebooting] = useState(false);
  const [rebooted, setRebooted] = useState(false);
  const [winboxLoading, setWinboxLoading] = useState(false);
  const [connInfo, setConnInfo] = useState(null);

  // Deteksi mobile (Android / iPhone / iPad)
  const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);

  // Ambil info koneksi dari server saat modal terbuka
  useEffect(() => {
    if (!device?.id || device.status === "offline") return;
    api.get(`/devices/${device.id}/connection-info`)
      .then(r => setConnInfo(r.data))
      .catch(() => {});
  }, [device?.id]);

  const handleWinbox = async () => {
    setWinboxLoading(true);
    try {
      const res = await api.get(`/devices/${device.id}/winbox-url`);
      const { url, address, username, has_remote_address } = res.data;
      // winbox:// URL kompatibel desktop (Windows Winbox) DAN mobile (Winbox App Android/iOS)
      // Di mobile: browser akan prompt "Buka dengan Winbox?" jika app terinstall
      window.location.href = url;  // pakai location.href agar intercept URI scheme di mobile
      // Fallback toast
      const addrLabel = has_remote_address ? `${address} (remote)` : address;
      toast.success(`Winbox dibuka ke ${addrLabel} (user: ${username})`);
    } catch (e) {
      const msg = e.response?.data?.detail || "Gagal membuka Winbox";
      toast.error(msg);
    }
    setWinboxLoading(false);
  };

  const handleWebFig = () => {
    const ip = device.ip_address;
    const scheme = (connInfo?.use_https || device.use_https) ? "https" : "http";
    window.open(`${scheme}://${ip}`, "_blank");
    toast.info(`Membuka WebFig ke ${ip}...`);
  };

  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget) onClose();
  };

  const handleReboot = async () => {
    if (!window.confirm(`Yakin ingin reboot device "${device.identity || device.name}" (${device.ip_address})?`)) return;
    setRebooting(true);
    try {
      await api.post(`/devices/${device.id}/reboot`);
      setRebooted(true);
      toast.success(`Perintah reboot dikirim ke ${device.identity || device.name}`);
      setTimeout(onClose, 2500);
    } catch (e) {
      const msg = e.response?.data?.detail || "Gagal mengirim perintah reboot";
      toast.error(msg);
    }
    setRebooting(false);
  };

  const isOffline = device.status === "offline";

  // Alamat Winbox: pakai remote address jika diset, fallback ke ip_address
  const winboxAddr = connInfo?.winbox_address || device.ip_address;
  const hasRemote  = !!(connInfo?.winbox_address);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.75)", backdropFilter: "blur(8px)" }}
      onClick={handleBackdropClick}
    >
      <div
        className="relative w-full max-w-sm rounded-2xl border p-5 flex flex-col gap-4"
        style={{
          background: "linear-gradient(135deg, rgba(15,23,42,0.98) 0%, rgba(2,8,23,0.98) 100%)",
          borderColor: isOffline ? "rgba(239,68,68,0.5)" : "rgba(34,197,94,0.4)",
          boxShadow: isOffline
            ? "0 0 40px rgba(239,68,68,0.25), 0 25px 50px rgba(0,0,0,0.8)"
            : "0 0 40px rgba(34,197,94,0.15), 0 25px 50px rgba(0,0,0,0.8)",
        }}
      >
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-3 right-3 w-7 h-7 rounded-full flex items-center justify-center bg-white/5 hover:bg-white/10 transition-colors"
        >
          <X className="w-3.5 h-3.5 text-slate-400" />
        </button>

        {/* Header */}
        <div className="flex items-start gap-3">
          <div
            className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${
              isOffline ? "bg-red-500/15 border border-red-500/30" : "bg-green-500/15 border border-green-500/30"
            }`}
          >
            <Server className={`w-5 h-5 ${isOffline ? "text-red-400" : "text-green-400"}`} />
          </div>
          <div className="flex-1 min-w-0">
            <p className="font-bold text-white text-base truncate">{device.identity || device.name}</p>
            <p className="text-xs font-mono text-slate-400">{device.ip_address}</p>
            <div className="mt-1">
              {isOffline
                ? <span className="flex items-center gap-1 text-red-400 text-[11px] font-semibold"><span className="w-1.5 h-1.5 rounded-full bg-red-400 animate-pulse" />OFFLINE</span>
                : <span className="flex items-center gap-1 text-green-400 text-[11px] font-semibold"><span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />ONLINE</span>
              }
            </div>
          </div>
        </div>

        {/* Info Metrics */}
        <div className="rounded-xl bg-white/[0.04] border border-white/[0.08] p-3 space-y-2">
          <div className="grid grid-cols-2 gap-2 text-xs">
            {device.model && (
              <div><p className="text-slate-500 text-[10px] uppercase tracking-wider">Model</p><p className="text-slate-200 font-mono truncate">{device.model}</p></div>
            )}
            {device.ros_version && (
              <div><p className="text-slate-500 text-[10px] uppercase tracking-wider">RouterOS</p><p className="text-slate-200 font-mono">v{device.ros_version}</p></div>
            )}
            {!isOffline && device.cpu_load != null && (
              <div><p className="text-slate-500 text-[10px] uppercase tracking-wider">CPU</p><p className={`font-mono font-semibold ${device.cpu_load > 80 ? "text-red-400" : device.cpu_load > 60 ? "text-yellow-400" : "text-green-400"}`}>{device.cpu_load}%</p></div>
            )}
            {!isOffline && device.memory_usage != null && (
              <div><p className="text-slate-500 text-[10px] uppercase tracking-wider">Memory</p><p className={`font-mono font-semibold ${device.memory_usage > 80 ? "text-red-400" : device.memory_usage > 60 ? "text-yellow-400" : "text-blue-400"}`}>{device.memory_usage}%</p></div>
            )}
            {!isOffline && device.ping_ms > 0 && (
              <div><p className="text-slate-500 text-[10px] uppercase tracking-wider">Ping</p><p className={`font-mono font-semibold ${device.ping_ms > 100 ? "text-red-400" : device.ping_ms > 50 ? "text-yellow-400" : "text-cyan-400"}`}>{device.ping_ms}ms</p></div>
            )}
            {device.uptime && (
              <div><p className="text-slate-500 text-[10px] uppercase tracking-wider">Uptime</p><p className="text-slate-300 font-mono text-[10px]">{device.uptime}</p></div>
            )}
          </div>

          {/* Winbox Credential Info */}
          {!isOffline && connInfo?.api_username && (
            <div className="border-t border-white/[0.08] pt-2 mt-1 space-y-1.5">
              <div className="flex items-center justify-between">
                <p className="text-slate-500 text-[10px] uppercase tracking-wider">Winbox Credential</p>
                {hasRemote && (
                  <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/30 text-amber-400 font-semibold">
                    📡 Remote Address
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                {/* Address — remote jika ada, fallback IP lokal */}
                <div className={`flex-1 rounded-lg px-2 py-1.5 border ${
                  hasRemote
                    ? "bg-amber-500/10 border-amber-500/25"
                    : "bg-blue-500/10 border-blue-500/20"
                }`}>
                  <p className={`text-[9px] ${hasRemote ? "text-amber-400/70" : "text-blue-400/70"}`}>
                    {hasRemote ? "Remote" : "Address"}
                  </p>
                  <p className={`font-mono text-[11px] ${hasRemote ? "text-amber-300" : "text-blue-300"}`}>{winboxAddr}</p>
                </div>
                <div className="flex-1 rounded-lg bg-blue-500/10 border border-blue-500/20 px-2 py-1.5">
                  <p className="text-[9px] text-blue-400/70">Username</p>
                  <p className="text-blue-300 font-mono text-[11px]">{connInfo.api_username}</p>
                </div>
                <div className="flex-1 rounded-lg bg-blue-500/10 border border-blue-500/20 px-2 py-1.5">
                  <p className="text-[9px] text-blue-400/70">Password</p>
                  <p className="text-blue-300 font-mono text-[11px]">••••••••</p>
                </div>
              </div>
              {hasRemote && (
                <p className="text-[9px] text-slate-500">
                  API: <span className="font-mono text-slate-400">{device.ip_address}</span>
                  <span className="text-slate-600 mx-1">·</span>
                  Winbox: <span className="font-mono text-amber-400/80">{winboxAddr}</span>
                </p>
              )}
              <p className="text-[9px] text-slate-600">✓ Credential akan terisi otomatis saat Winbox dibuka</p>
            </div>
          )}
        </div>

        {/* Action Buttons */}
        <div className="space-y-2">
          {/* Reboot */}
          <button
            onClick={handleReboot}
            disabled={rebooting || rebooted || isOffline}
            className={`w-full flex items-center justify-center gap-2.5 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 ${
              rebooted
                ? "bg-green-500/20 border border-green-500/40 text-green-400 cursor-default"
                : isOffline
                  ? "bg-white/5 border border-white/10 text-slate-600 cursor-not-allowed"
                  : "bg-red-500/15 border border-red-500/30 text-red-400 hover:bg-red-500/25 hover:border-red-500/50 active:scale-95"
            }`}
          >
            {rebooting ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> Mengirim perintah reboot...</>
            ) : rebooted ? (
              <><CheckCircle2 className="w-4 h-4" /> Reboot dikirim! Device akan restart...</>
            ) : (
              <><Power className="w-4 h-4" /> Reboot Device{isOffline ? " (Offline)" : ""}</>
            )}
          </button>

          {/* Remote Winbox */}
          <button
            onClick={handleWinbox}
            disabled={isOffline || winboxLoading}
            className={`w-full flex flex-col items-center justify-center gap-0.5 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 ${
              isOffline
                ? "bg-white/5 border border-white/10 text-slate-600 cursor-not-allowed"
                : "bg-blue-500/15 border border-blue-500/30 text-blue-400 hover:bg-blue-500/25 hover:border-blue-500/50 active:scale-95"
            }`}
          >
            <span className="flex items-center gap-2">
              {winboxLoading
                ? <><Loader2 className="w-4 h-4 animate-spin" /> Membuka Winbox...</>
                : <><ExternalLink className="w-4 h-4" /> Remote Winbox (auto-login)</>
              }
            </span>
            {/* Info mobile — hanya tampil di HP */}
            {isMobile && !isOffline && !winboxLoading && (
              <span className="text-[10px] text-blue-400/60 font-normal flex items-center gap-1">
                📱 Tersedia di Winbox App (Android/iOS)
              </span>
            )}
          </button>

          {/* WebFig */}
          <button
            onClick={handleWebFig}
            disabled={isOffline}
            className={`w-full flex items-center justify-center gap-2.5 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 ${
              isOffline
                ? "bg-white/5 border border-white/10 text-slate-600 cursor-not-allowed"
                : "bg-cyan-500/15 border border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/25 hover:border-cyan-500/50 active:scale-95"
            }`}
          >
            <Wifi className="w-4 h-4" />
            Buka WebFig (Browser)
          </button>
        </div>

        {isOffline && (
          <p className="text-[10px] text-slate-600 text-center">Reboot dan remote tidak tersedia saat device offline</p>
        )}
      </div>
    </div>
  );
}

function DeviceCard({ device, onSelect }) {
  const glowStyle = getGlowStyle(device.alert_level, device.status);
  const isOffline = device.status === "offline";

  return (
    <div
      onClick={() => onSelect(device)}
      className="relative rounded-xl border p-4 flex flex-col gap-2 transition-all duration-500 cursor-pointer hover:scale-[1.02] hover:brightness-110 select-none"
      style={{
        background: "linear-gradient(135deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.01) 100%)",
        backdropFilter: "blur(12px)",
        ...glowStyle,
      }}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-bold text-white truncate leading-tight">
            {device.identity || device.name}
          </p>
          <p className="text-[10px] text-slate-400 font-mono">{device.ip_address}</p>
        </div>
        <StatusBadge status={device.status} />
      </div>

      {/* Model + Uptime */}
      {device.model && (
        <p className="text-[10px] text-slate-500 truncate">{device.model} {device.ros_version ? `· v${device.ros_version}` : ""}</p>
      )}

      {/* Metrics */}
      {!isOffline ? (
        <div className="space-y-2 mt-1">
          <div>
            <div className="flex justify-between text-[10px] mb-0.5">
              <span className="text-slate-400 flex items-center gap-1"><Cpu className="w-3 h-3" /> CPU</span>
              <span className={`font-mono font-semibold ${device.cpu_load > 80 ? "text-red-400" : device.cpu_load > 60 ? "text-yellow-400" : "text-green-400"}`}>{device.cpu_load}%</span>
            </div>
            <MetricBar value={device.cpu_load} color="#22c55e" />
          </div>
          <div>
            <div className="flex justify-between text-[10px] mb-0.5">
              <span className="text-slate-400 flex items-center gap-1"><HardDrive className="w-3 h-3" /> MEM</span>
              <span className={`font-mono font-semibold ${device.memory_usage > 80 ? "text-red-400" : device.memory_usage > 60 ? "text-yellow-400" : "text-blue-400"}`}>{device.memory_usage}%</span>
            </div>
            <MetricBar value={device.memory_usage} color="#3b82f6" />
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-center py-3">
          <WifiOff className="w-8 h-8 text-red-500/60" />
        </div>
      )}

      {/* Footer stats */}
      <div className="grid grid-cols-3 gap-1 mt-1 pt-2 border-t border-white/10">
        <div className="text-center">
          <p className="text-[9px] text-slate-500 uppercase">Ping</p>
          <p className={`text-[11px] font-mono font-bold ${
            !isOffline && device.ping_ms > 100 ? "text-red-400" :
            !isOffline && device.ping_ms > 50  ? "text-yellow-400" :
            !isOffline && device.ping_ms > 10  ? "text-green-400" :
            "text-cyan-400"
          }`}>
            {isOffline ? "—" : device.ping_ms > 0 ? `${device.ping_ms}ms` : "—"}
          </p>
        </div>
        <div className="text-center">
          <p className="text-[9px] text-slate-500 flex items-center justify-center gap-0.5"><TrendingDown className="w-2.5 h-2.5" />DL</p>
          <p className="text-[11px] font-mono font-bold text-blue-400">{isOffline ? "—" : `${device.download_mbps}M`}</p>
        </div>
        <div className="text-center">
          <p className="text-[9px] text-slate-500 flex items-center justify-center gap-0.5"><TrendingUp className="w-2.5 h-2.5" />UL</p>
          <p className="text-[11px] font-mono font-bold text-green-400">{isOffline ? "—" : `${device.upload_mbps}M`}</p>
        </div>
      </div>
    </div>
  );
}

function EventTicker({ events }) {
  const ref = useRef(null);
  // Infinitely scroll the event list
  useEffect(() => {
    const el = ref.current;
    if (!el || !events.length) return;
    let x = 0;
    const speed = 0.7;
    const anim = requestAnimationFrame(function tick() {
      x -= speed;
      if (Math.abs(x) >= el.scrollWidth / 2) x = 0;
      el.style.transform = `translateX(${x}px)`;
      requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(anim);
  }, [events]);

  const colorMap = {
    red: "text-red-400",
    green: "text-green-400",
    yellow: "text-yellow-400",
    orange: "text-orange-400",
    blue: "text-blue-400",
  };

  const items = [...events, ...events]; // duplicate for seamless loop

  return (
    <div className="overflow-hidden whitespace-nowrap">
      <div ref={ref} className="inline-flex gap-8">
        {items.map((ev, i) => (
          <span key={i} className={`text-xs font-mono ${colorMap[ev.color] || "text-slate-400"}`}>
            <span className="text-slate-500 mr-2">{ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }) : ""}</span>
            {ev.message}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function WallDisplayPage() {
  const [data, setData] = useState(null);
  const [events, setEvents] = useState([]);
  const [time, setTime] = useState(new Date());
  const [bwHistory, setBwHistory] = useState([]);
  const [deviceBwHistory, setDeviceBwHistory] = useState({});
  const [selectedDevice, setSelectedDevice] = useState(null); // untuk modal aksi

  const fetchData = async () => {
    try {
      const [statusRes, eventsRes] = await Promise.all([
        api.get("/wallboard/status"),
        api.get("/wallboard/events"),
      ]);
      setData(statusRes.data);
      setEvents(eventsRes.data.events || []);

      const devs = statusRes.data.devices || [];

      // Track aggregated BW history
      const total_dl = devs.reduce((s, d) => s + (d.download_mbps || 0), 0);
      const total_ul = devs.reduce((s, d) => s + (d.upload_mbps || 0), 0);
      setBwHistory(prev => {
        const next = [...prev, { download: parseFloat(total_dl.toFixed(2)), upload: parseFloat(total_ul.toFixed(2)) }];
        return next.slice(-30);
      });

      // Track per-device BW history
      setDeviceBwHistory(prev => {
        const next = { ...prev };
        for (const d of devs) {
          const hist = next[d.id] || [];
          next[d.id] = [...hist, {
            dl: parseFloat((d.download_mbps || 0).toFixed(2)),
            ul: parseFloat((d.upload_mbps || 0).toFixed(2)),
          }].slice(-20);
        }
        return next;
      });
    } catch (e) {
      console.error("Wallboard fetch error:", e);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, REFRESH_INTERVAL);
    const clockInterval = setInterval(() => setTime(new Date()), 1000);
    return () => { clearInterval(interval); clearInterval(clockInterval); };
  }, []);

  const summary = data?.summary || { total: 0, online: 0, offline: 0, warning: 0 };
  const devices = data?.devices || [];

  return (
    <div
      className="min-h-screen flex flex-col"
      style={{
        background: "linear-gradient(135deg, #020817 0%, #0a1628 50%, #020817 100%)",
        fontFamily: "'Inter', 'Rajdhani', sans-serif",
      }}
    >
      {/* ── TOP HEADER ─────────────────────────────────────────────── */}
      <div
        className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 px-3 sm:px-6 py-2 sm:py-3 border-b"
        style={{
          borderColor: "rgba(99,179,237,0.2)",
          background: "linear-gradient(90deg, rgba(14,165,233,0.08) 0%, rgba(0,0,0,0) 50%, rgba(14,165,233,0.08) 100%)",
        }}
      >
        <div className="flex items-center justify-between sm:justify-start gap-3">
          <div className="flex items-center gap-3">
            <div className="w-7 h-7 sm:w-8 sm:h-8 bg-blue-500/20 border border-blue-500/40 rounded-lg flex items-center justify-center">
              <Monitor className="w-4 h-4 sm:w-5 sm:h-5 text-blue-400" />
            </div>
            <div>
              <h1 className="text-base sm:text-lg font-['Rajdhani'] font-bold text-white tracking-wider">
                NOC SENTINEL <span className="text-blue-400">v3</span>
              </h1>
              <p className="text-[9px] sm:text-[10px] text-slate-400 tracking-widest uppercase hidden sm:block">ARBA MONITORING · WALL DISPLAY</p>
            </div>
          </div>
          {/* Clock on mobile beside logo */}
          <div className="text-right sm:hidden">
            <p className="text-lg font-mono font-bold text-white">
              {time.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </p>
            <p className="text-[9px] text-slate-400">{time.toLocaleDateString("id-ID", { weekday: "short", day: "2-digit", month: "short" })}</p>
          </div>
        </div>

        {/* Stats Counter */}
        <div className="flex items-center gap-2 sm:gap-6 flex-wrap">
          <div className="flex items-center gap-1.5 sm:gap-2 px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg bg-green-500/10 border border-green-500/30">
            <CheckCircle2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-green-400" />
            <span className="text-green-400 font-bold font-['Rajdhani'] text-lg sm:text-xl">{summary.online}</span>
            <span className="text-green-400/70 text-[10px] sm:text-xs">online</span>
          </div>
          <div className="flex items-center gap-1.5 sm:gap-2 px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg bg-red-500/10 border border-red-500/30">
            <ZapOff className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-red-400" />
            <span className="text-red-400 font-bold font-['Rajdhani'] text-lg sm:text-xl">{summary.offline}</span>
            <span className="text-red-400/70 text-[10px] sm:text-xs">offline</span>
          </div>
          <div className="flex items-center gap-1.5 sm:gap-2 px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg bg-yellow-500/10 border border-yellow-500/30">
            <AlertTriangle className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-yellow-400" />
            <span className="text-yellow-400 font-bold font-['Rajdhani'] text-lg sm:text-xl">{summary.warning}</span>
            <span className="text-yellow-400/70 text-[10px] sm:text-xs">warning</span>
          </div>
          {/* Clock on desktop */}
          <div className="text-right hidden sm:block">
            <p className="text-2xl font-mono font-bold text-white">
              {time.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </p>
            <p className="text-[10px] text-slate-400">{time.toLocaleDateString("id-ID", { weekday: "long", day: "2-digit", month: "long", year: "numeric" })}</p>
          </div>
        </div>
      </div>

      {/* ── MAIN CONTENT ────────────────────────────────────────────── */}
      <div className="flex flex-col lg:flex-row flex-1 gap-3 p-3 sm:p-4 min-h-0 overflow-hidden">
        {/* Device Grid — scrolls independently */}
        <div className="flex-1 min-h-0 overflow-y-auto">
          {devices.length === 0 ? (
            <div className="flex items-center justify-center h-full min-h-[200px]">
              <div className="text-center text-slate-500">
                <Server className="w-14 h-14 mx-auto mb-3 opacity-30" />
                <p>No devices configured</p>
              </div>
            </div>
          ) : (
          <div className="grid gap-2 sm:gap-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))" }}>
              {devices.map(d => <DeviceCard key={d.id} device={d} onSelect={setSelectedDevice} />)}
            </div>
          )}
        </div>

        {/* Right Panel — full height, scrollable */}
        <div className="w-full lg:w-72 flex-shrink-0 flex flex-col sm:flex-row lg:flex-col gap-3 lg:overflow-y-auto lg:h-full">
          <div
            className="rounded-xl border p-4 flex flex-col flex-1"
            style={{
              background: "rgba(255,255,255,0.03)",
              borderColor: "rgba(99,179,237,0.2)",
            }}
          >
            <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-widest mb-3 flex items-center gap-2">
              <Activity className="w-3.5 h-3.5 text-blue-400" /> Bandwidth Real-time (ISP)
            </h3>

            {/* ── Total Bandwidth Numbers ── */}
            {bwHistory.length > 0 && (() => {
              const latest = bwHistory[bwHistory.length - 1];
              const formatBw = (mbps) => {
                if (mbps >= 1000) return `${(mbps / 1000).toFixed(2)} Gbps`;
                if (mbps >= 1) return `${mbps.toFixed(1)} Mbps`;
                return `${(mbps * 1000).toFixed(0)} Kbps`;
              };
              return (
                <div className="grid grid-cols-2 gap-2 mb-3">
                  <div className="rounded-lg bg-blue-500/10 border border-blue-500/20 p-2 text-center">
                    <p className="text-[9px] text-blue-400/70 uppercase tracking-widest flex items-center justify-center gap-1 mb-0.5">
                      <TrendingDown className="w-2.5 h-2.5" /> Download
                    </p>
                    <p className="text-lg font-bold font-mono text-blue-300 leading-tight">{formatBw(latest.download)}</p>
                    <p className="text-[9px] text-blue-500/60">total ISP all devices</p>
                  </div>
                  <div className="rounded-lg bg-green-500/10 border border-green-500/20 p-2 text-center">
                    <p className="text-[9px] text-green-400/70 uppercase tracking-widest flex items-center justify-center gap-1 mb-0.5">
                      <TrendingUp className="w-2.5 h-2.5" /> Upload
                    </p>
                    <p className="text-lg font-bold font-mono text-green-300 leading-tight">{formatBw(latest.upload)}</p>
                    <p className="text-[9px] text-green-500/60">total ISP all devices</p>
                  </div>
                </div>
              );
            })()}

            {/* Aggregated chart */}
            <div className="h-24">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={bwHistory}>
                  <defs>
                    <linearGradient id="wdl" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="wul" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#22c55e" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <Tooltip
                    contentStyle={{ background: "#0f172a", border: "1px solid #1e3a5f", borderRadius: "8px", fontSize: "11px" }}
                    labelStyle={{ color: "#94a3b8" }}
                    formatter={(v) => [`${v} Mbps`]}
                  />
                  <Area type="monotone" dataKey="download" stroke="#3b82f6" fill="url(#wdl)" strokeWidth={2} name="DL" dot={false} />
                  <Area type="monotone" dataKey="upload" stroke="#22c55e" fill="url(#wul)" strokeWidth={2} name="UL" dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div className="flex gap-4 mt-1 mb-3 text-[10px] text-slate-500">
              <span className="flex items-center gap-1"><span className="w-2 h-[2px] bg-blue-500 inline-block" /> DL</span>
              <span className="flex items-center gap-1"><span className="w-2 h-[2px] bg-green-500 inline-block" /> UL</span>
              <span className="ml-auto text-slate-600">{bwHistory.length} pts</span>
            </div>

            {/* ── Per-device ISP interface bandwidth ── */}
            <div className="border-t border-white/10 pt-3 mt-1">
              <div className="flex items-center justify-between mb-2">
                <p className="text-[9px] text-slate-500 uppercase tracking-widest">Per-Device ISP Bandwidth</p>
                <span className="text-[9px] text-slate-600 font-mono">
                  {devices.filter(d => d.status === "online").length} online
                </span>
              </div>
              {/* max-height for ~6 items (~72px each) */}
              <div className="overflow-y-auto space-y-2 pr-0.5" style={{ maxHeight: "432px" }}>
              {devices.filter(d => d.status === "online").map(d => {
                const hist = deviceBwHistory[d.id] || [];
                const latest = hist[hist.length - 1] || { dl: d.download_mbps || 0, ul: d.upload_mbps || 0 };
                const formatBw = (v) => {
                  if (!v) return "0"; 
                  if (v >= 1000) return `${(v/1000).toFixed(1)}G`;
                  if (v >= 1) return `${v.toFixed(1)}M`;
                  return `${(v*1000).toFixed(0)}K`;
                };
                const isp = d.isp_interfaces?.join(", ") || "";
                return (
                  <div key={d.id} className="rounded-lg bg-white/[0.03] border border-white/[0.07] p-2">
                    <div className="flex items-center justify-between mb-1">
                      <div className="min-w-0 flex-1">
                        <p className="text-[10px] font-semibold text-white truncate">{d.identity || d.name}</p>
                        {isp && <p className="text-[9px] text-blue-400/70 font-mono truncate">{isp}</p>}
                      </div>
                      <div className="flex gap-2 text-[10px] font-mono ml-2 flex-shrink-0">
                        <span className="text-blue-300"><TrendingDown className="w-2.5 h-2.5 inline" /> {formatBw(latest.dl)}</span>
                        <span className="text-green-300"><TrendingUp className="w-2.5 h-2.5 inline" /> {formatBw(latest.ul)}</span>
                      </div>
                    </div>
                    {/* Tiny sparkline charts */}
                    {hist.length > 1 && (
                      <div className="h-8">
                        <ResponsiveContainer width="100%" height="100%">
                          <AreaChart data={hist} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
                            <defs>
                              <linearGradient id={`dl_${d.id}`} x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.5} />
                                <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                              </linearGradient>
                              <linearGradient id={`ul_${d.id}`} x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor="#22c55e" stopOpacity={0.5} />
                                <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
                              </linearGradient>
                            </defs>
                            <Area type="monotone" dataKey="dl" stroke="#3b82f6" fill={`url(#dl_${d.id})`} strokeWidth={1.5} dot={false} />
                            <Area type="monotone" dataKey="ul" stroke="#22c55e" fill={`url(#ul_${d.id})`} strokeWidth={1.5} dot={false} />
                          </AreaChart>
                        </ResponsiveContainer>
                      </div>
                    )}
                  </div>
                );
              })}
              {devices.filter(d => d.status === "online").length === 0 && (
                <p className="text-[10px] text-slate-600 text-center py-2">No online devices</p>
              )}
              </div>
            </div>
          </div>

          {/* Active Alerts */}
          <div
            className="rounded-xl border p-4"
            style={{
              background: "rgba(255,255,255,0.03)",
              borderColor: "rgba(99,179,237,0.2)",
            }}
          >
            <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-widest mb-3 flex items-center gap-2">
              <AlertTriangle className="w-3.5 h-3.5 text-yellow-400" /> Active Alerts
            </h3>
            <div className="space-y-2 max-h-48 overflow-y-auto">
              {devices.filter(d => d.alert_level !== "normal").length === 0 ? (
                <div className="flex items-center gap-2 text-green-400 text-xs">
                  <CheckCircle2 className="w-4 h-4" /> All systems normal
                </div>
              ) : (
                devices
                  .filter(d => d.alert_level !== "normal")
                  .map(d => (
                    <div key={d.id} className={`flex items-start gap-2 p-2 rounded-lg text-xs ${d.alert_level === "critical" ? "bg-red-500/10 border border-red-500/20" : "bg-yellow-500/10 border border-yellow-500/20"}`}>
                      {d.alert_level === "critical" ? <WifiOff className="w-3.5 h-3.5 text-red-400 flex-shrink-0 mt-0.5" /> : <AlertTriangle className="w-3.5 h-3.5 text-yellow-400 flex-shrink-0 mt-0.5" />}
                      <div>
                        <p className={`font-semibold ${d.alert_level === "critical" ? "text-red-300" : "text-yellow-300"}`}>{d.name}</p>
                        <p className="text-slate-400 font-mono text-[10px]">
                          {d.status === "offline" ? "OFFLINE" : `CPU:${d.cpu_load}% MEM:${d.memory_usage}%`}
                        </p>
                      </div>
                    </div>
                  ))
              )}
            </div>
          </div>

          {/* Refresh indicator */}
          <div className="flex items-center justify-center gap-2 text-slate-600 text-[10px]">
            <RefreshCw className="w-3 h-3 animate-spin" style={{ animationDuration: "3s" }} />
            Auto-refresh every 10s
          </div>
        </div>
      </div>

      {/* ── BOTTOM TICKER ───────────────────────────────────────────── */}
      <div
        className="border-t px-4 py-2"
        style={{
          borderColor: "rgba(99,179,237,0.2)",
          background: "rgba(0,0,0,0.4)",
        }}
      >
        {events.length > 0 ? (
          <EventTicker events={events} />
        ) : (
          <p className="text-slate-600 text-xs text-center font-mono">No recent events</p>
        )}
      </div>

      {/* ── DEVICE ACTION MODAL ──────────────────────────────────────── */}
      {selectedDevice && (
        <DeviceActionModal
          device={selectedDevice}
          onClose={() => setSelectedDevice(null)}
        />
      )}
    </div>
  );
}
