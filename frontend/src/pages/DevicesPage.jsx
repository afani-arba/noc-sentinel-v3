import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import { Plus, Trash2, RefreshCw, Server, Wifi, WifiOff, Pencil, TestTube, Zap, Shield } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";

export default function DevicesPage() {
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [testing, setTesting] = useState("");
  const [form, setForm] = useState({
    name: "", ip_address: "", snmp_community: "public", snmp_port: 161,
    api_mode: "rest", api_username: "admin", api_password: "", api_port: 443, api_ssl: true, api_plaintext_login: true, description: "",
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
    // Port dikosongkan agar user bebas mengisi nilainya
    setForm({ name: "", ip_address: "", snmp_community: "public", snmp_port: 161, api_mode: "rest", api_username: "admin", api_password: "", api_port: "", api_ssl: true, api_plaintext_login: true, description: "" });
    setDialogOpen(true);
  };

  const openEdit = (d) => {
    setEditing(d);
    setForm({
      name: d.name, ip_address: d.ip_address || "", snmp_community: "public", snmp_port: d.snmp_port || 161,
      api_mode: d.api_mode || "rest", api_username: d.api_username || "admin", api_password: "",
      api_port: d.api_port || "",  // Biarkan kosong jika tidak ada, user bisa isi bebas
      api_ssl: d.api_ssl !== undefined ? d.api_ssl : (d.api_mode !== "api"),
      api_plaintext_login: d.api_plaintext_login !== undefined ? d.api_plaintext_login : true,
      description: d.description || "",
    });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    try {
      // Jika port kosong, gunakan default berdasarkan mode
      const defaultPort = form.api_mode === "api" ? 8728 : 443;
      const apiPort = form.api_port ? parseInt(form.api_port) : defaultPort;
      const data = { ...form, snmp_port: parseInt(form.snmp_port)||161, api_port: apiPort };
      if (editing) {
        if (!data.api_password) delete data.api_password;
        if (!data.snmp_community || data.snmp_community === "public") delete data.snmp_community;
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

  const handleTestSnmp = async (id) => {
    setTesting(id + "_snmp");
    try {
      const r = await api.post(`/devices/${id}/test-snmp`);
      if (r.data.snmp?.success) {
        toast.success(`SNMP OK - ${r.data.snmp.sys_name} | Ping: ${r.data.ping?.reachable ? r.data.ping.avg + "ms" : "unreachable"}`);
      } else {
        toast.error(`SNMP Failed: ${r.data.snmp?.error || "timeout"}`);
      }
    } catch (e) { toast.error("Test failed"); }
    setTesting("");
  };

  const handleTestApi = async (id) => {
    setTesting(id + "_api");
    try {
      const r = await api.post(`/devices/${id}/test-api`);
      if (r.data.success) {
        toast.success(`REST API OK - Identity: ${r.data.identity}`);
      } else {
        toast.error(`REST API Failed: ${r.data.error || "connection error"}`);
      }
    } catch (e) { toast.error("API test failed"); }
    setTesting("");
  };

  const handlePoll = async (id) => {
    setTesting(id + "_poll");
    try {
      const r = await api.post(`/devices/${id}/poll`);
      toast.success(r.data.reachable ? "Poll completed - device online" : "Poll completed - device offline");
      fetchDevices();
    } catch (e) { toast.error("Poll failed"); }
    setTesting("");
  };

  return (
    <div className="space-y-6" data-testid="devices-page">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold font-['Rajdhani'] tracking-tight">Devices</h1>
          <p className="text-sm text-muted-foreground mt-1">Manage MikroTik devices (SNMP monitoring + REST API)</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="icon" onClick={fetchDevices} className="rounded-sm" data-testid="devices-refresh-btn"><RefreshCw className="w-4 h-4" /></Button>
          <Button onClick={openAdd} className="rounded-sm gap-2" data-testid="add-device-btn"><Plus className="w-4 h-4" /> Add Device</Button>
        </div>
      </div>

      {loading ? (
        <div className="text-center text-muted-foreground py-12">Loading devices...</div>
      ) : devices.length === 0 ? (
        <div className="bg-card border border-border rounded-sm p-12 text-center"><Server className="w-12 h-12 mx-auto mb-3 text-muted-foreground/30" /><p className="text-muted-foreground">No devices configured</p><p className="text-xs text-muted-foreground mt-2">Add a MikroTik router to start monitoring</p></div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {devices.map(d => (
            <div key={d.id} className="bg-card border border-border rounded-sm p-5 transition-all hover:border-border/80" data-testid={`device-card-${d.name}`}>
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-sm flex items-center justify-center ${d.status==="online"?"bg-green-500/10":"bg-red-500/10"}`}>
                    {d.status==="online"?<Wifi className="w-5 h-5 text-green-500" />:<WifiOff className="w-5 h-5 text-red-500" />}
                  </div>
                  <div><h3 className="text-sm font-semibold">{d.name}</h3><p className="text-xs text-muted-foreground font-mono">{d.ip_address}</p></div>
                </div>
                <Badge className={`rounded-sm text-xs border ${d.status==="online"?"bg-green-500/10 text-green-500 border-green-500/20":d.status==="offline"?"bg-red-500/10 text-red-500 border-red-500/20":"bg-yellow-500/10 text-yellow-500 border-yellow-500/20"}`}>{d.status || "unknown"}</Badge>
              </div>
              <div className="space-y-2 text-xs">
                <div className="flex justify-between"><span className="text-muted-foreground">API Mode</span><Badge variant="outline" className="rounded-sm text-[10px]">{d.api_mode === "api" ? "RouterOS 6+ (API)" : "RouterOS 7+ (REST)"}</Badge></div>
                {d.model && <div className="flex justify-between"><span className="text-muted-foreground">Model</span><span className="font-mono">{d.model}</span></div>}
                {d.ros_version && <div className="flex justify-between"><span className="text-muted-foreground">RouterOS</span><span className="font-mono">v{d.ros_version}</span></div>}
                {d.uptime && <div className="flex justify-between"><span className="text-muted-foreground">Uptime</span><span className="font-mono">{d.uptime}</span></div>}
                {d.serial && <div className="flex justify-between"><span className="text-muted-foreground">Serial</span><span className="font-mono">{d.serial}</span></div>}
                {typeof d.cpu_load === "number" && d.status === "online" && (
                  <div className="flex justify-between items-center"><span className="text-muted-foreground">CPU</span><div className="flex items-center gap-2"><div className="w-16 h-1.5 bg-secondary rounded-full overflow-hidden"><div className="h-full rounded-full" style={{ width:`${d.cpu_load}%`, backgroundColor:d.cpu_load>80?"#ef4444":d.cpu_load>50?"#f59e0b":"#10b981" }} /></div><span className="font-mono w-8 text-right">{d.cpu_load}%</span></div></div>
                )}
                {typeof d.memory_usage === "number" && d.status === "online" && (
                  <div className="flex justify-between items-center"><span className="text-muted-foreground">Memory</span><div className="flex items-center gap-2"><div className="w-16 h-1.5 bg-secondary rounded-full overflow-hidden"><div className="h-full rounded-full" style={{ width:`${d.memory_usage}%`, backgroundColor:d.memory_usage>80?"#ef4444":d.memory_usage>50?"#f59e0b":"#10b981" }} /></div><span className="font-mono w-8 text-right">{d.memory_usage}%</span></div></div>
                )}
                {d.last_poll && <div className="flex justify-between"><span className="text-muted-foreground">Last Poll</span><span className="font-mono">{d.last_poll.replace("T"," ").slice(0,19)}</span></div>}
              </div>
              <div className="mt-4 pt-3 border-t border-border/50 flex flex-wrap gap-1.5">
                <Button variant="outline" size="sm" className="text-xs gap-1 h-7 rounded-sm" onClick={() => handleTestSnmp(d.id)} disabled={testing===d.id+"_snmp"} data-testid={`test-snmp-${d.name}`}>
                  <TestTube className="w-3 h-3" />{testing===d.id+"_snmp"?"Testing...":"SNMP"}
                </Button>
                <Button variant="outline" size="sm" className="text-xs gap-1 h-7 rounded-sm" onClick={() => handleTestApi(d.id)} disabled={testing===d.id+"_api"} data-testid={`test-api-${d.name}`}>
                  <Zap className="w-3 h-3" />{testing===d.id+"_api"?"Testing...":"API"}
                </Button>
                <Button variant="outline" size="sm" className="text-xs gap-1 h-7 rounded-sm" onClick={() => handlePoll(d.id)} disabled={testing===d.id+"_poll"} data-testid={`poll-${d.name}`}>
                  <RefreshCw className="w-3 h-3" />Poll
                </Button>
                <Button variant="ghost" size="sm" className="text-xs gap-1 h-7 rounded-sm" onClick={() => openEdit(d)} data-testid={`edit-device-${d.name}`}><Pencil className="w-3 h-3" />Edit</Button>
                <Button variant="ghost" size="sm" className="text-xs gap-1 h-7 rounded-sm text-destructive" onClick={() => handleDelete(d.id, d.name)} data-testid={`delete-device-${d.name}`}><Trash2 className="w-3 h-3" />Delete</Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="rounded-sm bg-card border-border max-w-lg max-h-[90vh] overflow-y-auto" data-testid="device-dialog">
          <DialogHeader>
            <DialogTitle className="font-['Rajdhani'] text-xl">{editing?"Edit Device":"Add Device"}</DialogTitle>
            <DialogDescription>Configure MikroTik device with SNMP monitoring and REST API access.</DialogDescription>
          </DialogHeader>
          <div className="space-y-5">
            <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Device Name</Label>
              <Input value={form.name} onChange={e => setForm({...form, name:e.target.value})} className="rounded-sm bg-background" placeholder="Router-Core-01" data-testid="device-form-name" /></div>
            <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">IP Address</Label>
              <Input value={form.ip_address} onChange={e => setForm({...form, ip_address:e.target.value})} className="rounded-sm bg-background font-mono text-xs" placeholder="192.168.1.1" data-testid="device-form-ip" /></div>

            {/* SNMP Section */}
            <div className="border border-border/50 rounded-sm p-3 space-y-3">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1"><Shield className="w-3 h-3" /> SNMP Monitoring</p>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Community String</Label>
                  <Input value={form.snmp_community} onChange={e => setForm({...form, snmp_community:e.target.value})} className="rounded-sm bg-background font-mono text-xs" data-testid="device-form-snmp-community" /></div>
                <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">SNMP Port</Label>
                  <Input type="number" value={form.snmp_port} onChange={e => setForm({...form, snmp_port:e.target.value})} className="rounded-sm bg-background font-mono text-xs" data-testid="device-form-snmp-port" /></div>
              </div>
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
                  onValueChange={v => {
                    // Hanya ubah mode, TIDAK auto-set port - biarkan user yang tentukan
                    setForm({...form, api_mode: v});
                  }}
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
                    ? "Untuk RouterOS versi 6.x - menggunakan port 8728/8729" 
                    : "Untuk RouterOS versi 7.1+ - menggunakan REST API di port 443/80"}
                </p>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">API Username</Label>
                  <Input value={form.api_username} onChange={e => setForm({...form, api_username:e.target.value})} className="rounded-sm bg-background" data-testid="device-form-api-username" /></div>
                <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">API Password</Label>
                  <Input type="password" value={form.api_password} onChange={e => setForm({...form, api_password:e.target.value})} className="rounded-sm bg-background" placeholder={editing?"(unchanged)":""} data-testid="device-form-api-password" /></div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">API Port</Label>
                  <Input 
                    type="number" 
                    value={form.api_port} 
                    onChange={e => setForm({...form, api_port:e.target.value})} 
                    className="rounded-sm bg-background font-mono text-xs" 
                    placeholder={form.api_mode === "api" ? "8728" : "443"}
                    data-testid="device-form-api-port" 
                  />
                  <p className="text-[10px] text-muted-foreground/70">
                    {form.api_mode === "api" ? "Kosong = 8728 (SSL: 8729)" : "Kosong = 443 (HTTP: 80)"}
                  </p>
                </div>
                <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">SSL/TLS</Label>
                  <Select value={form.api_ssl?"true":"false"} onValueChange={v => setForm({...form, api_ssl:v==="true"})}>
                    <SelectTrigger className="rounded-sm bg-background text-xs" data-testid="device-form-ssl"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {form.api_mode === "api" ? (
                        <>
                          <SelectItem value="false">Tanpa SSL (Port 8728)</SelectItem>
                          <SelectItem value="true">Dengan SSL (Port 8729)</SelectItem>
                        </>
                      ) : (
                        <>
                          <SelectItem value="true">HTTPS (Port 443)</SelectItem>
                          <SelectItem value="false">HTTP (Port 80)</SelectItem>
                        </>
                      )}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </div>
            <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Description</Label>
              <Input value={form.description} onChange={e => setForm({...form, description:e.target.value})} className="rounded-sm bg-background" data-testid="device-form-description" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} className="rounded-sm" data-testid="device-form-cancel">Cancel</Button>
            <Button onClick={handleSave} className="rounded-sm" data-testid="device-form-save">{editing?"Update":"Add Device"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
