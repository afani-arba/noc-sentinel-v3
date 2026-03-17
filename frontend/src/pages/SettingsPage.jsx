import { useState, useEffect } from "react";
import api from "@/lib/api";
import { Shield, Wifi, WifiOff, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

// ─── WireGuard Section ────────────────────────────────────────────────────────
function WireGuardSection() {
  const [cfg, setCfg] = useState({ enabled: false, private_key: "", client_ip: "", server_public_key: "", server_endpoint: "", allowed_ips: "0.0.0.0/0" });
  const [status, setStatus] = useState(null);
  const [saving, setSaving] = useState(false);
  const [showKey, setShowKey] = useState(false);

  useEffect(() => {
    api.get("/wireguard/config").then(r => setCfg(c => ({ ...c, ...r.data }))).catch(() => {});
    api.get("/wireguard/status").then(r => setStatus(r.data)).catch(() => {});
  }, []);

  const handleSave = async () => {
    if (cfg.enabled && (!cfg.private_key || !cfg.client_ip || !cfg.server_endpoint || !cfg.server_public_key)) {
      toast.error("Private Key, Client IP, Server Endpoint, dan Server Public Key wajib diisi jika Enable di-centang");
      return;
    }
    setSaving(true);
    try {
      const r = await api.put("/wireguard/config", cfg);
      toast.success(r.data.message);
      api.get("/wireguard/status").then(res => setStatus(res.data)).catch(() => {});
    } catch (e) { toast.error(e.response?.data?.detail || "Gagal menyimpan konfigurasi WireGuard"); }
    setSaving(false);
  };

  const isOnline = status?.status === "online";

  return (
    <div className="bg-card border border-border rounded-sm p-4 sm:p-6 space-y-4" data-testid="wireguard-section">
      <div className="flex items-start justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-sm bg-purple-500/10 flex items-center justify-center">
            <Shield className="w-4 h-4 text-purple-400" />
          </div>
          <div>
            <h2 className="text-base sm:text-lg font-semibold font-['Rajdhani']">WireGuard Client</h2>
            <p className="text-[10px] sm:text-xs text-muted-foreground">Koneksikan Server NOC-Sentinel ini ke MikroTik via WireGuard Tunnel</p>
          </div>
        </div>
        <div className={`flex items-center gap-1.5 px-2 py-1 rounded-sm text-[10px] font-medium border ${isOnline ? "bg-green-500/10 text-green-400 border-green-500/20" : "bg-secondary text-muted-foreground border-border"}`}>
          {isOnline ? <Wifi className="w-3 h-3 animate-pulse" /> : <WifiOff className="w-3 h-3" />}
          {isOnline ? "CONNECTED" : "DISCONNECTED"}
        </div>
      </div>

      <div className="flex items-center gap-2 p-3 rounded-sm bg-secondary/30 border border-border mb-4">
        <input 
          type="checkbox" 
          id="wg-enable" 
          checked={cfg.enabled} 
          onChange={(e) => setCfg(c => ({ ...c, enabled: e.target.checked }))}
          className="w-4 h-4 rounded-sm border-gray-300 text-purple-600 focus:ring-purple-600 bg-background"
        />
        <Label htmlFor="wg-enable" className="text-xs font-semibold cursor-pointer">Aktifkan WireGuard Client (wg0)</Label>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground flex gap-1 justify-between">
            <span>Private Key (VPS Linux Ini)</span>
            <span className="text-[10px] text-muted-foreground cursor-pointer hover:underline" onClick={() => setShowKey(!showKey)}>
              {showKey ? "Hide" : "Show"}
            </span>
          </Label>
          <Input type={showKey ? "text" : "password"} value={cfg.private_key} onChange={e => setCfg(c => ({ ...c, private_key: e.target.value }))}
            placeholder="Kunci Privat Host Linux Sentinel..." className="rounded-sm bg-background font-mono text-xs" />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Address / IP Client (wg0)</Label>
          <Input value={cfg.client_ip} onChange={e => setCfg(c => ({ ...c, client_ip: e.target.value }))}
            placeholder="10.10.10.2/24" className="rounded-sm bg-background font-mono text-xs" />
        </div>
        
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Server Public Key (MikroTik Hub)</Label>
          <Input value={cfg.server_public_key} onChange={e => setCfg(c => ({ ...c, server_public_key: e.target.value }))}
            placeholder="Kunci Publik Server MikroTik..." className="rounded-sm bg-background font-mono text-xs" />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Server Endpoint (IP Public MikroTik:Port)</Label>
          <Input value={cfg.server_endpoint} onChange={e => setCfg(c => ({ ...c, server_endpoint: e.target.value }))}
            placeholder="103.x.x.x:13231" className="rounded-sm bg-background font-mono text-xs" />
        </div>
        
        <div className="sm:col-span-2 space-y-1.5">
          <Label className="text-xs text-muted-foreground">Allowed IPs (Routing)</Label>
          <Input value={cfg.allowed_ips} onChange={e => setCfg(c => ({ ...c, allowed_ips: e.target.value }))}
            placeholder="0.0.0.0/0, ::/0" className="rounded-sm bg-background font-mono text-xs" />
          <p className="text-[10px] text-muted-foreground">Contoh: 0.0.0.0/0 (Semua traffic ke WireGuard) atau 10.10.10.0/24 (Hanya traffic IP Tunneling)</p>
        </div>
      </div>

      <div className="flex gap-2 pt-2 border-t border-border/50">
        <Button onClick={handleSave} disabled={saving} size="sm" className="rounded-sm gap-2 bg-purple-600 hover:bg-purple-700 text-white">
          <Save className="w-3.5 h-3.5" /> {saving ? "Menyimpan dan Mengkonfigurasi wg0..." : "Simpan & Terapkan"}
        </Button>
      </div>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────
export default function SettingsPage() {
  return (
    <div className="space-y-4 pb-16" data-testid="settings-page">
      <div>
        <h1 className="text-xl sm:text-2xl md:text-3xl font-bold font-['Rajdhani'] tracking-tight">Pengaturan</h1>
        <p className="text-xs sm:text-sm text-muted-foreground">Pengaturan sistem NOC-Sentinel</p>
      </div>

      {/* WireGuard Section */}
      <WireGuardSection />
    </div>
  );
}
