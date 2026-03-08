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
  if (s === "expired") return "bg-yellow-500/10 text-yellow-500 border-yellow-500/20";
  return "bg-gray-500/10 text-gray-500 border-gray-500/20";
};

export default function HotspotUsersPage() {
  const { user } = useAuth();
  const isViewer = user?.role === "viewer";
  const [users, setUsers] = useState([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({
    username: "", password: "", profile: "1hour", server: "hotspot1",
    mac_address: "", limit_uptime: "", limit_bytes_total: "", comment: "",
  });

  const fetchUsers = useCallback(async () => {
    try {
      const params = {};
      if (search) params.search = search;
      if (statusFilter) params.status = statusFilter;
      const res = await api.get("/hotspot-users", { params });
      setUsers(res.data);
    } catch (err) {
      toast.error("Failed to fetch hotspot users");
    }
    setLoading(false);
  }, [search, statusFilter]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const openAdd = () => {
    setEditing(null);
    setForm({
      username: "", password: "", profile: "1hour", server: "hotspot1",
      mac_address: "", limit_uptime: "", limit_bytes_total: "", comment: "",
    });
    setDialogOpen(true);
  };

  const openEdit = (u) => {
    setEditing(u);
    setForm({
      username: u.username, password: "", profile: u.profile, server: u.server || "hotspot1",
      mac_address: u.mac_address || "", limit_uptime: u.limit_uptime || "",
      limit_bytes_total: u.limit_bytes_total || "", comment: u.comment || "",
      status: u.status,
    });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    try {
      if (editing) {
        const data = { ...form };
        if (!data.password) delete data.password;
        await api.put(`/hotspot-users/${editing.id}`, data);
        toast.success("User updated");
      } else {
        await api.post("/hotspot-users", form);
        toast.success("User created");
      }
      setDialogOpen(false);
      fetchUsers();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Operation failed");
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this hotspot user?")) return;
    try {
      await api.delete(`/hotspot-users/${id}`);
      toast.success("User deleted");
      fetchUsers();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Delete failed");
    }
  };

  return (
    <div className="space-y-6" data-testid="hotspot-users-page">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold font-['Rajdhani'] tracking-tight">Hotspot Users</h1>
          <p className="text-sm text-muted-foreground mt-1">Manage hotspot user sessions</p>
        </div>
        {!isViewer && (
          <Button onClick={openAdd} className="rounded-sm gap-2" data-testid="add-hotspot-user-btn">
            <Plus className="w-4 h-4" /> Add User
          </Button>
        )}
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder="Search username, MAC..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 rounded-sm bg-card"
            data-testid="hotspot-search-input"
          />
        </div>
        <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v === "all" ? "" : v)}>
          <SelectTrigger className="w-36 rounded-sm bg-card" data-testid="hotspot-status-filter">
            <SelectValue placeholder="All Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Status</SelectItem>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="expired">Expired</SelectItem>
            <SelectItem value="disabled">Disabled</SelectItem>
          </SelectContent>
        </Select>
        <Button variant="outline" size="icon" onClick={fetchUsers} className="rounded-sm" data-testid="hotspot-refresh-btn">
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
              <TableHead>Server</TableHead>
              <TableHead className="hidden md:table-cell">MAC Address</TableHead>
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
                <TableRow key={u.id} data-testid={`hotspot-row-${u.username}`}>
                  <TableCell className="font-mono text-xs">{u.username}</TableCell>
                  <TableCell><Badge variant="outline" className="rounded-sm text-xs">{u.profile}</Badge></TableCell>
                  <TableCell className="text-xs">{u.server}</TableCell>
                  <TableCell className="hidden md:table-cell font-mono text-xs">{u.mac_address}</TableCell>
                  <TableCell>
                    <Badge className={`rounded-sm text-xs border ${statusColor(u.status)}`}>{u.status}</Badge>
                  </TableCell>
                  <TableCell className="hidden md:table-cell font-mono text-xs">{u.uptime}</TableCell>
                  <TableCell className="hidden lg:table-cell font-mono text-xs">{formatBytes(u.bytes_in)}</TableCell>
                  <TableCell className="hidden lg:table-cell font-mono text-xs">{formatBytes(u.bytes_out)}</TableCell>
                  {!isViewer && (
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openEdit(u)} data-testid={`hotspot-edit-${u.username}`}>
                          <Pencil className="w-3.5 h-3.5" />
                        </Button>
                        {user?.role === "administrator" && (
                          <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => handleDelete(u.id)} data-testid={`hotspot-delete-${u.username}`}>
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

      {/* Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="rounded-sm bg-card border-border max-w-md" data-testid="hotspot-user-dialog">
          <DialogHeader>
            <DialogTitle className="font-['Rajdhani'] text-xl">{editing ? "Edit Hotspot User" : "Add Hotspot User"}</DialogTitle>
            <DialogDescription>
              {editing ? "Update the hotspot user details below." : "Fill in the details to create a new hotspot user."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Username</Label>
                <Input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} className="rounded-sm bg-background" data-testid="hotspot-form-username" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Password</Label>
                <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className="rounded-sm bg-background" placeholder={editing ? "(unchanged)" : ""} data-testid="hotspot-form-password" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Profile</Label>
                <Select value={form.profile} onValueChange={(v) => setForm({ ...form, profile: v })}>
                  <SelectTrigger className="rounded-sm bg-background" data-testid="hotspot-form-profile">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {["1hour", "3hour", "1day", "1week", "1month"].map((p) => (
                      <SelectItem key={p} value={p}>{p}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Server</Label>
                <Select value={form.server} onValueChange={(v) => setForm({ ...form, server: v })}>
                  <SelectTrigger className="rounded-sm bg-background" data-testid="hotspot-form-server">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="hotspot1">hotspot1</SelectItem>
                    <SelectItem value="hotspot2">hotspot2</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            {editing && (
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Status</Label>
                <Select value={form.status} onValueChange={(v) => setForm({ ...form, status: v })}>
                  <SelectTrigger className="rounded-sm bg-background" data-testid="hotspot-form-status">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="active">Active</SelectItem>
                    <SelectItem value="expired">Expired</SelectItem>
                    <SelectItem value="disabled">Disabled</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Limit Uptime</Label>
                <Input value={form.limit_uptime} onChange={(e) => setForm({ ...form, limit_uptime: e.target.value })} className="rounded-sm bg-background font-mono text-xs" placeholder="e.g. 24h" data-testid="hotspot-form-limit-uptime" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Limit Bytes</Label>
                <Input value={form.limit_bytes_total} onChange={(e) => setForm({ ...form, limit_bytes_total: e.target.value })} className="rounded-sm bg-background font-mono text-xs" placeholder="e.g. 500M" data-testid="hotspot-form-limit-bytes" />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Comment</Label>
              <Input value={form.comment} onChange={(e) => setForm({ ...form, comment: e.target.value })} className="rounded-sm bg-background" data-testid="hotspot-form-comment" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} className="rounded-sm" data-testid="hotspot-form-cancel">Cancel</Button>
            <Button onClick={handleSave} className="rounded-sm" data-testid="hotspot-form-save">{editing ? "Update" : "Create"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
