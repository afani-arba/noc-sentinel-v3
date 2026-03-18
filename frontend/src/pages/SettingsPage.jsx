import { useState, useEffect } from "react";
import api from "@/lib/api";
import { Shield, Wifi, WifiOff, Save, Info, RefreshCw, Palette } from "lucide-react";
import { useTheme } from "@/context/ThemeContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

// ─── WireGuard Section ────────────────────────────────────────────────────────
function WireGuardSection() {
  const [cfg, setCfg] = useState({ enabled: false, private_key: "", local_public_key: "", client_ip: "", server_public_key: "", server_endpoint: "", allowed_ips: "0.0.0.0/0" });
  const [status, setStatus] = useState(null);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
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

  const handleGenerate = async () => {
    if (!confirm("Buat kunci baru? Peringatan: Anda harus menyesuaikan Public Key di Mikrotik nanti.")) return;
    setGenerating(true);
    try {
      const { data } = await api.get("/wireguard/generate-keys");
      setCfg(c => ({ ...c, private_key: data.private_key, local_public_key: data.public_key }));
      toast.success("Kunci berhasil dibuat! Jangan lupa Simpan & Terapkan.");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Gagal membuat kunci.");
    }
    setGenerating(false);
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
          <div className="flex gap-2">
            <Input type={showKey ? "text" : "password"} value={cfg.private_key} onChange={e => setCfg(c => ({ ...c, private_key: e.target.value }))}
              placeholder="Kunci Privat Host Linux Sentinel..." className="rounded-sm bg-background font-mono text-xs" />
            <Button type="button" variant="outline" size="icon" disabled={generating} onClick={handleGenerate} className="w-9 h-9 flex-shrink-0 bg-secondary hover:bg-muted" title="Generate Private/Public Key otomatis">
              <RefreshCw className={`w-4 h-4 text-purple-400 ${generating ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground flex justify-between">
            <span>Public Key Host Linux (wg0)</span>
            <span className="text-[10px] text-purple-400">Dibuat otomatis dari Private Key</span>
          </Label>
          <div className="flex gap-2">
            <Input value={cfg.local_public_key || "Belum tersedia..."} disabled className="rounded-sm bg-background/50 font-mono text-xs text-muted-foreground" />
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="w-9 h-9 flex-shrink-0"
              onClick={() => {
                if (cfg.local_public_key) {
                  navigator.clipboard.writeText(cfg.local_public_key);
                  toast.success("Public Key disalin ke clipboard!");
                }
              }}
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
            </Button>
          </div>
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

      {/* Tutorial Section */}
      <div className="mt-6 pt-4 border-t border-border/30">
        <div className="flex items-center gap-2 mb-3">
          <Info className="w-4 h-4 text-purple-400" />
          <h3 className="text-sm font-semibold text-slate-200">Cara Setting di MikroTik RouterOS</h3>
        </div>
        <div className="text-xs text-muted-foreground mb-4">
          Agar server NOC-Sentinel dapat terhubung ke MikroTik via WireGuard, terapkan konfigurasi berikut pada Terminal MikroTik (Hub Utama / VPN Server).
        </div>
        <div className="bg-black/40 border border-white/10 rounded-md p-3 font-mono text-[10px] sm:text-xs text-green-400/90 overflow-x-auto whitespace-pre space-y-2">
          <p className="text-slate-500"># 1. Buat interface WireGuard di MikroTik (Port menyesuaikan Endpoint)</p>
          <p>/interface wireguard add name=wireguard1 listen-port=13231</p>
          
          <p className="text-slate-500 mt-2"># 2. Tambahkan IP Address untuk MikroTik (gateway VPN)</p>
          <p>/ip address add address=10.10.10.1/24 interface=wireguard1</p>

          <p className="text-slate-500 mt-2"># 3. Tambahkan Peer NOC-Sentinel (Gunakan Public Key Host Linux di atas)</p>
          <p>
            /interface wireguard peers add interface=wireguard1 \ <br/>
            {"  "}public-key="{cfg.local_public_key || "<PUBLIC_KEY_LINUX>"}" \ <br/>
            {"  "}allowed-address={cfg.client_ip ? cfg.client_ip.split('/')[0] + "/32" : "10.10.10.2/32"}
          </p>

          <p className="text-slate-500 mt-2"># 4. Pastikan Firewall mengizinkan akses port UDP WireGuard</p>
          <p>/ip firewall filter add chain=input protocol=udp dst-port=13231 action=accept place-before=1</p>
        </div>
      </div>
    </div>
  );
}

// ─── Theme Section ────────────────────────────────────────────────────────
function ThemeSection() {
  const { theme, setTheme } = useTheme();

  return (
    <div className="bg-card border border-border rounded-sm p-4 sm:p-6 space-y-4" data-testid="theme-section">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-sm bg-blue-500/10 flex items-center justify-center">
          <Palette className="w-4 h-4 text-blue-400" />
        </div>
        <div>
          <h2 className="text-base sm:text-lg font-semibold font-['Rajdhani']">Tampilan (Global Theme)</h2>
          <p className="text-[10px] sm:text-xs text-muted-foreground">Pilih tema antarmuka NOC Sentinel Anda</p>
        </div>
      </div>

      <div className="flex flex-col sm:flex-row gap-4 pt-2">
        <button
          onClick={() => setTheme('classic')}
          className={`flex-1 p-3 rounded-sm border text-left transition-all ${
            theme === 'classic' ? 'border-primary bg-primary/10' : 'border-border bg-secondary/30 hover:border-primary/50'
          }`}
        >
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">Tema Classic</h3>
            {theme === 'classic' && <div className="w-2 h-2 rounded-full bg-primary" />}
          </div>
          <p className="text-xs text-muted-foreground mt-1">Tampilan clean dark dan profesional (Bawaan).</p>
        </button>

        <button
          onClick={() => setTheme('neon')}
          className={`flex-1 p-3 rounded-sm border text-left transition-all ${
            theme === 'neon' ? 'border-cyan-500 bg-cyan-500/10' : 'border-border bg-secondary/30 hover:border-cyan-500/50'
          }`}
        >
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-cyan-400">Tema Neon v4</h3>
            {theme === 'neon' && <div className="w-2 h-2 rounded-full bg-cyan-400 shadow-[0_0_8px_rgba(34,211,238,0.8)]" />}
          </div>
          <p className="text-xs text-muted-foreground mt-1">Dark mode dengan warna neon cyber futuristik.</p>
        </button>
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

      {/* Theme Section */}
      <ThemeSection />

      {/* WireGuard Section */}
      <WireGuardSection />
    </div>
  );
}
