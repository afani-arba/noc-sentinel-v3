import { useState, useEffect, useRef, useCallback } from "react";
import api from "@/lib/api";
import {
  Server, Cpu, HardDrive, Wifi, WifiOff, AlertTriangle,
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
  if (status === "online")  return <span className="w-2.5 h-2.5 rounded-full bg-green-400 animate-pulse flex-shrink-0" title="Online" />;
  if (status === "offline") return <span className="w-2.5 h-2.5 rounded-full bg-red-400 animate-pulse flex-shrink-0" title="Offline" />;
  return <span className="w-2.5 h-2.5 rounded-full bg-gray-500 flex-shrink-0" title="Unknown" />;
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
  // FIX Bug #1: Ganti window.confirm() (diblokir mobile) dengan state konfirmasi inline
  const [confirmReboot, setConfirmReboot] = useState(false);

  // Deteksi mobile (Android / iPhone / iPad)
  const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);

  // Ambil info koneksi dari server saat modal terbuka
  useEffect(() => {
    if (!device?.id || device.status === "offline") return;
    api.get(`/devices/${device.id}/connection-info`)
      .then(r => setConnInfo(r.data))
      .catch(() => { });
  }, [device?.id]);

  // FIX Bug #2: Winbox deep link — gunakan window.location.href agar reliable di mobile
  // window.open dengan _self sering diblokir untuk custom URI scheme (winbox://) di Chrome Android/Safari iOS
  const handleWinbox = async () => {
    setWinboxLoading(true);
    try {
      const res = await api.get(`/devices/${device.id}/winbox-url`);
      const { url, mobile_url, address, username, has_remote_address, winbox_path } = res.data;
      const targetUrl = (isMobile && mobile_url) ? mobile_url : url;

      // Jika ada winbox_path di server (diset di Settings), gunakan file:// scheme
      // agar OS langsung meluncurkan Winbox.exe tanpa bergantung pada URI handler
      if (!isMobile && winbox_path) {
        // Format: "path/to/winbox.exe" address user pass
        // Kita buka via custom protocol atau fallback ke winbox:// URI scheme
        window.location.href = targetUrl;
      } else {
        // window.location.href lebih reliable untuk custom URI scheme (winbox://) di semua browser
        window.location.href = targetUrl;
      }

      const addrLabel = has_remote_address ? `${address} (remote)` : address;
      toast.success(`Winbox dibuka ke ${addrLabel} (user: ${username})`);
    } catch (e) {
      const status = e.response?.status;
      const msg = status === 403
        ? "Akses ditolak — hubungi administrator"
        : (e.response?.data?.detail || "Gagal membuka Winbox");
      toast.error(msg);
    }
    setWinboxLoading(false);
  };

  // FIX Bug #3: WebFig — gunakan window.location.href di mobile (hindari popup blocker)
  // Sertakan port yang benar di URL WebFig
  const handleWebFig = () => {
    const useHttps = connInfo?.use_https || device.use_https;
    const scheme = useHttps ? "https" : "http";
    // Gunakan webfig port yang benar; default 80 (http) atau 443 (https)
    const port = connInfo?.api_port || device.api_port;
    // Hanya tampilkan port jika bukan default (80 untuk http, 443 untuk https)
    const isDefaultPort = !port || (useHttps ? port === 443 : port === 80);
    const webfigPort = isDefaultPort ? "" : `:${port}`;
    // Alamat WebFig: gunakan ip_address (API address) bukan winbox_address
    const ip = device.ip_address;
    const webfigUrl = `${scheme}://${ip}${webfigPort}`;
    toast.info(`Membuka WebFig ke ${ip}...`);
    if (isMobile) {
      // Mobile: langsung navigate (hindari popup blocker)
      window.location.href = webfigUrl;
    } else {
      // Desktop: buka di tab baru
      const w = window.open(webfigUrl, "_blank");
      if (!w) window.location.href = webfigUrl; // fallback jika popup diblokir
    }
  };

  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget) onClose();
  };

  // FIX Bug #1: handleReboot sekarang dua tahap — pertama set confirmReboot, lalu eksekusi
  const handleReboot = async () => {
    if (!confirmReboot) {
      // Tampilkan konfirmasi inline (tidak pakai window.confirm yang diblokir mobile)
      setConfirmReboot(true);
      return;
    }
    // Eksekusi reboot
    setConfirmReboot(false);
    setRebooting(true);
    try {
      await api.post(`/devices/${device.id}/reboot`);
      setRebooted(true);
      toast.success(`Perintah reboot dikirim ke ${device.identity || device.name}`);
      setTimeout(onClose, 2500);
    } catch (e) {
      // Cek apakah error adalah network error (koneksi terputus)
      // Ini bisa terjadi karena MikroTik reboot SEGERA setelah terima perintah,
      // sehingga koneksi ke backend sempat terputus sebelum response diterima
      if (!e.response && (e.code === 'ERR_NETWORK' || e.message?.includes('Network Error'))) {
        setRebooted(true);
        toast.success(`Reboot kemungkinan berhasil — ${device.identity || device.name} mungkin sedang restart`);
        setTimeout(onClose, 3000);
      } else {
        const msg = e.response?.data?.detail || "Gagal mengirim perintah reboot";
        toast.error(msg);
      }
    }
    setRebooting(false);
  };

  const isOffline = device.status === "offline";

  // Alamat Winbox: pakai remote address jika diset, fallback ke ip_address
  const winboxAddr = connInfo?.winbox_address || device.ip_address;
  const hasRemote = !!(connInfo?.winbox_address);

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
            className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${isOffline ? "bg-red-500/15 border border-red-500/30" : "bg-green-500/15 border border-green-500/30"
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
                <div className={`flex-1 rounded-lg px-2 py-1.5 border ${hasRemote
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
          {/* Reboot — dua tahap: tombol → konfirmasi inline → eksekusi */}
          {confirmReboot && !rebooting && !rebooted && (
            <div className="rounded-xl bg-red-500/10 border border-red-500/40 p-3 space-y-2">
              <p className="text-xs text-red-300 text-center font-semibold">
                ⚠️ Yakin ingin reboot <span className="text-white">{device.identity || device.name}</span>?
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => setConfirmReboot(false)}
                  className="flex-1 py-2 rounded-lg text-xs font-semibold bg-white/5 border border-white/10 text-slate-400 hover:bg-white/10 active:scale-95 transition-all"
                >
                  Batal
                </button>
                <button
                  onClick={handleReboot}
                  className="flex-1 py-2 rounded-lg text-xs font-bold bg-red-500/25 border border-red-500/50 text-red-300 hover:bg-red-500/35 active:scale-95 transition-all"
                >
                  Ya, Reboot!
                </button>
              </div>
            </div>
          )}
          <button
            onClick={handleReboot}
            disabled={rebooting || rebooted || isOffline}
            className={`w-full flex items-center justify-center gap-2.5 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 ${rebooted
                ? "bg-green-500/20 border border-green-500/40 text-green-400 cursor-default"
                : isOffline
                  ? "bg-white/5 border border-white/10 text-slate-600 cursor-not-allowed"
                  : confirmReboot
                    ? "bg-red-500/25 border border-red-500/50 text-red-300 cursor-default"
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
            className={`w-full flex flex-col items-center justify-center gap-0.5 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 ${isOffline
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

        </div>

        {isOffline && (
          <p className="text-[10px] text-slate-600 text-center">Reboot dan remote tidak tersedia saat device offline</p>
        )}
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

  const summary = data?.summary || { total: 0, online: 0, offline: 0, warning: 0, total_pppoe: 0, total_hotspot: 0 };
  const devices = data?.devices || [];

  // Hitung total bandwidth semua device (ISP accumulated)
  const formatBwHeader = (mbps) => {
    if (mbps >= 1000) return `${(mbps / 1000).toFixed(2)} Gbps`;
    if (mbps >= 1) return `${mbps.toFixed(1)} Mbps`;
    return `${(mbps * 1000).toFixed(0)} Kbps`;
  };
  const total_dl = devices.reduce((s, d) => s + (d.download_mbps || 0), 0);
  const total_ul = devices.reduce((s, d) => s + (d.upload_mbps || 0), 0);

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
        {/* Logo + Title */}
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

        {/* Stats Counter */}
        <div className="flex items-center gap-2 sm:gap-3 flex-wrap">
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

          {/* Total Bandwidth — semua device ISP accumulated */}
          {devices.length > 0 && (
            <div className="flex items-center gap-1.5 sm:gap-2 px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/25">
              <TrendingDown className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-blue-400" />
              <span className="text-blue-300 font-bold font-['Rajdhani'] text-lg sm:text-xl">{formatBwHeader(total_dl)}</span>
              <span className="text-slate-600 text-xs">/</span>
              <TrendingUp className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-green-400" />
              <span className="text-green-300 font-bold font-['Rajdhani'] text-lg sm:text-xl">{formatBwHeader(total_ul)}</span>
              <span className="text-cyan-400/60 text-[10px] sm:text-xs hidden sm:inline">ISP</span>
            </div>
          )}

          {/* PPPoE & Hotspot Total Badges — accumulation from all online devices */}
          {summary.total_pppoe > 0 && (
            <div className="flex items-center gap-1.5 px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg border"
              style={{ background: "rgba(0,212,255,0.07)", borderColor: "rgba(0,212,255,0.3)" }}>
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="#00d4ff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M8 12h.01M12 12h.01M16 12h.01" /><rect x="2" y="4" width="20" height="16" rx="2" />
              </svg>
              <span className="font-bold font-['Rajdhani'] text-lg sm:text-xl" style={{ color: "#00d4ff" }}>{summary.total_pppoe.toLocaleString()}</span>
              <span className="text-[10px] sm:text-xs hidden sm:inline" style={{ color: "rgba(0,212,255,0.7)" }}>PPPoE</span>
            </div>
          )}
          {summary.total_hotspot > 0 && (
            <div className="flex items-center gap-1.5 px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg border"
              style={{ background: "rgba(255,140,0,0.07)", borderColor: "rgba(255,140,0,0.35)" }}>
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="#ff8c00" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12.55a11 11 0 0 1 14.08 0" /><path d="M1.42 9a16 16 0 0 1 21.16 0" /><path d="M8.53 16.11a6 6 0 0 1 6.95 0" /><circle cx="12" cy="20" r="1" fill="#ff8c00" />
              </svg>
              <span className="font-bold font-['Rajdhani'] text-lg sm:text-xl" style={{ color: "#ff8c00" }}>{summary.total_hotspot.toLocaleString()}</span>
              <span className="text-[10px] sm:text-xs hidden sm:inline" style={{ color: "rgba(255,140,0,0.7)" }}>Hotspot</span>
            </div>
          )}
        </div>

      </div>

      {/* ── MAIN CONTENT ────────────────────────────────────────────── */}
      <div className="flex flex-col lg:flex-row flex-1 gap-3 p-3 sm:p-4 min-h-0 overflow-hidden">

        {/* ── Main Area: Per-Device ISP Bandwidth Cards ── */}
        <div className="flex-1 min-h-0 overflow-y-auto">
          {devices.length === 0 ? (
            <div className="flex items-center justify-center h-full min-h-[200px]">
              <div className="text-center text-slate-500">
                <Server className="w-14 h-14 mx-auto mb-3 opacity-30" />
                <p>No devices configured</p>
              </div>
            </div>
          ) : (
            <div className="grid gap-2 sm:gap-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}>
              {devices.map(d => {
                const glowStyle = getGlowStyle(d.alert_level, d.status);
                const isOffline = d.status === "offline";
                const hist = deviceBwHistory[d.id] || [];
                const latest = hist[hist.length - 1] || { dl: d.download_mbps || 0, ul: d.upload_mbps || 0 };
                const formatBw = (v) => {
                  if (!v) return "0";
                  if (v >= 1000) return `${(v / 1000).toFixed(1)}G`;
                  if (v >= 1) return `${v.toFixed(1)}M`;
                  return `${(v * 1000).toFixed(0)}K`;
                };
                const isp = d.isp_interfaces?.join(", ") || ""; // eslint-disable-line no-unused-vars

                return (
                  <div
                    key={d.id}
                    onClick={() => setSelectedDevice(d)}
                    className="relative rounded-xl border p-3 flex flex-col gap-2 transition-all duration-500 cursor-pointer hover:brightness-110 select-none"
                    style={{
                      background: "linear-gradient(135deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.01) 100%)",
                      backdropFilter: "blur(12px)",
                      ...glowStyle,
                    }}
                  >
                    {/* Header: name + status dot */}
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-bold text-white truncate leading-tight">{d.identity || d.name}</p>
                        <p className="text-[10px] text-slate-400 font-mono">{d.ip_address}</p>
                      </div>
                      <StatusBadge status={d.status} />
                    </div>

                    {/* Model + ROS version only */}
                    {d.model && (
                      <p className="text-[10px] text-slate-500 truncate">{d.model}{d.ros_version ? ` · v${d.ros_version}` : ""}</p>
                    )}

                    {!isOffline ? (
                      <>
                        {/* Metrics: CPU + MEM */}
                        <div className="space-y-1.5">
                          <div>
                            <div className="flex justify-between text-[10px] mb-0.5">
                              <span className="text-slate-400 flex items-center gap-1"><Cpu className="w-3 h-3" /> CPU</span>
                              <span className={`font-mono font-semibold ${d.cpu_load > 80 ? "text-red-400" : d.cpu_load > 60 ? "text-yellow-400" : "text-green-400"
                                }`}>{d.cpu_load}%</span>
                            </div>
                            <MetricBar value={d.cpu_load} color="#22c55e" />
                          </div>
                          <div>
                            <div className="flex justify-between text-[10px] mb-0.5">
                              <span className="text-slate-400 flex items-center gap-1"><HardDrive className="w-3 h-3" /> MEM</span>
                              <span className={`font-mono font-semibold ${d.memory_usage > 80 ? "text-red-400" : d.memory_usage > 60 ? "text-yellow-400" : "text-blue-400"
                                }`}>{d.memory_usage}%</span>
                            </div>
                            <MetricBar value={d.memory_usage} color="#3b82f6" />
                          </div>
                        </div>

                        {/* Footer: ping + DL + UL values */}
                        <div className="grid grid-cols-3 gap-1 pt-1.5 border-t border-white/10">
                          <div className="text-center">
                            <p className="text-[9px] text-slate-500 uppercase">Ping</p>
                            <p className={`text-[11px] font-mono font-bold ${d.ping_ms > 100 ? "text-red-400" : d.ping_ms > 50 ? "text-yellow-400" : "text-cyan-400"
                              }`}>{d.ping_ms > 0 ? `${d.ping_ms}ms` : "—"}</p>
                          </div>
                          <div className="text-center">
                            <p className="text-[9px] text-slate-500 flex items-center justify-center gap-0.5"><TrendingDown className="w-2.5 h-2.5" />DL</p>
                            <p className="text-[11px] font-mono font-bold text-blue-400">{formatBw(latest.dl)}</p>
                          </div>
                          <div className="text-center">
                            <p className="text-[9px] text-slate-500 flex items-center justify-center gap-0.5"><TrendingUp className="w-2.5 h-2.5" />UL</p>
                            <p className="text-[11px] font-mono font-bold text-green-400">{formatBw(latest.ul)}</p>
                          </div>
                        </div>

                        {/* PPPoE & Hotspot Active Badges */}
                        {(d.pppoe_active > 0 || d.hotspot_active > 0) && (
                          <div className="flex items-center gap-1.5 pt-1 border-t border-white/[0.06]">
                            {d.pppoe_active > 0 && (
                              <div className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-semibold font-mono"
                                style={{ background: "rgba(0,212,255,0.08)", border: "1px solid rgba(0,212,255,0.25)", color: "#00d4ff" }}>
                                <span>PPPoE</span>
                                <span className="font-bold">{d.pppoe_active.toLocaleString()}</span>
                              </div>
                            )}
                            {d.hotspot_active > 0 && (
                              <div className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-semibold font-mono"
                                style={{ background: "rgba(255,140,0,0.08)", border: "1px solid rgba(255,140,0,0.3)", color: "#ff8c00" }}>
                                <span>Hotspot</span>
                                <span className="font-bold">{d.hotspot_active.toLocaleString()}</span>
                              </div>
                            )}
                          </div>
                        )}

                        {/* ── ISP Interface Down Badges ── */}
                        {/* Tampil jika ada ISP interface dengan traffic < 1Mbps atau tidak terbaca */}
                        {d.isp_status?.some(isp => isp.is_down) && (
                          <div className="flex flex-wrap items-center gap-1.5 pt-1 border-t border-red-500/20">
                            {d.isp_status.filter(isp => isp.is_down).map(isp => (
                              <div
                                key={isp.name}
                                className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold font-mono animate-pulse"
                                style={{
                                  background: "rgba(239,68,68,0.15)",
                                  border: "1px solid rgba(239,68,68,0.5)",
                                  color: "#f87171",
                                }}
                                title={`${isp.name}: DL=${isp.download_mbps}Mbps UL=${isp.upload_mbps}Mbps`}
                              >
                                <svg className="w-3 h-3 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                                  <path d="M1 1l22 22M16.72 11.06A10.94 10.94 0 0 1 19 12.55M5 12.55a10.94 10.94 0 0 1 5.17-2.39M10.71 5.05A16 16 0 0 1 22.56 9M1.42 9a15.91 15.91 0 0 1 4.7-2.88M8.53 16.11a6 6 0 0 1 6.95 0M12 20h.01" />
                                </svg>
                                {/* Gunakan comment MikroTik sebagai label, fallback ke nama interface */}
                                <span>{(isp.comment || isp.name)} Down</span>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Embedded interface sparkline graph */}
                        {hist.length > 1 && (
                          <div className="h-16">
                            <ResponsiveContainer width="100%" height="100%">
                              <AreaChart data={hist} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
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
                                <Tooltip
                                  contentStyle={{ background: "#0f172a", border: "1px solid #1e3a5f", borderRadius: "6px", fontSize: "10px", padding: "4px 8px" }}
                                  formatter={(v, name) => [`${formatBw(v)}`, name === "dl" ? "↓ Download" : "↑ Upload"]}
                                  labelFormatter={() => ""}
                                />
                                <Area type="monotone" dataKey="dl" stroke="#3b82f6" fill={`url(#dl_${d.id})`} strokeWidth={1.5} dot={false} name="dl" />
                                <Area type="monotone" dataKey="ul" stroke="#22c55e" fill={`url(#ul_${d.id})`} strokeWidth={1.5} dot={false} name="ul" />
                              </AreaChart>
                            </ResponsiveContainer>
                          </div>
                        )}
                        {hist.length <= 1 && (
                          <div className="h-10 flex items-center justify-center">
                            <p className="text-[10px] text-slate-600 flex items-center gap-1"><RefreshCw className="w-3 h-3 animate-spin" style={{ animationDuration: "2s" }} /> Collecting data...</p>
                          </div>
                        )}
                      </>
                    ) : (
                      <div className="flex items-center justify-center py-4">
                        <WifiOff className="w-8 h-8 text-red-500/50" />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* ── Right Panel: Active Alerts only ── */}
        <div className="w-full lg:w-64 flex-shrink-0 flex flex-col gap-3 min-h-0">
          {/* Active Alerts */}
          <div
            className="rounded-xl border p-4 flex flex-col min-h-0"
            style={{
              background: "rgba(255,255,255,0.03)",
              borderColor: "rgba(99,179,237,0.2)",
            }}
          >
            <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-widest mb-3 flex items-center gap-2 flex-shrink-0">
              <AlertTriangle className="w-3.5 h-3.5 text-yellow-400" /> Active Alerts
            </h3>
            <div className="space-y-2 overflow-y-auto flex-1 pr-1 custom-scrollbar">
              {devices.filter(d => d.alert_level !== "normal").length === 0 ? (
                <div className="flex items-center gap-2 text-green-400 text-xs">
                  <CheckCircle2 className="w-4 h-4" /> All systems normal
                </div>
              ) : (
                devices
                  .filter(d => d.alert_level !== "normal")
                  .map(d => (
                    <div key={d.id} className={`flex items-start gap-2 p-2 rounded-lg text-xs ${d.alert_level === "critical" ? "bg-red-500/10 border border-red-500/20" : "bg-yellow-500/10 border border-yellow-500/20"
                      }`}>
                      {d.alert_level === "critical"
                        ? <WifiOff className="w-3.5 h-3.5 text-red-400 flex-shrink-0 mt-0.5" />
                        : <AlertTriangle className="w-3.5 h-3.5 text-yellow-400 flex-shrink-0 mt-0.5" />
                      }
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
          <div className="flex items-center justify-center gap-2 text-slate-600 text-[10px] flex-shrink-0">
            <RefreshCw className="w-3 h-3 animate-spin" style={{ animationDuration: "3s" }} />
            Auto-refresh every 5s
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
