import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import { useAuth } from "@/App";
import { Search, Plus, Pencil, Trash2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";

const formatBytes = (bytes) => {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
};

const statusColor = (s) => {
  if (s === "active") return "bg-green-500/10 text-green-500 border-green-500/20";
  if (s === "disabled") return "bg-red-500/10 text-red-500 border-red-500/20";
  return "bg-yellow-500/10 text-yellow-500 border-yellow-500/20";
};

export default function PPPoEUsersPage() {
  const { user } = useAuth();
  const isViewer = user?.role === "viewer";
  const [users, setUsers] = useState([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ username: "", password: "", profile: "10Mbps", service: "pppoe", ip_address: "", mac_address: "", comment: "" });

  const fetchUsers = useCallback(async () => {
    try {
      const params = {};
      if (search) params.search = search;
      if (statusFilter) params.status = statusFilter;
      const res = await api.get("/pppoe-users", { params });
      setUsers(res.data);
    } catch (err) {
      toast.error("Failed to fetch PPPoE users");
    }
    setLoading(false);
  }, [search, statusFilter]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const openAdd = () => {
    setEditing(null);
    setForm({ username: "", password: "", profile: "10Mbps", service: "pppoe", ip_address: "", mac_address: "", comment: "" });
    setDialogOpen(true);
  };

  const openEdit = (u) => {
    setEditing(u);
    setForm({
      username: u.username, password: "", profile: u.profile, service: u.service || "pppoe",
      ip_address: u.ip_address || "", mac_address: u.mac_address || "", comment: u.comment || "",
      status: u.status,
    });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    try {
      if (editing) {
        const data = { ...form };
        if (!data.password) delete data.password;
        await api.put(`/pppoe-users/${editing.id}`, data);
        toast.success("User updated");
      } else {
        await api.post("/pppoe-users", form);
        toast.success("User created");
      }
      setDialogOpen(false);
      fetchUsers();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Operation failed");
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this PPPoE user?")) return;
    try {
      await api.delete(`/pppoe-users/${id}`);
      toast.success("User deleted");
      fetchUsers();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Delete failed");
    }
  };

  return (
    <div className="space-y-6" data-testid="pppoe-users-page">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold font-['Rajdhani'] tracking-tight">PPPoE Users</h1>
          <p className="text-sm text-muted-foreground mt-1">Manage PPPoE user connections</p>
        </div>
        {!isViewer && (
          <Button onClick={openAdd} className="rounded-sm gap-2" data-testid="add-pppoe-user-btn">
            <Plus className="w-4 h-4" /> Add User
          </Button>
        )}
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder="Search username, IP, MAC..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 rounded-sm bg-card"
            data-testid="pppoe-search-input"
          />
        </div>
        <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v === "all" ? "" : v)}>
          <SelectTrigger className="w-36 rounded-sm bg-card" data-testid="pppoe-status-filter">
            <SelectValue placeholder="All Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Status</SelectItem>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="disabled">Disabled</SelectItem>
          </SelectContent>
        </Select>
        <Button variant="outline" size="icon" onClick={fetchUsers} className="rounded-sm" data-testid="pppoe-refresh-btn">
          <RefreshCw className="w-4 h-4" />
        </Button>
      </div>

      {/* Table */}
      <div className="bg-card border border-border rounded-sm overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Username</TableHead>
              <TableHead>Profile</TableHead>
              <TableHead className="hidden md:table-cell">IP Address</TableHead>
              <TableHead className="hidden lg:table-cell">MAC Address</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="hidden md:table-cell">Uptime</TableHead>
              <TableHead className="hidden lg:table-cell">Download</TableHead>
              <TableHead className="hidden lg:table-cell">Upload</TableHead>
              {!isViewer && <TableHead className="text-right">Actions</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow><TableCell colSpan={9} className="text-center text-muted-foreground py-8">Loading...</TableCell></TableRow>
            ) : users.length === 0 ? (
              <TableRow><TableCell colSpan={9} className="text-center text-muted-foreground py-8">No users found</TableCell></TableRow>
            ) : (
              users.map((u) => (
                <TableRow key={u.id} data-testid={`pppoe-row-${u.username}`}>
                  <TableCell className="font-mono text-xs">{u.username}</TableCell>
                  <TableCell><Badge variant="outline" className="rounded-sm text-xs">{u.profile}</Badge></TableCell>
                  <TableCell className="hidden md:table-cell font-mono text-xs">{u.ip_address}</TableCell>
                  <TableCell className="hidden lg:table-cell font-mono text-xs">{u.mac_address}</TableCell>
                  <TableCell>
                    <Badge className={`rounded-sm text-xs border ${statusColor(u.status)}`}>{u.status}</Badge>
                  </TableCell>
                  <TableCell className="hidden md:table-cell font-mono text-xs">{u.uptime}</TableCell>
                  <TableCell className="hidden lg:table-cell font-mono text-xs">{formatBytes(u.bytes_in)}</TableCell>
                  <TableCell className="hidden lg:table-cell font-mono text-xs">{formatBytes(u.bytes_out)}</TableCell>
                  {!isViewer && (
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openEdit(u)} data-testid={`pppoe-edit-${u.username}`}>
                          <Pencil className="w-3.5 h-3.5" />
                        </Button>
                        {user?.role === "administrator" && (
                          <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => handleDelete(u.id)} data-testid={`pppoe-delete-${u.username}`}>
                            <Trash2 className="w-3.5 h-3.5" />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  )}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <p className="text-xs text-muted-foreground">Total: {users.length} users</p>

      {/* Add/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="rounded-sm bg-card border-border max-w-md" data-testid="pppoe-user-dialog">
          <DialogHeader>
            <DialogTitle className="font-['Rajdhani'] text-xl">{editing ? "Edit PPPoE User" : "Add PPPoE User"}</DialogTitle>
            <DialogDescription>
              {editing ? "Update the PPPoE user details below." : "Fill in the details to create a new PPPoE user."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Username</Label>
                <Input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} className="rounded-sm bg-background" data-testid="pppoe-form-username" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Password</Label>
                <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className="rounded-sm bg-background" placeholder={editing ? "(unchanged)" : ""} data-testid="pppoe-form-password" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Profile</Label>
                <Select value={form.profile} onValueChange={(v) => setForm({ ...form, profile: v })}>
                  <SelectTrigger className="rounded-sm bg-background" data-testid="pppoe-form-profile">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {["10Mbps", "20Mbps", "50Mbps", "100Mbps"].map((p) => (
                      <SelectItem key={p} value={p}>{p}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {editing && (
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">Status</Label>
                  <Select value={form.status} onValueChange={(v) => setForm({ ...form, status: v })}>
                    <SelectTrigger className="rounded-sm bg-background" data-testid="pppoe-form-status">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="active">Active</SelectItem>
                      <SelectItem value="disabled">Disabled</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              )}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">IP Address</Label>
                <Input value={form.ip_address} onChange={(e) => setForm({ ...form, ip_address: e.target.value })} className="rounded-sm bg-background font-mono text-xs" placeholder="10.0.1.x" data-testid="pppoe-form-ip" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">MAC Address</Label>
                <Input value={form.mac_address} onChange={(e) => setForm({ ...form, mac_address: e.target.value })} className="rounded-sm bg-background font-mono text-xs" placeholder="aa:bb:cc:dd:ee:ff" data-testid="pppoe-form-mac" />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Comment</Label>
              <Input value={form.comment} onChange={(e) => setForm({ ...form, comment: e.target.value })} className="rounded-sm bg-background" data-testid="pppoe-form-comment" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} className="rounded-sm" data-testid="pppoe-form-cancel">Cancel</Button>
            <Button onClick={handleSave} className="rounded-sm" data-testid="pppoe-form-save">{editing ? "Update" : "Create"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
