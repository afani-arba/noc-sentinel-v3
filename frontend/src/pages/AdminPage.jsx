import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import { useAuth } from "@/App";
import { Plus, Pencil, Trash2, RefreshCw, Shield, Eye, User } from "lucide-react";
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

const roleConfig = {
  administrator: { icon: Shield, color: "text-red-500", bg: "bg-red-500/10 border-red-500/20" },
  viewer: { icon: Eye, color: "text-blue-500", bg: "bg-blue-500/10 border-blue-500/20" },
  user: { icon: User, color: "text-green-500", bg: "bg-green-500/10 border-green-500/20" },
};

export default function AdminPage() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ username: "", password: "", full_name: "", role: "user" });

  const fetchUsers = useCallback(async () => {
    try {
      const res = await api.get("/admin/users");
      setUsers(res.data);
    } catch (err) {
      toast.error("Failed to fetch users");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const openAdd = () => {
    setEditing(null);
    setForm({ username: "", password: "", full_name: "", role: "user" });
    setDialogOpen(true);
  };

  const openEdit = (u) => {
    setEditing(u);
    setForm({ username: u.username, password: "", full_name: u.full_name, role: u.role });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    try {
      if (editing) {
        const data = { full_name: form.full_name, role: form.role };
        if (form.password) data.password = form.password;
        await api.put(`/admin/users/${editing.id}`, data);
        toast.success("User updated");
      } else {
        if (!form.username || !form.password || !form.full_name) {
          toast.error("All fields are required");
          return;
        }
        await api.post("/admin/users", form);
        toast.success("User created");
      }
      setDialogOpen(false);
      fetchUsers();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Operation failed");
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this user?")) return;
    try {
      await api.delete(`/admin/users/${id}`);
      toast.success("User deleted");
      fetchUsers();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Delete failed");
    }
  };

  return (
    <div className="space-y-6" data-testid="admin-page">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold font-['Rajdhani'] tracking-tight">User Management</h1>
          <p className="text-sm text-muted-foreground mt-1">Manage system users and roles</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="icon" onClick={fetchUsers} className="rounded-sm" data-testid="admin-refresh-btn">
            <RefreshCw className="w-4 h-4" />
          </Button>
          <Button onClick={openAdd} className="rounded-sm gap-2" data-testid="add-admin-user-btn">
            <Plus className="w-4 h-4" /> Add User
          </Button>
        </div>
      </div>

      {/* Role Summary */}
      <div className="grid grid-cols-3 gap-3">
        {["administrator", "viewer", "user"].map((role) => {
          const config = roleConfig[role];
          const count = users.filter((u) => u.role === role).length;
          return (
            <div key={role} className="bg-card border border-border rounded-sm p-4">
              <div className="flex items-center gap-2 mb-2">
                <config.icon className={`w-4 h-4 ${config.color}`} />
                <span className="text-xs text-muted-foreground capitalize">{role}s</span>
              </div>
              <p className="text-2xl font-bold font-['Rajdhani']">{count}</p>
            </div>
          );
        })}
      </div>

      {/* Table */}
      <div className="bg-card border border-border rounded-sm overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Full Name</TableHead>
              <TableHead>Username</TableHead>
              <TableHead>Role</TableHead>
              <TableHead className="hidden md:table-cell">Created At</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow><TableCell colSpan={5} className="text-center text-muted-foreground py-8">Loading...</TableCell></TableRow>
            ) : users.length === 0 ? (
              <TableRow><TableCell colSpan={5} className="text-center text-muted-foreground py-8">No users found</TableCell></TableRow>
            ) : (
              users.map((u) => {
                const config = roleConfig[u.role] || roleConfig.user;
                return (
                  <TableRow key={u.id} data-testid={`admin-row-${u.username}`}>
                    <TableCell className="font-medium text-sm">{u.full_name}</TableCell>
                    <TableCell className="font-mono text-xs">{u.username}</TableCell>
                    <TableCell>
                      <Badge className={`rounded-sm text-xs border capitalize ${config.bg} ${config.color}`}>
                        <config.icon className="w-3 h-3 mr-1" />{u.role}
                      </Badge>
                    </TableCell>
                    <TableCell className="hidden md:table-cell text-xs text-muted-foreground font-mono">
                      {u.created_at ? new Date(u.created_at).toLocaleDateString() : "-"}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openEdit(u)} data-testid={`admin-edit-${u.username}`}>
                          <Pencil className="w-3.5 h-3.5" />
                        </Button>
                        {u.id !== currentUser?.id && (
                          <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => handleDelete(u.id)} data-testid={`admin-delete-${u.username}`}>
                            <Trash2 className="w-3.5 h-3.5" />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      <p className="text-xs text-muted-foreground">Total: {users.length} users</p>

      {/* Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="rounded-sm bg-card border-border max-w-md" data-testid="admin-user-dialog">
          <DialogHeader>
            <DialogTitle className="font-['Rajdhani'] text-xl">{editing ? "Edit User" : "Add User"}</DialogTitle>
            <DialogDescription>
              {editing ? "Update user details and role." : "Create a new system user."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            {!editing && (
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Username</Label>
                <Input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} className="rounded-sm bg-background" data-testid="admin-form-username" />
              </div>
            )}
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Full Name</Label>
              <Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} className="rounded-sm bg-background" data-testid="admin-form-fullname" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">{editing ? "New Password (leave empty to keep)" : "Password"}</Label>
              <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className="rounded-sm bg-background" placeholder={editing ? "(unchanged)" : ""} data-testid="admin-form-password" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Role</Label>
              <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })}>
                <SelectTrigger className="rounded-sm bg-background" data-testid="admin-form-role">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="administrator">Administrator</SelectItem>
                  <SelectItem value="viewer">Viewer</SelectItem>
                  <SelectItem value="user">User</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} className="rounded-sm" data-testid="admin-form-cancel">Cancel</Button>
            <Button onClick={handleSave} className="rounded-sm" data-testid="admin-form-save">{editing ? "Update" : "Create"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
