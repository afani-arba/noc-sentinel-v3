import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import { Plus, Trash2, RefreshCw, Server, Wifi, WifiOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import { toast } from "sonner";

export default function DevicesPage() {
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState({ name: "", ip_address: "", port: 8728, username: "admin", password: "", description: "" });

  const fetchDevices = useCallback(async () => {
    try {
      const res = await api.get("/devices");
      setDevices(res.data);
    } catch (err) {
      toast.error("Failed to fetch devices");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchDevices();
  }, [fetchDevices]);

  const handleAdd = async () => {
    try {
      await api.post("/devices", { ...form, port: parseInt(form.port) || 8728 });
      toast.success("Device added");
      setDialogOpen(false);
      setForm({ name: "", ip_address: "", port: 8728, username: "admin", password: "", description: "" });
      fetchDevices();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to add device");
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this device?")) return;
    try {
      await api.delete(`/devices/${id}`);
      toast.success("Device deleted");
      fetchDevices();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Delete failed");
    }
  };

  return (
    <div className="space-y-6" data-testid="devices-page">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold font-['Rajdhani'] tracking-tight">Devices</h1>
          <p className="text-sm text-muted-foreground mt-1">Manage MikroTik router devices</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="icon" onClick={fetchDevices} className="rounded-sm" data-testid="devices-refresh-btn">
            <RefreshCw className="w-4 h-4" />
          </Button>
          <Button onClick={() => setDialogOpen(true)} className="rounded-sm gap-2" data-testid="add-device-btn">
            <Plus className="w-4 h-4" /> Add Device
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="text-center text-muted-foreground py-12">Loading devices...</div>
      ) : devices.length === 0 ? (
        <div className="text-center text-muted-foreground py-12">
          <Server className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p>No devices configured</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {devices.map((d) => (
            <div
              key={d.id}
              className="bg-card border border-border rounded-sm p-5 transition-all hover:border-border/80"
              data-testid={`device-card-${d.name}`}
            >
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-sm flex items-center justify-center ${d.status === "online" ? "bg-green-500/10" : "bg-red-500/10"}`}>
                    {d.status === "online" ? (
                      <Wifi className="w-5 h-5 text-green-500" />
                    ) : (
                      <WifiOff className="w-5 h-5 text-red-500" />
                    )}
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold">{d.name}</h3>
                    <p className="text-xs text-muted-foreground font-mono">{d.ip_address}:{d.port}</p>
                  </div>
                </div>
                <Badge className={`rounded-sm text-xs border ${d.status === "online" ? "bg-green-500/10 text-green-500 border-green-500/20" : "bg-red-500/10 text-red-500 border-red-500/20"}`}>
                  {d.status}
                </Badge>
              </div>

              <div className="space-y-2 text-xs">
                {d.model && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Model</span>
                    <span className="font-mono">{d.model}</span>
                  </div>
                )}
                {d.uptime && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Uptime</span>
                    <span className="font-mono">{d.uptime}</span>
                  </div>
                )}
                {d.cpu_load !== undefined && (
                  <div className="flex justify-between items-center">
                    <span className="text-muted-foreground">CPU</span>
                    <div className="flex items-center gap-2">
                      <div className="w-16 h-1.5 bg-secondary rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${d.cpu_load}%`,
                            backgroundColor: d.cpu_load > 80 ? "#ef4444" : d.cpu_load > 50 ? "#f59e0b" : "#10b981",
                          }}
                        />
                      </div>
                      <span className="font-mono w-8 text-right">{d.cpu_load}%</span>
                    </div>
                  </div>
                )}
                {d.memory_usage !== undefined && (
                  <div className="flex justify-between items-center">
                    <span className="text-muted-foreground">Memory</span>
                    <div className="flex items-center gap-2">
                      <div className="w-16 h-1.5 bg-secondary rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${d.memory_usage}%`,
                            backgroundColor: d.memory_usage > 80 ? "#ef4444" : d.memory_usage > 50 ? "#f59e0b" : "#10b981",
                          }}
                        />
                      </div>
                      <span className="font-mono w-8 text-right">{d.memory_usage}%</span>
                    </div>
                  </div>
                )}
              </div>

              <div className="mt-4 pt-3 border-t border-border/50 flex justify-end">
                <Button variant="ghost" size="sm" className="text-destructive gap-1 text-xs" onClick={() => handleDelete(d.id)} data-testid={`delete-device-${d.name}`}>
                  <Trash2 className="w-3.5 h-3.5" /> Remove
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <p className="text-xs text-muted-foreground">Total: {devices.length} devices</p>

      {/* Add Device Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="rounded-sm bg-card border-border max-w-md" data-testid="add-device-dialog">
          <DialogHeader>
            <DialogTitle className="font-['Rajdhani'] text-xl">Add Device</DialogTitle>
            <DialogDescription>Add a new MikroTik router device to monitor.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Device Name</Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="rounded-sm bg-background" placeholder="e.g. Router-Core-02" data-testid="device-form-name" />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2 space-y-1.5">
                <Label className="text-xs text-muted-foreground">IP Address</Label>
                <Input value={form.ip_address} onChange={(e) => setForm({ ...form, ip_address: e.target.value })} className="rounded-sm bg-background font-mono text-xs" placeholder="192.168.1.x" data-testid="device-form-ip" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Port</Label>
                <Input type="number" value={form.port} onChange={(e) => setForm({ ...form, port: e.target.value })} className="rounded-sm bg-background font-mono text-xs" data-testid="device-form-port" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Username</Label>
                <Input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} className="rounded-sm bg-background" data-testid="device-form-username" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Password</Label>
                <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className="rounded-sm bg-background" data-testid="device-form-password" />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Description</Label>
              <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="rounded-sm bg-background" data-testid="device-form-description" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} className="rounded-sm" data-testid="device-form-cancel">Cancel</Button>
            <Button onClick={handleAdd} className="rounded-sm" data-testid="device-form-save">Add Device</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
