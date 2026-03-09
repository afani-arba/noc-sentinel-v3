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

export default function HotspotUsersPage() {
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
  const [form, setForm] = useState({ name: "", password: "", profile: "default", server: "all", comment: "" });

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
      const r = await api.get("/hotspot-users", { params });
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
    setForm({ name: "", password: "", profile: "default", server: "all", comment: "" });
    setDialogOpen(true);
  };

  const openEdit = (u) => {
    setEditing(u);
    setForm({ name: u.name || "", password: "", profile: u.profile || "default", server: u.server || "all", comment: u.comment || "", disabled: u.disabled || "false" });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    try {
      if (editing) {
        const data = { ...form };
        if (!data.password) delete data.password;
        await api.put(`/hotspot-users/${editing[".id"]}?device_id=${selectedDevice}`, data);
        toast.success("Hotspot user updated on MikroTik");
      } else {
        await api.post(`/hotspot-users?device_id=${selectedDevice}`, form);
        toast.success("Hotspot user created on MikroTik");
      }
      setDialogOpen(false);
      fetchUsers();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Operation failed");
    }
  };

  const handleDelete = async (mtId, name) => {
    if (!window.confirm(`Delete hotspot user "${name}" from MikroTik?`)) return;
    try {
      await api.delete(`/hotspot-users/${mtId}?device_id=${selectedDevice}`);
      toast.success("Hotspot user deleted");
      fetchUsers();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Delete failed");
    }
  };

  const currentDev = devices.find(d => d.id === selectedDevice);

  return (
    <div className="space-y-4 pb-16" data-testid="hotspot-users-page">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl md:text-3xl font-bold font-['Rajdhani'] tracking-tight">Hotspot Users</h1>
          <p className="text-xs sm:text-sm text-muted-foreground">Manage hotspot users on MikroTik</p>
        </div>
        {!isViewer && selectedDevice && (
          <Button onClick={openAdd} size="sm" className="rounded-sm gap-2" data-testid="add-hotspot-user-btn"><Plus className="w-4 h-4" /> <span className="hidden sm:inline">Add User</span></Button>
        )}
      </div>

      <div className="flex flex-col sm:flex-row gap-2 sm:gap-3">
        <div className="space-y-1">
          <label className="text-[10px] text-muted-foreground uppercase tracking-widest">Select Device</label>
          <Select value={selectedDevice} onValueChange={setSelectedDevice}>
            <SelectTrigger className="w-full sm:w-48 rounded-sm bg-card text-xs h-9" data-testid="hotspot-device-select"><SelectValue placeholder="Select device..." /></SelectTrigger>
            <SelectContent>
              {devices.map(d => (
                <SelectItem key={d.id} value={d.id}><span className="flex items-center gap-2"><div className={`w-1.5 h-1.5 rounded-full ${d.status==="online"?"bg-green-500":"bg-red-500"}`} />{d.name}</span></SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {selectedDevice && (
          <div className="flex gap-2 flex-1">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input placeholder="Search..." value={search} onChange={e => setSearch(e.target.value)} className="pl-9 rounded-sm bg-card h-9 text-xs" data-testid="hotspot-search-input" />
            </div>
            <Button variant="outline" size="icon" onClick={fetchUsers} className="rounded-sm h-9 w-9 flex-shrink-0" data-testid="hotspot-refresh-btn"><RefreshCw className="w-4 h-4" /></Button>
          </div>
        )}
      </div>

      {!selectedDevice ? (
        <div className="bg-card border border-border rounded-sm p-8 sm:p-12 text-center"><Server className="w-10 h-10 sm:w-12 sm:h-12 mx-auto mb-3 text-muted-foreground/30" /><p className="text-sm text-muted-foreground">Select a MikroTik device</p></div>
      ) : error ? (
        <div className="bg-card border border-red-500/30 rounded-sm p-6 sm:p-8 text-center"><WifiOff className="w-8 h-8 sm:w-10 sm:h-10 mx-auto mb-3 text-red-500/50" /><p className="text-red-400 text-xs sm:text-sm">{error}</p></div>
      ) : (
        <div className="bg-card border border-border rounded-sm overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs">Username</TableHead>
                <TableHead className="text-xs hidden sm:table-cell">Password</TableHead>
                <TableHead className="text-xs">Profile</TableHead>
                <TableHead className="text-xs hidden md:table-cell">Server</TableHead>
                <TableHead className="text-xs">Status</TableHead>
                {!isViewer && <TableHead className="text-xs text-right">Actions</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow><TableCell colSpan={6} className="text-center text-muted-foreground py-8 text-sm">Connecting...</TableCell></TableRow>
              ) : users.length === 0 ? (
                <TableRow><TableCell colSpan={6} className="text-center text-muted-foreground py-8 text-sm">No hotspot users</TableCell></TableRow>
              ) : users.map(u => (
                <TableRow key={u[".id"]} data-testid={`hotspot-row-${u.name}`}>
                  <TableCell className="font-mono text-[11px] sm:text-xs">{u.name}</TableCell>
                  <TableCell className="font-mono text-[11px] sm:text-xs text-muted-foreground hidden sm:table-cell">{u.password || "••••••"}</TableCell>
                  <TableCell><Badge variant="outline" className="rounded-sm text-[10px] sm:text-xs">{u.profile || "default"}</Badge></TableCell>
                  <TableCell className="text-xs hidden md:table-cell">{u.server || "all"}</TableCell>
                  <TableCell>
                    <Badge className={`rounded-sm text-[10px] sm:text-xs border ${u.disabled==="true"?"bg-red-500/10 text-red-500 border-red-500/20":"bg-green-500/10 text-green-500 border-green-500/20"}`}>
                      {u.disabled==="true"?"off":"on"}
                    </Badge>
                  </TableCell>
                  {!isViewer && (
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openEdit(u)} data-testid={`hotspot-edit-${u.name}`}><Pencil className="w-3.5 h-3.5" /></Button>
                        {user?.role === "administrator" && <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => handleDelete(u[".id"], u.name)} data-testid={`hotspot-delete-${u.name}`}><Trash2 className="w-3.5 h-3.5" /></Button>}
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
        <DialogContent className="rounded-sm bg-card border-border max-w-md" data-testid="hotspot-user-dialog">
          <DialogHeader>
            <DialogTitle className="font-['Rajdhani'] text-xl">{editing ? "Edit Hotspot User" : "Add Hotspot User"}</DialogTitle>
            <DialogDescription>{editing ? "Update hotspot user on MikroTik." : "Create a new hotspot user on MikroTik."}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Username</Label>
                <Input value={form.name} onChange={e => setForm({...form, name:e.target.value})} className="rounded-sm bg-background" data-testid="hotspot-form-username" /></div>
              <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Password</Label>
                <Input type="password" value={form.password} onChange={e => setForm({...form, password:e.target.value})} className="rounded-sm bg-background" placeholder={editing?"(unchanged)":""} data-testid="hotspot-form-password" /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Profile</Label>
                <Input value={form.profile} onChange={e => setForm({...form, profile:e.target.value})} className="rounded-sm bg-background" data-testid="hotspot-form-profile" /></div>
              <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Server</Label>
                <Input value={form.server} onChange={e => setForm({...form, server:e.target.value})} className="rounded-sm bg-background" data-testid="hotspot-form-server" /></div>
            </div>
            {editing && (
              <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Status</Label>
                <Select value={form.disabled} onValueChange={v => setForm({...form, disabled:v})}>
                  <SelectTrigger className="rounded-sm bg-background" data-testid="hotspot-form-status"><SelectValue /></SelectTrigger>
                  <SelectContent><SelectItem value="false">Enabled</SelectItem><SelectItem value="true">Disabled</SelectItem></SelectContent>
                </Select></div>
            )}
            <div className="space-y-1.5"><Label className="text-xs text-muted-foreground">Comment</Label>
              <Input value={form.comment} onChange={e => setForm({...form, comment:e.target.value})} className="rounded-sm bg-background" data-testid="hotspot-form-comment" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} className="rounded-sm" data-testid="hotspot-form-cancel">Cancel</Button>
            <Button onClick={handleSave} className="rounded-sm" data-testid="hotspot-form-save">{editing?"Update":"Create"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
