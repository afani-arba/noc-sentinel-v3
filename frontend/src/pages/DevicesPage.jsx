import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { useAuth } from "@/App";
import { Plus, Trash2, Server, Wifi, WifiOff, Pencil, Zap, Monitor, Radio, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";

export default function DevicesPage() {
  const navigate = useNavigate();
  const { snmpEnabled } = useAuth(); // null=belum dicek, true=OK, false=belum install
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [testing, setTesting] = useState("");
  const [form, setForm] = useState({
    name: "", ip_address: "", winbox_address: "",
    api_mode: "rest", api_username: "admin", api_password: "",
    api_port: "", use_https: false, api_ssl: true, api_plaintext_login: true,
    description: "", snmp_community: "public", snmp_version: "2c",
  });

  const fetchDevices = useCallback(async () => {
    try {
      const r = await api.get("/devices");
      setDevices(r.data);
    } catch (e) { toast.error("Failed to fetch devices"); }
    setLoading(false);
  }, []);

  useEffect(() => { fetchDevices(); }, [fetchDevices]);

  const openAdd = () => {
    setEditing(null);
    setForm({ name: "", ip_address: "", winbox_address: "", api_mode: "rest", api_username: "admin", api_password: "", api_port: "", use_https: false, api_ssl: true, api_plaintext_login: true, description: "", snmp_community: "public", snmp_version: "2c" });
    setDialogOpen(true);
  };

  const openEdit = (d) => {
    setEditing(d);
    setForm({
      name: d.name, ip_address: d.ip_address || "",
      winbox_address: d.winbox_address || "",
      api_mode: d.api_mode || "rest", api_username: d.api_username || "admin", api_password: "",
      api_port: d.api_port || "",
      use_https: d.use_https || false,
      api_ssl: d.api_ssl !== undefined ? d.api_ssl : true,
      api_plaintext_login: d.api_plaintext_login !== undefined ? d.api_plaintext_login : true,
      description: d.description || "",
      snmp_community: d.snmp_community || "public",
      snmp_version: d.snmp_version || "2c",
    });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    try {
      const apiPort = form.api_port ? parseInt(form.api_port) : null;
      const data = { ...form, api_port: apiPort, use_https: form.use_https };
      // winbox_address: kirim null jika kosong (bukan string kosong)
      if (!data.winbox_address || !data.winbox_address.trim()) data.winbox_address = null;
      else data.winbox_address = data.winbox_address.trim();
      if (editing) {
        if (!data.api_password) delete data.api_password;
        await api.put(`/devices/${editing.id}`, data);
        toast.success("Device updated");
      } else {
        await api.post("/devices", data);
        toast.success("Device added & polling started");
      }
      setDialogOpen(false);
      fetchDevices();
    } catch (e) { toast.error(e.response?.data?.detail || "Failed"); }
  };

  const handleDelete = async (id, name) => {
    if (!window.confirm(`Delete device "${name}"?`)) return;
    try {
      await api.delete(`/devices/${id}`);
      toast.success("Device deleted");
      fetchDevices();
    } catch (e) { toast.error(e.response?.data?.detail || "Failed"); }
  };

  const handleTestApi = async (id) => {
    setTesting(id + "_api");
    try {
      const r = await api.post(`/devices/${id}/test-api`);
      if (r.data.success) {
        toast.success(`API OK — Identity: ${r.data.identity}`);
      } else {
        toast.error(`API Failed: ${r.data.error || "connection error"}`);
      }
    } catch (e) { toast.error("API test failed"); }
    setTesting("");
  };

  const handleTestSnmp = async (id) => {
    setTesting(id + "_snmp");
    try {
      const r = await api.get(`/devices/${id}/test-snmp`);
      if (r.data.success) {
        toast.success(r.data.message, {
          description: r.data.sys_descr ? r.data.sys_descr.substring(0, 80) : undefined,
          duration: 6000,
        });
      } else {
        toast.error(`SNMP Gagal: ${r.data.error}`, { duration: 8000 });
      }
    } catch (e) { toast.error("SNMP test error: " + (e.response?.data?.detail || e.message)); }
    setTesting("");
  };

  const handlePoll = async (id) => {
    setTesting(id + "_poll");
    try {
      const r = await api.post(`/devices/${id}/poll`);
      toast.success(r.data.reachable ? "Poll OK — device online" : "Poll completed — device offline");
      fetchDevices();
    } catch (e) { toast.error("Poll failed"); }
    setTesting("");
  };

  return (
    <div className="space-y-4 pb-16" data-testid="devices-page">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl md:text-3xl font-bold font-['Rajdhani'] tracking-tight">Devices</h1>
          <p className="text-xs sm:text-sm text-muted-foreground">Manage MikroTik devices — polling via REST API</p>
        </div>
        <div className="flex gap-2">
          <Button onClick={openAdd} size="sm" className="rounded-sm gap-2" data-testid="add-device-btn"><Plus className="w-4 h-4" /> <span className="hidden sm:inline">Add Device</span></Button>
        </div>
      </div>

      {/* SNMP Status Banner — hanya tampil jika backend konfirmasi pysnmp BELUM terinstall */}
      {snmpEnabled === false && (
        <div className="flex items-start gap-3 p-3 rounded-sm border border-yellow-500/30 bg-yellow-500/5 text-yellow-400" role="alert">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <div className="text-xs leading-relaxed">
            <span className="font-semibold">SNMP Hybrid Monitoring tidak aktif</span>
            {" — "}
            <code className="bg-yellow-500/10 px-1 rounded">pysnmp-lextudio</code> belum terinstall di server.
            {" "}
            Jalankan <code className="bg-yellow-500/10 px-1 rounded">sudo noc-update</code> untuk install otomatis.
            Bandwidth monitoring menggunakan API fallback.
          </div>
        </div>
      )}

      {loading ? (
        <div className="text-center text-muted-foreground py-12 text-sm">Loading devices...</div>
      ) : devices.length === 0 ? (
        <div className="bg-card border border-border rounded-sm p-8 sm:p-12 text-center"><Server className="w-10 h-10 sm:w-12 sm:h-12 mx-auto mb-3 text-muted-foreground/30" /><p className="text-sm text-muted-foreground">No devices configured</p></div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 sm:gap-4">
          {devices.map(d => (
            <div key={d.id} className="bg-card border border-border rounded-sm p-3 sm:p-5 transition-all hover:border-border/80" data-testid={`device-card-${d.name}`}>
              <div className="flex items-start justify-between mb-3 sm:mb-4">
                <div className="flex items-center gap-2 sm:gap-3">
                  <div className={`w-8 h-8 sm:w-10 sm:h-10 rounded-sm flex items-center justify-center ${d.status==="online"?"bg-green-500/10":"bg-red-500/10"}`}>
                    {d.status==="online"?<Wifi className="w-4 h-4 sm:w-5 sm:h-5 text-green-500" />:<WifiOff className="w-4 h-4 sm:w-5 sm:h-5 text-red-500" />}
                  </div>
                  <div><h3 className="text-xs sm:text-sm font-semibold">{d.name}</h3><p className="text-[10px] sm:text-xs text-muted-foreground font-mono">{d.ip_address}</p></div>
                </div>
                <Badge className={`rounded-sm text-[10px] sm:text-xs border ${d.status==="online"?"bg-green-500/10 text-green-500 border-green-500/20":"bg-red-500/10 text-red-500 border-red-500/20"}`}>{d.status || "?"}</Badge>
              </div>
              <div className="space-y-1.5 sm:space-y-2 text-[10px] sm:text-xs">
                <div className="flex justify-between"><span className="text-muted-foreground">API Mode</span><Badge variant="outline" className="rounded-sm text-[10px]">{d.api_mode === "api" ? "ROS6" : "ROS7"}</Badge></div>
                {d.ros_version && <div className="flex justify-between"><span className="text-muted-foreground">RouterOS</span><span className="font-mono">v{d.ros_version}</span></div>}
                {d.uptime && <div className="flex justify-between"><span className="text-muted-foreground">Uptime</span><span className="font-mono text-[10px]">{d.uptime}</span></div>}
                {typeof d.cpu_load === "number" && d.status === "online" && (
                  <div className="flex justify-between items-center"><span className="text-muted-foreground">CPU</span><div className="flex items-center gap-2"><div className="w-12 sm:w-16 h-1.5 bg-secondary rounded-full overflow-hidden"><div className="h-full rounded-full" style={{ width:`${d.cpu_load}%`, backgroundColor:d.cpu_load>80?"#ef4444":d.cpu_load>50?"#f59e0b":"#10b981" }} /></div><span className="font-mono w-6 sm:w-8 text-right">{d.cpu_load}%</span></div></div>
                )}
              </div>
              <div className="mt-3 sm:mt-4 pt-2 sm:pt-3 border-t border-border/50 flex flex-wrap gap-1">
                <Button variant="outline" size="sm" className="text-[10px] sm:text-xs gap-1 h-6 sm:h-7 rounded-sm px-2" onClick={() => handleTestApi(d.id)} disabled={testing===d.id+"_api"} data-testid={`test-api-${d.name}`}>
                  <Zap className="w-3 h-3" />{testing===d.id+"_api"?"...":"Test API"}
                </Button>
                <Button variant="outline" size="sm" className="text-[10px] sm:text-xs gap-1 h-6 sm:h-7 rounded-sm px-2 text-cyan-500 border-cyan-500/30 hover:bg-cyan-500/10" onClick={() => handleTestSnmp(d.id)} disabled={testing===d.id+"_snmp"} data-testid={`test-snmp-${d.name}`}>
                  <Radio className="w-3 h-3" />{testing===d.id+"_snmp"?"...":"SNMP"}
                </Button>
                <Button variant="outline" size="sm" className="text-[10px] sm:text-xs gap-1 h-6 sm:h-7 rounded-sm px-2 text-primary border-primary/30 hover:bg-primary/10" onClick={() => navigate(`/devices/${d.id}`)} data-testid={`detail-device-${d.name}`}>
                  <Zap className="w-3 h-3" />Detail
                </Button>
                <Button variant="ghost" size="sm" className="text-[10px] sm:text-xs gap-1 h-6 sm:h-7 rounded-sm px-2" onClick={() => openEdit(d)} data-testid={`edit-device-${d.name}`}><Pencil className="w-3 h-3" /></Button>
                <Button variant="ghost" size="sm" className="text-[10px] sm:text-xs gap-1 h-6 sm:h-7 rounded-sm px-2 text-destructive" onClick={() => handleDelete(d.id, d.name)} data-testid={`delete-device-${d.name}`}><Trash2 className="w-3 h-3" /></Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="rounded-sm bg-card border-border max-w-lg max-h-[90vh] overflow-y-auto" data-testid="device-dialog">
          <DialogHeader>
            <DialogTitle className="font-['Rajdhani'] text-xl">{editing?"Edit Device":"Add Device"}</DialogTitle>
            <DialogDescription>Configure MikroTik device with REST API access (ROS 7+) or API Protocol (ROS 6+).</DialogDescription>
          </DialogHeader>
          <div className="space-y-5">
            <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Device Name</Label>
              <Input value={form.name} onChange={e => setForm({...form, name:e.target.value})} className="rounded-sm bg-background" placeholder="Router-Core-01" data-testid="device-form-name" /></div>
            <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">IP Address <span className="text-muted-foreground/50">(untuk API / polling)</span></Label>
              <Input value={form.ip_address} onChange={e => setForm({...form, ip_address:e.target.value})} className="rounded-sm bg-background font-mono text-xs" placeholder="192.168.1.1" data-testid="device-form-ip" /></div>

            {/* Winbox Remote Address */}
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground flex items-center gap-1.5">
                <Monitor className="w-3 h-3" />
                Alamat Winbox Remote
                <span className="text-muted-foreground/40 font-normal">(opsional)</span>
              </Label>
              <Input
                value={form.winbox_address}
                onChange={e => setForm({...form, winbox_address: e.target.value})}
                className="rounded-sm bg-background font-mono text-xs"
                placeholder="IP publik / DDNS — contoh: 203.0.113.5 atau my-router.dyndns.org"
                data-testid="device-form-winbox-address"
              />
              <p className="text-[10px] text-muted-foreground/60">
                Kosongkan jika Winbox diakses melalui IP yang sama dengan API. Isi jika MikroTik
                berada di balik NAT atau memiliki IP publik/DDNS yang berbeda.
              </p>
            </div>

            {/* MikroTik API Section */}
            <div className="border border-border/50 rounded-sm p-3 space-y-3">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1">
                <Zap className="w-3 h-3" /> MikroTik API
              </p>

              {/* API Mode Selector */}
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">API Mode (RouterOS Version)</Label>
                <Select
                  value={form.api_mode}
                  onValueChange={v => setForm({...form, api_mode: v})}
                >
                  <SelectTrigger className="rounded-sm bg-background text-xs" data-testid="device-form-api-mode">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="rest">REST API (RouterOS 7.1+)</SelectItem>
                    <SelectItem value="api">API Protocol (RouterOS 6.x+)</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-[10px] text-muted-foreground/70">
                  {form.api_mode === "api"
                    ? "Untuk RouterOS versi 6.x — menggunakan port 8728/8729"
                    : "Untuk RouterOS versi 7.1+ — menggunakan REST API di port 443/80"}
                </p>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">API Username</Label>
                  <Input value={form.api_username} onChange={e => setForm({...form, api_username:e.target.value})} className="rounded-sm bg-background" data-testid="device-form-api-username" /></div>
                <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">API Password</Label>
                  <Input type="password" value={form.api_password} onChange={e => setForm({...form, api_password:e.target.value})} className="rounded-sm bg-background" placeholder={editing?"(unchanged)":""} data-testid="device-form-api-password" /></div>
              </div>

              {/* Port Configuration */}
              {form.api_mode === "api" ? (
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">API Port (RouterOS 6)</Label>
                  <Input
                    type="number"
                    value={form.api_port}
                    onChange={e => setForm({...form, api_port:e.target.value})}
                    className="rounded-sm bg-background font-mono text-xs"
                    placeholder={form.api_ssl ? "8729 (SSL, kosong = default)" : "8728 (kosong = default)"}
                    data-testid="device-form-api-port"
                  />
                  <p className="text-[10px] text-muted-foreground/70">
                    Kosongkan untuk port default ({form.api_ssl ? "8729" : "8728"}). Isi jika port sudah diganti di IP › Services.
                  </p>
                  <div className="flex items-center gap-2 pt-1">
                    <Label className="text-xs text-muted-foreground">SSL/Encrypted</Label>
                    <Select value={form.api_ssl ? "true" : "false"} onValueChange={v => setForm({...form, api_ssl: v === "true"})}>
                      <SelectTrigger className="rounded-sm bg-background text-xs h-8 w-32" data-testid="device-form-api-ssl">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="false">Plain (8728)</SelectItem>
                        <SelectItem value="true">SSL (8729)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label className="text-xs text-muted-foreground">Protokol</Label>
                      <Select value={form.use_https ? "https" : "http"} onValueChange={v => setForm({...form, use_https: v === "https"})}>
                        <SelectTrigger className="rounded-sm bg-background text-xs" data-testid="device-form-protocol">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="http">HTTP (www)</SelectItem>
                          <SelectItem value="https">HTTPS (www-ssl)</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs text-muted-foreground">WWW Port</Label>
                      <Input
                        type="number"
                        value={form.api_port}
                        onChange={e => setForm({...form, api_port:e.target.value})}
                        className="rounded-sm bg-background font-mono text-xs"
                        placeholder={form.use_https ? "443 (kosong = default)" : "80 (kosong = default)"}
                        data-testid="device-form-api-port"
                      />
                    </div>
                  </div>
                  <p className="text-[10px] text-muted-foreground/70">
                    Kosongkan port untuk menggunakan default ({form.use_https ? "443" : "80"}). Isi jika port {form.use_https ? "www-ssl" : "www"} di IP › Services sudah diubah.
                  </p>
                </div>
              )}
            </div>
            <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Description</Label>
              <Input value={form.description} onChange={e => setForm({...form, description:e.target.value})} className="rounded-sm bg-background" data-testid="device-form-description" /></div>

            {/* SNMP Section */}
            <div className="border border-border/50 rounded-sm p-3 space-y-3">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1">
                <Radio className="w-3 h-3" /> SNMP (Hybrid Monitoring)
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">SNMP Version</Label>
                  <Select
                    value={form.snmp_version || "2c"}
                    onValueChange={v => setForm({...form, snmp_version: v})}
                  >
                    <SelectTrigger className="rounded-sm bg-background text-xs" data-testid="device-form-snmp-version">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="1">SNMPv1</SelectItem>
                      <SelectItem value="2c">SNMPv2c (default)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">Community String</Label>
                  <Input
                    value={form.snmp_community}
                    onChange={e => setForm({...form, snmp_community: e.target.value})}
                    className="rounded-sm bg-background font-mono text-xs"
                    placeholder="public"
                    data-testid="device-form-snmp-community"
                  />
                </div>
              </div>
              <p className="text-[10px] text-muted-foreground/60">
                SNMP v2c direkomendasikan untuk monitoring traffic (ifHCInOctets 64-bit). Default community: <code className="bg-muted px-1 rounded">public</code>
              </p>
            </div>
          </div>
          <DialogFooter className="flex-col sm:flex-row gap-2">
            {editing && (
              <Button
                variant="outline"
                size="sm"
                className="rounded-sm gap-1 text-cyan-500 border-cyan-500/30 hover:bg-cyan-500/10"
                onClick={() => handleTestSnmp(editing.id)}
                disabled={testing === editing.id + "_snmp"}
                data-testid="device-form-test-snmp"
              >
                <Radio className="w-3 h-3" />
                {testing === editing.id + "_snmp" ? (
                  <span className="flex items-center gap-1">
                    <span className="animate-spin inline-block w-3 h-3 border border-current border-t-transparent rounded-full" />
                    Testing...
                  </span>
                ) : "Test SNMP"}
              </Button>
            )}
            <div className="flex gap-2 ml-auto">
              <Button variant="outline" onClick={() => setDialogOpen(false)} className="rounded-sm" data-testid="device-form-cancel">Cancel</Button>
              <Button onClick={handleSave} className="rounded-sm" data-testid="device-form-save">{editing?"Update":"Add Device"}</Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
