import { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/App";
import api from "@/lib/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Cpu, RefreshCw, Search, RotateCcw, AlertTriangle, CheckCircle2,
  Clock, Wifi, WifiOff, Zap, Settings, ChevronRight, Trash2,
  LinkIcon, TriangleAlert
} from "lucide-react";

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(isoStr) {
  if (!isoStr) return "—";
  const diff = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
  if (diff < 60) return `${diff}d lalu`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m lalu`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}j lalu`;
  return `${Math.floor(diff / 86400)}h lalu`;
}

// ── Stats Bar ─────────────────────────────────────────────────────────────────

function StatsBar({ stats, loading }) {
  const items = [
    { label: "Total CPE", value: stats?.total ?? "—", color: "text-foreground" },
    { label: "Online", value: stats?.online ?? "—", color: "text-green-400" },
    { label: "Offline", value: stats?.offline ?? "—", color: "text-red-400" },
    { label: "Faults", value: stats?.faults ?? "—", color: "text-yellow-400" },
  ];
  return (
    <div className="flex flex-wrap gap-3">
      {items.map((s) => (
        <div key={s.label} className="bg-secondary/30 border border-border rounded-sm px-4 py-2 flex flex-col items-center min-w-[80px]">
          <span className={`text-xl font-bold font-mono ${s.color} ${loading ? "animate-pulse" : ""}`}>{s.value}</span>
          <span className="text-[10px] text-muted-foreground uppercase tracking-wider">{s.label}</span>
        </div>
      ))}
    </div>
  );
}

// ── Device Row ────────────────────────────────────────────────────────────────

function DeviceRow({ device, onAction, isAdmin }) {
  const [acting, setActing] = useState(null);

  const doAction = async (action, label) => {
    setActing(action);
    try {
      await api.post(`/genieacs/devices/${encodeURIComponent(device.id)}/${action}`);
      toast.success(`${label} dikirim ke ${device.model || device.id}`);
    } catch (e) {
      toast.error(e.response?.data?.detail || `${label} gagal`);
    }
    setActing(null);
  };

  return (
    <tr className="border-b border-border/30 hover:bg-secondary/20 transition-colors">
      <td className="px-3 py-2.5">
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full flex-shrink-0 ${device.online ? "bg-green-500 animate-pulse" : "bg-red-500"}`} />
          <div>
            <p className="text-xs font-mono text-foreground truncate max-w-[200px]" title={device.id}>{device.id}</p>
            <p className="text-[10px] text-muted-foreground">{device.serial || "—"}</p>
          </div>
        </div>
      </td>
      <td className="px-3 py-2.5 text-xs">
        <p className="text-foreground font-medium">{device.manufacturer || "—"}</p>
        <p className="text-muted-foreground">{device.model || "—"}</p>
      </td>
      <td className="px-3 py-2.5 text-xs font-mono text-muted-foreground">{device.ip || "—"}</td>
      <td className="px-3 py-2.5 text-[10px] text-muted-foreground font-mono">{device.firmware || "—"}</td>
      <td className="px-3 py-2.5 text-[10px] text-muted-foreground">{timeAgo(device.last_inform)}</td>
      <td className="px-3 py-2.5">
        <Badge variant="outline" className={`text-[10px] rounded-sm ${device.online ? "border-green-500/40 text-green-400" : "border-red-500/40 text-red-400"}`}>
          {device.online ? <><Wifi className="w-2.5 h-2.5 mr-1" />Online</> : <><WifiOff className="w-2.5 h-2.5 mr-1" />Offline</>}
        </Badge>
      </td>
      {isAdmin && (
        <td className="px-3 py-2.5">
          <div className="flex gap-1">
            <Button size="icon" variant="ghost" className="h-6 w-6" title="Reboot"
              disabled={acting !== null}
              onClick={() => doAction("reboot", "Reboot")}>
              <RotateCcw className={`w-3 h-3 ${acting === "reboot" ? "animate-spin" : ""}`} />
            </Button>
            <Button size="icon" variant="ghost" className="h-6 w-6" title="Refresh Parameter"
              disabled={acting !== null}
              onClick={() => doAction("refresh", "Refresh")}>
              <RefreshCw className={`w-3 h-3 ${acting === "refresh" ? "animate-spin" : ""}`} />
            </Button>
          </div>
        </td>
      )}
    </tr>
  );
}

// ── Faults Tab ────────────────────────────────────────────────────────────────

function FaultsTab() {
  const [faults, setFaults] = useState([]);
  const [loading, setLoading] = useState(false);
  const { user } = useAuth();
  const isAdmin = user?.role === "administrator";

  useEffect(() => {
    setLoading(true);
    api.get("/genieacs/faults").then(r => setFaults(r.data)).catch(() => toast.error("Gagal memuat faults")).finally(() => setLoading(false));
  }, []);

  const deleteFault = async (id) => {
    try {
      await api.delete(`/genieacs/faults/${encodeURIComponent(id)}`);
      setFaults(f => f.filter(x => x._id !== id));
      toast.success("Fault dihapus");
    } catch { toast.error("Gagal hapus fault"); }
  };

  return (
    <div>
      {loading && <p className="text-muted-foreground text-sm py-4 text-center animate-pulse">Memuat faults...</p>}
      {!loading && faults.length === 0 && (
        <div className="text-center py-12">
          <CheckCircle2 className="w-10 h-10 text-green-500 mx-auto mb-2" />
          <p className="text-muted-foreground text-sm">Tidak ada fault aktif 🎉</p>
        </div>
      )}
      {faults.length > 0 && (
        <div className="space-y-2">
          {faults.map(f => (
            <div key={f._id} className="flex items-start gap-3 p-3 bg-red-500/5 border border-red-500/20 rounded-sm">
              <TriangleAlert className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-mono text-foreground truncate">{f.device || f._id}</p>
                <p className="text-[10px] text-red-400 mt-0.5">{f.code || ""} — {f.message || JSON.stringify(f).slice(0, 80)}</p>
                <p className="text-[10px] text-muted-foreground mt-0.5">{timeAgo(f.timestamp)}</p>
              </div>
              {isAdmin && (
                <Button size="icon" variant="ghost" className="h-6 w-6 flex-shrink-0" onClick={() => deleteFault(f._id)}>
                  <Trash2 className="w-3 h-3 text-red-400" />
                </Button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Connection Test ───────────────────────────────────────────────────────────

function ConnectionTest() {
  const [result, setResult] = useState(null);
  const [testing, setTesting] = useState(false);

  const test = async () => {
    setTesting(true);
    try {
      const r = await api.get("/genieacs/test-connection");
      setResult(r.data);
    } catch (e) {
      setResult({ success: false, error: e.response?.data?.detail || e.message });
    }
    setTesting(false);
  };

  return (
    <div className="flex items-center gap-3 p-3 bg-secondary/20 border border-border rounded-sm">
      <LinkIcon className="w-4 h-4 text-muted-foreground flex-shrink-0" />
      <div className="flex-1">
        {result ? (
          <p className={`text-xs ${result.success ? "text-green-400" : "text-red-400"}`}>
            {result.success ? <><CheckCircle2 className="inline w-3 h-3 mr-1" />{result.message}</> : <><AlertTriangle className="inline w-3 h-3 mr-1" />{result.error}</>}
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">Klik untuk test koneksi ke GenieACS</p>
        )}
      </div>
      <Button size="sm" variant="outline" className="rounded-sm h-7 text-xs gap-1" onClick={test} disabled={testing}>
        <Zap className="w-3 h-3" />{testing ? "Testing..." : "Test"}
      </Button>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function GenieACSPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "administrator";

  const [tab, setTab] = useState("devices");
  const [devices, setDevices] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");

  const fetchDevices = useCallback(async () => {
    setLoading(true);
    try {
      const [devRes, statsRes] = await Promise.all([
        api.get("/genieacs/devices", { params: { limit: 300, search } }),
        api.get("/genieacs/stats"),
      ]);
      setDevices(devRes.data);
      setStats(statsRes.data);
    } catch (e) {
      const msg = e.response?.data?.detail || "Gagal terhubung ke GenieACS";
      toast.error(msg);
    }
    setLoading(false);
  }, [search]);

  useEffect(() => { fetchDevices(); }, [fetchDevices]);

  const handleSearch = (e) => {
    e.preventDefault();
    setSearch(searchInput.trim());
  };

  const tabs = [
    { id: "devices", label: "CPE Devices", icon: Cpu },
    { id: "faults", label: "Faults", icon: AlertTriangle },
  ];

  return (
    <div className="space-y-4 pb-16">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold font-['Rajdhani'] tracking-tight flex items-center gap-2">
            <Cpu className="w-6 h-6 text-primary" /> GenieACS / TR-069
          </h1>
          <p className="text-xs text-muted-foreground">Manajemen CPE (modem/router pelanggan) via protocol TR-069</p>
        </div>
        <Button variant="outline" size="sm" className="rounded-sm gap-2 self-start" onClick={fetchDevices} disabled={loading}>
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {/* Connection test */}
      <ConnectionTest />

      {/* Stats */}
      <StatsBar stats={stats} loading={loading} />

      {/* Tabs */}
      <div className="flex border-b border-border gap-1">
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 px-4 py-2 text-sm border-b-2 transition-colors ${
              tab === t.id ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"
            }`}>
            <t.icon className="w-3.5 h-3.5" />
            {t.label}
            {t.id === "faults" && stats?.faults > 0 && (
              <span className="ml-1 bg-red-500/20 text-red-400 text-[10px] px-1.5 py-0.5 rounded-full font-mono">{stats.faults}</span>
            )}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="bg-card border border-border rounded-sm p-4">
        {tab === "devices" && (
          <>
            {/* Search */}
            <form onSubmit={handleSearch} className="flex gap-2 mb-4">
              <div className="relative flex-1">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
                <Input value={searchInput} onChange={e => setSearchInput(e.target.value)}
                  placeholder="Cari ID, model, IP, serial..." className="pl-8 h-8 rounded-sm text-xs" />
              </div>
              <Button type="submit" size="sm" className="rounded-sm h-8 text-xs">Cari</Button>
              {search && (
                <Button type="button" size="sm" variant="outline" className="rounded-sm h-8 text-xs"
                  onClick={() => { setSearch(""); setSearchInput(""); }}>Reset</Button>
              )}
            </form>

            {/* Table */}
            {loading ? (
              <p className="text-muted-foreground text-sm text-center py-8 animate-pulse">Memuat perangkat...</p>
            ) : devices.length === 0 ? (
              <div className="text-center py-12">
                <Cpu className="w-10 h-10 text-muted-foreground/30 mx-auto mb-3" />
                <p className="text-muted-foreground text-sm">Tidak ada perangkat ditemukan</p>
                <p className="text-[11px] text-muted-foreground/60 mt-1">Pastikan GenieACS terhubung dan GENIEACS_URL sudah dikonfigurasi</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left min-w-[700px]">
                  <thead>
                    <tr className="border-b border-border">
                      {["Device ID / Serial", "Produsen / Model", "IP Address", "Firmware", "Terakhir Aktif", "Status", isAdmin ? "Aksi" : ""].map(h => (
                        <th key={h} className="px-3 py-2 text-[10px] text-muted-foreground uppercase tracking-wider font-medium">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {devices.map(d => (
                      <DeviceRow key={d.id} device={d} isAdmin={isAdmin} />
                    ))}
                  </tbody>
                </table>
                <p className="text-[10px] text-muted-foreground mt-3 text-right font-mono">
                  Menampilkan {devices.length} perangkat
                </p>
              </div>
            )}
          </>
        )}

        {tab === "faults" && <FaultsTab />}
      </div>

      {/* Config reminder */}
      <div className="p-3 bg-secondary/10 border border-dashed border-border rounded-sm">
        <p className="text-[10px] text-muted-foreground">
          <strong>Konfigurasi:</strong> Set <code className="bg-secondary px-1 rounded">GENIEACS_URL</code>, <code className="bg-secondary px-1 rounded">GENIEACS_USERNAME</code>, dan <code className="bg-secondary px-1 rounded">GENIEACS_PASSWORD</code> di file <code className="bg-secondary px-1 rounded">/opt/noc-sentinel/backend/.env</code> lalu restart backend.
        </p>
      </div>
    </div>
  );
}
