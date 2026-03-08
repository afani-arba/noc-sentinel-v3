import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import { useAuth } from "@/App";
import { Search, Plus, Pencil, Trash2, RefreshCw, Wifi, WifiOff, Server } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";

export default function PPPoEUsersPage() {
  const { user } = useAuth();
  const isViewer = user?.role === "viewer";
  const [devices, setDevices] = useState([]);
  const [selectedDevice, setSelectedDevice] = useState("");
  const [users, setUsers] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ name: "", password: "", profile: "default", service: "pppoe", comment: "" });

  useEffect(() => {
    api.get("/devices").then(r => {
      setDevices(r.data);
      if (r.data.length === 1) setSelectedDevice(r.data[0].id);
    }).catch(() => {});
  }, []);

  const fetchUsers = useCallback(async () => {
    if (!selectedDevice) return;
    setLoading(true);
    setError("");
    try {
      const params = { device_id: selectedDevice };
      if (search) params.search = search;
      const r = await api.get("/pppoe-users", { params });
      setUsers(r.data);
    } catch (e) {
      const msg = e.response?.data?.detail || "Failed to connect to MikroTik";
      setError(msg);
      setUsers([]);
    }
    setLoading(false);
  }, [selectedDevice, search]);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const openAdd = () => {
    setEditing(null);
    setForm({ name: "", password: "", profile: "default", service: "pppoe", comment: "" });
    setDialogOpen(true);
  };

  const openEdit = (u) => {
    setEditing(u);
    setForm({ name: u.name || "", password: "", profile: u.profile || "default", service: u.service || "pppoe", comment: u.comment || "", disabled: u.disabled || "false" });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    try {
      if (editing) {
        const data = { ...form };
        if (!data.password) delete data.password;
        await api.put(`/pppoe-users/${editing[".id"]}?device_id=${selectedDevice}`, data);
        toast.success("PPPoE user updated on MikroTik");
      } else {
        await api.post(`/pppoe-users?device_id=${selectedDevice}`, form);
        toast.success("PPPoE user created on MikroTik");
      }
      setDialogOpen(false);
      fetchUsers();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Operation failed");
    }
  };

  const handleDelete = async (mtId, name) => {
    if (!window.confirm(`Delete PPPoE user "${name}" from MikroTik?`)) return;
    try {
      await api.delete(`/pppoe-users/${mtId}?device_id=${selectedDevice}`);
      toast.success("PPPoE user deleted");
      fetchUsers();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Delete failed");
    }
  };

  const currentDev = devices.find(d => d.id === selectedDevice);

  return (
    <div className="space-y-6" data-testid="pppoe-users-page">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold font-['Rajdhani'] tracking-tight">PPPoE Users</h1>
          <p className="text-sm text-muted-foreground mt-1">Manage PPPoE secrets on MikroTik via REST API</p>
        </div>
        {!isViewer && selectedDevice && (
          <Button onClick={openAdd} className="rounded-sm gap-2" data-testid="add-pppoe-user-btn"><Plus className="w-4 h-4" /> Add User</Button>
        )}
      </div>

      {/* Device Selector */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="space-y-1 flex-shrink-0">
          <label className="text-[10px] text-muted-foreground uppercase tracking-widest">Select Device</label>
          <Select value={selectedDevice} onValueChange={setSelectedDevice}>
            <SelectTrigger className="w-56 rounded-sm bg-card text-xs h-9" data-testid="pppoe-device-select"><SelectValue placeholder="Select device..." /></SelectTrigger>
            <SelectContent>
              {devices.map(d => (
                <SelectItem key={d.id} value={d.id}><span className="flex items-center gap-2"><div className={`w-1.5 h-1.5 rounded-full ${d.status==="online"?"bg-green-500":"bg-red-500"}`} />{d.name}</span></SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {selectedDevice && (
          <>
            <div className="relative flex-1 max-w-md self-end">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input placeholder="Search username, profile..." value={search} onChange={e => setSearch(e.target.value)} className="pl-9 rounded-sm bg-card h-9" data-testid="pppoe-search-input" />
            </div>
            <Button variant="outline" size="icon" onClick={fetchUsers} className="rounded-sm h-9 w-9 self-end" data-testid="pppoe-refresh-btn"><RefreshCw className="w-4 h-4" /></Button>
          </>
        )}
      </div>

      {!selectedDevice ? (
        <div className="bg-card border border-border rounded-sm p-12 text-center"><Server className="w-12 h-12 mx-auto mb-3 text-muted-foreground/30" /><p className="text-muted-foreground">Select a MikroTik device to view PPPoE users</p></div>
      ) : error ? (
        <div className="bg-card border border-red-500/30 rounded-sm p-8 text-center"><WifiOff className="w-10 h-10 mx-auto mb-3 text-red-500/50" /><p className="text-red-400 text-sm">{error}</p><p className="text-xs text-muted-foreground mt-2">Make sure the MikroTik REST API is enabled and credentials are correct</p></div>
      ) : (
        <div className="bg-card border border-border rounded-sm overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Username</TableHead>
                <TableHead>Password</TableHead>
                <TableHead>Profile</TableHead>
                <TableHead>Service</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="hidden md:table-cell">Online</TableHead>
                <TableHead className="hidden lg:table-cell">Comment</TableHead>
                {!isViewer && <TableHead className="text-right">Actions</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow><TableCell colSpan={8} className="text-center text-muted-foreground py-8">Connecting to MikroTik...</TableCell></TableRow>
              ) : users.length === 0 ? (
                <TableRow><TableCell colSpan={8} className="text-center text-muted-foreground py-8">No PPPoE users found</TableCell></TableRow>
              ) : users.map(u => (
                <TableRow key={u[".id"]} data-testid={`pppoe-row-${u.name}`}>
                  <TableCell className="font-mono text-xs">{u.name}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {u.password && u.password !== "" && !u.password.includes("*") ? u.password : (
                      <span className="text-yellow-500/70 italic text-[10px]">tersembunyi (ROS7)</span>
                    )}
                  </TableCell>
                  <TableCell><Badge variant="outline" className="rounded-sm text-xs">{u.profile || "default"}</Badge></TableCell>
                  <TableCell className="text-xs">{u.service || "pppoe"}</TableCell>
                  <TableCell>
                    <Badge className={`rounded-sm text-xs border ${u.disabled==="true"?"bg-red-500/10 text-red-500 border-red-500/20":"bg-green-500/10 text-green-500 border-green-500/20"}`}>
                      {u.disabled==="true"?"disabled":"enabled"}
                    </Badge>
                  </TableCell>
                  <TableCell className="hidden md:table-cell">
                    {u.is_online ? <Badge className="rounded-sm text-xs border bg-green-500/10 text-green-500 border-green-500/20 gap-1"><Wifi className="w-3 h-3" />Online</Badge> : <span className="text-xs text-muted-foreground">Offline</span>}
                  </TableCell>
                  <TableCell className="hidden lg:table-cell text-xs text-muted-foreground">{u.comment || "-"}</TableCell>
                  {!isViewer && (
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openEdit(u)} data-testid={`pppoe-edit-${u.name}`}><Pencil className="w-3.5 h-3.5" /></Button>
                        {user?.role === "administrator" && <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => handleDelete(u[".id"], u.name)} data-testid={`pppoe-delete-${u.name}`}><Trash2 className="w-3.5 h-3.5" /></Button>}
                      </div>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {selectedDevice && !error && <p className="text-xs text-muted-foreground">Total: {users.length} users {currentDev && `on ${currentDev.name}`}</p>}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="rounded-sm bg-card border-border max-w-md" data-testid="pppoe-user-dialog">
          <DialogHeader>
            <DialogTitle className="font-['Rajdhani'] text-xl">{editing ? "Edit PPPoE User" : "Add PPPoE User"}</DialogTitle>
            <DialogDescription>{editing ? "Update PPPoE secret on MikroTik." : "Create a new PPPoE secret on MikroTik."}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Username</Label>
                <Input value={form.name} onChange={e => setForm({...form, name:e.target.value})} className="rounded-sm bg-background" data-testid="pppoe-form-username" /></div>
              <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Password</Label>
                <Input type="password" value={form.password} onChange={e => setForm({...form, password:e.target.value})} className="rounded-sm bg-background" placeholder={editing?"(unchanged)":""} data-testid="pppoe-form-password" /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Profile</Label>
                <Input value={form.profile} onChange={e => setForm({...form, profile:e.target.value})} className="rounded-sm bg-background" data-testid="pppoe-form-profile" /></div>
              <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Service</Label>
                <Input value={form.service} onChange={e => setForm({...form, service:e.target.value})} className="rounded-sm bg-background" data-testid="pppoe-form-service" /></div>
            </div>
            {editing && (
              <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Status</Label>
                <Select value={form.disabled} onValueChange={v => setForm({...form, disabled:v})}>
                  <SelectTrigger className="rounded-sm bg-background" data-testid="pppoe-form-status"><SelectValue /></SelectTrigger>
                  <SelectContent><SelectItem value="false">Enabled</SelectItem><SelectItem value="true">Disabled</SelectItem></SelectContent>
                </Select></div>
            )}
            <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Comment</Label>
              <Input value={form.comment} onChange={e => setForm({...form, comment:e.target.value})} className="rounded-sm bg-background" data-testid="pppoe-form-comment" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} className="rounded-sm" data-testid="pppoe-form-cancel">Cancel</Button>
            <Button onClick={handleSave} className="rounded-sm" data-testid="pppoe-form-save">{editing?"Update":"Create"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
