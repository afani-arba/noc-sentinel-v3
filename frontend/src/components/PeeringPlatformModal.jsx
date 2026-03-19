import { useState, useEffect } from "react";
import api from "@/lib/api";
import { Plus, Trash2, Edit2, Upload, Download, X, Save, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

export default function PeeringPlatformModal({ onClose, onChange }) {
  const [platforms, setPlatforms] = useState([]);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/peering-eye/platforms");
      setPlatforms(data);
    } catch {
      toast.error("Gagal memuat platform");
    }
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const handleSave = async (e) => {
    e.preventDefault();
    try {
      if (form.id) {
        await api.put(`/peering-eye/platforms/${form.id}`, form);
        toast.success("Platform diperbarui");
      } else {
        await api.post("/peering-eye/platforms", form);
        toast.success("Platform ditambahkan");
      }
      setForm(null);
      load();
      if (onChange) onChange();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Gagal menyimpan");
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Hapus platform ini?")) return;
    try {
      await api.delete(`/peering-eye/platforms/${id}`);
      toast.success("Dihapus");
      load();
      if (onChange) onChange();
    } catch {
      toast.error("Gagal menghapus");
    }
  };

  const handleExport = () => {
    const dataStr = JSON.stringify(platforms, null, 2);
    const blob = new Blob([dataStr], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "peering_platforms.json";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  // Simplified import (relies on POST endpoints directly for bulk)
  const handleImport = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async (event) => {
      try {
        const json = JSON.parse(event.target.result);
        if (!Array.isArray(json)) throw new Error("Format tidak valid");
        for (const p of json) {
          // just ignore id and is_active internally if not needed
          await api.post("/peering-eye/platforms", {
            name: p.name,
            regex_pattern: p.regex_pattern,
            icon: p.icon || "🌐",
            color: p.color || "#64748b"
          }).catch(e => console.error(e)); // Ignore duplicate errors
        }
        toast.success("Import selesai (mengabaikan duplikat)");
        load();
        if (onChange) onChange();
      } catch (err) {
        toast.error("Gagal import: " + err.message);
      }
    };
    reader.readAsText(file);
    e.target.value = ""; // reset
  };

  return (
    <div className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-card w-full max-w-3xl rounded-lg shadow-xl border border-border p-5 relative max-h-[90vh] flex flex-col">
        <Button variant="ghost" size="icon" className="absolute right-3 top-3 h-6 w-6" onClick={onClose}>
          <X className="w-4 h-4" />
        </Button>
        <h3 className="text-lg font-bold mb-1">Kelola Kategori Platform</h3>
        <p className="text-xs text-muted-foreground mb-4">
          Atur regex pencocokan domain untuk menangkap traffic Peering-Eye.
        </p>

        <div className="flex gap-2 mb-4">
          <Button size="sm" onClick={() => setForm({ name: "", regex_pattern: "", icon: "🌐", color: "#64748b", alert_threshold_hits: 0, alert_threshold_mb: 0 })} className="gap-1.5 h-8 text-xs">
            <Plus className="w-3.5 h-3.5" /> Tambah Platform
          </Button>
          <Button size="sm" variant="outline" onClick={handleExport} className="gap-1.5 h-8 text-xs">
            <Download className="w-3.5 h-3.5" /> Export JSON
          </Button>
          <Label htmlFor="import-json" className="cursor-pointer">
            <div className="inline-flex items-center justify-center rounded-md text-xs font-medium border border-input bg-background hover:bg-accent hover:text-accent-foreground h-8 px-3 gap-1.5 transition-colors">
              <Upload className="w-3.5 h-3.5" /> Import JSON
            </div>
          </Label>
          <input id="import-json" type="file" accept=".json" className="hidden" onChange={handleImport} />
          <div className="flex-1" />
          <Button size="sm" variant="ghost" className="h-8 gap-1 text-xs" onClick={load}>
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>

        {form && (
          <div className="bg-secondary/20 p-4 rounded-md border border-border mb-4">
            <form onSubmit={handleSave} className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label className="text-xs">Nama Platform</Label>
                  <Input required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} className="h-8 text-xs" placeholder="Contoh: Judi Online" />
                </div>
                <div className="flex gap-3">
                  <div className="space-y-1 w-20">
                    <Label className="text-xs">Ikon</Label>
                    <Input required value={form.icon} onChange={e => setForm({ ...form, icon: e.target.value })} className="h-8 text-xs text-center" />
                  </div>
                  <div className="space-y-1 flex-1">
                    <Label className="text-xs">Warna (Hex)</Label>
                    <div className="flex gap-2">
                      <Input required type="color" value={form.color} onChange={e => setForm({ ...form, color: e.target.value })} className="w-8 h-8 p-0 border-0 cursor-pointer" />
                      <Input required value={form.color} onChange={e => setForm({ ...form, color: e.target.value })} className="h-8 text-xs font-mono" />
                    </div>
                  </div>
                </div>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Regex Pattern (Pencocokan Domain)</Label>
                <Input required value={form.regex_pattern} onChange={e => setForm({ ...form, regex_pattern: e.target.value })} className="h-8 text-xs font-mono" placeholder="(slot88|togel|maxwin)" />
                <p className="text-[10px] text-muted-foreground mt-1">Gunakan format regex Python. Contoh: `(youtube\.com|youtu\.be)`</p>
              </div>
              <div className="grid grid-cols-2 gap-3 mt-2 border-t border-border pt-3">
                <div className="space-y-1">
                  <Label className="text-xs">Peringatan Kuota (MB)</Label>
                  <Input type="number" required value={form.alert_threshold_mb} onChange={e => setForm({ ...form, alert_threshold_mb: parseInt(e.target.value) || 0 })} className="h-8 text-xs" />
                  <p className="text-[9px] text-muted-foreground">0 = Nonaktif</p>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Peringatan DNS Hits</Label>
                  <Input type="number" required value={form.alert_threshold_hits} onChange={e => setForm({ ...form, alert_threshold_hits: parseInt(e.target.value) || 0 })} className="h-8 text-xs" />
                  <p className="text-[9px] text-muted-foreground">0 = Nonaktif</p>
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" size="sm" variant="outline" onClick={() => setForm(null)} className="h-8 text-xs">Batal</Button>
                <Button type="submit" size="sm" className="h-8 text-xs gap-1"><Save className="w-3.5 h-3.5" /> Simpan</Button>
              </div>
            </form>
          </div>
        )}

        <div className="flex-1 overflow-auto border border-border rounded-md">
          <table className="w-full text-left text-xs">
            <thead className="bg-secondary/40 sticky top-0 z-10 backdrop-blur-md">
              <tr className="border-b border-border">
                <th className="px-3 py-2 font-medium text-muted-foreground w-10">Ikon</th>
                <th className="px-3 py-2 font-medium text-muted-foreground">Nama Platform</th>
                <th className="px-3 py-2 font-medium text-muted-foreground">Regex Pattern</th>
                <th className="px-3 py-2 font-medium text-muted-foreground w-16 text-right">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {platforms.map(p => (
                <tr key={p.id} className="border-b border-border/20 hover:bg-secondary/20">
                  <td className="px-3 py-2 text-center text-base">{p.icon}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: p.color }} />
                      <span className="font-semibold">{p.name}</span>
                    </div>
                  </td>
                  <td className="px-3 py-2 font-mono text-[10px] truncate max-w-[300px]" title={p.regex_pattern}>
                    {p.regex_pattern}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex justify-end gap-1">
                      <Button size="icon" variant="ghost" className="h-6 w-6" onClick={() => setForm(p)}>
                        <Edit2 className="w-3 h-3 text-blue-400" />
                      </Button>
                      <Button size="icon" variant="ghost" className="h-6 w-6" onClick={() => handleDelete(p.id)}>
                        <Trash2 className="w-3 h-3 text-red-400" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
              {platforms.length === 0 && !loading && (
                <tr>
                  <td colSpan={4} className="py-8 text-center text-muted-foreground">Belum ada platform.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

      </div>
    </div>
  );
}
