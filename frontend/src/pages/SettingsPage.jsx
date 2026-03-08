import { useState } from "react";
import api from "@/lib/api";
import { Download, RefreshCw, CheckCircle2, AlertCircle, Github, Terminal, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";

export default function SettingsPage() {
  const [checking, setChecking] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [updateInfo, setUpdateInfo] = useState(null);
  const [updateLog, setUpdateLog] = useState([]);

  const checkUpdate = async () => {
    setChecking(true);
    setUpdateInfo(null);
    try {
      const r = await api.get("/system/check-update");
      setUpdateInfo(r.data);
      if (r.data.has_update) {
        toast.info("Update tersedia!");
      } else {
        toast.success("Aplikasi sudah versi terbaru");
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || "Gagal cek update");
    }
    setChecking(false);
  };

  const performUpdate = async () => {
    if (!updateInfo?.has_update) {
      toast.error("Tidak ada update yang tersedia");
      return;
    }
    
    setUpdating(true);
    setUpdateLog(["Memulai proses update..."]);
    
    try {
      const r = await api.post("/system/perform-update");
      setUpdateLog(r.data.log || []);
      
      if (r.data.success) {
        toast.success("Update berhasil! Silakan refresh halaman.");
        setUpdateInfo(null);
      } else {
        toast.error("Update gagal: " + (r.data.error || "Unknown error"));
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || "Update gagal");
      setUpdateLog(prev => [...prev, `Error: ${e.response?.data?.detail || e.message}`]);
    }
    setUpdating(false);
  };

  return (
    <div className="space-y-6" data-testid="settings-page">
      <div>
        <h1 className="text-3xl font-bold font-['Rajdhani'] tracking-tight">Pengaturan</h1>
        <p className="text-sm text-muted-foreground mt-1">Pengaturan sistem dan update aplikasi</p>
      </div>

      {/* Update Section */}
      <div className="bg-card border border-border rounded-sm p-6" data-testid="update-section">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-sm bg-primary/10 flex items-center justify-center">
            <Github className="w-5 h-5 text-primary" />
          </div>
          <div>
            <h2 className="text-lg font-semibold font-['Rajdhani']">Update Aplikasi</h2>
            <p className="text-xs text-muted-foreground">Pull update terbaru dari GitHub repository</p>
          </div>
        </div>

        <div className="space-y-4">
          {/* Current Version Info */}
          <div className="flex flex-wrap gap-3 items-center text-sm">
            <Badge variant="outline" className="rounded-sm gap-1">
              <Clock className="w-3 h-3" />
              Versi Saat Ini
            </Badge>
            <span className="text-muted-foreground font-mono text-xs">
              {updateInfo?.current_commit ? updateInfo.current_commit.slice(0, 7) : "Belum dicek"}
            </span>
          </div>

          {/* Update Status */}
          {updateInfo && (
            <div className={`p-4 rounded-sm border ${updateInfo.has_update ? 'bg-yellow-500/10 border-yellow-500/30' : 'bg-green-500/10 border-green-500/30'}`}>
              <div className="flex items-center gap-2">
                {updateInfo.has_update ? (
                  <>
                    <Download className="w-4 h-4 text-yellow-500" />
                    <span className="text-yellow-500 font-medium">Update Tersedia!</span>
                  </>
                ) : (
                  <>
                    <CheckCircle2 className="w-4 h-4 text-green-500" />
                    <span className="text-green-500 font-medium">Aplikasi sudah versi terbaru</span>
                  </>
                )}
              </div>
              {updateInfo.has_update && updateInfo.latest_commit && (
                <div className="mt-2 text-xs text-muted-foreground">
                  <p>Commit terbaru: <code className="bg-secondary px-1 rounded">{updateInfo.latest_commit.slice(0, 7)}</code></p>
                  {updateInfo.commits_behind && <p>Tertinggal {updateInfo.commits_behind} commit</p>}
                </div>
              )}
              {updateInfo.message && (
                <p className="mt-2 text-xs text-muted-foreground">{updateInfo.message}</p>
              )}
            </div>
          )}

          {/* Update Log */}
          {updateLog.length > 0 && (
            <div className="bg-secondary/30 border border-border rounded-sm p-3">
              <div className="flex items-center gap-2 mb-2">
                <Terminal className="w-4 h-4 text-muted-foreground" />
                <span className="text-xs text-muted-foreground font-medium">Log Update</span>
              </div>
              <div className="font-mono text-xs space-y-1 max-h-48 overflow-y-auto">
                {updateLog.map((log, i) => (
                  <div key={i} className={`${log.startsWith('Error') ? 'text-red-400' : log.startsWith('Success') ? 'text-green-400' : 'text-foreground/70'}`}>
                    {log}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Action Buttons */}
          <div className="flex flex-wrap gap-3 pt-2">
            <Button
              variant="outline"
              onClick={checkUpdate}
              disabled={checking || updating}
              className="rounded-sm gap-2"
              data-testid="check-update-btn"
            >
              <RefreshCw className={`w-4 h-4 ${checking ? 'animate-spin' : ''}`} />
              {checking ? "Mengecek..." : "Cek Update"}
            </Button>
            
            <Button
              onClick={performUpdate}
              disabled={updating || !updateInfo?.has_update}
              className="rounded-sm gap-2"
              data-testid="perform-update-btn"
            >
              <Download className={`w-4 h-4 ${updating ? 'animate-bounce' : ''}`} />
              {updating ? "Mengupdate..." : "Update Sekarang"}
            </Button>
          </div>

          {/* Instructions */}
          <div className="mt-4 p-3 bg-secondary/20 rounded-sm border border-dashed border-border">
            <p className="text-xs text-muted-foreground">
              <strong>Petunjuk:</strong> Pastikan Anda telah melakukan "Save to GitHub" di Emergent sebelum 
              melakukan update di server self-hosted. Proses update akan melakukan <code className="bg-secondary px-1 rounded">git pull</code> dari repository.
            </p>
          </div>
        </div>
      </div>

      {/* System Info */}
      <div className="bg-card border border-border rounded-sm p-6">
        <h2 className="text-lg font-semibold font-['Rajdhani'] mb-4">Informasi Sistem</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
          <div className="flex justify-between p-2 bg-secondary/20 rounded-sm">
            <span className="text-muted-foreground">Aplikasi</span>
            <span className="font-mono">NOC-SENTINEL v2.4</span>
          </div>
          <div className="flex justify-between p-2 bg-secondary/20 rounded-sm">
            <span className="text-muted-foreground">Backend</span>
            <span className="font-mono">FastAPI + Python</span>
          </div>
          <div className="flex justify-between p-2 bg-secondary/20 rounded-sm">
            <span className="text-muted-foreground">Frontend</span>
            <span className="font-mono">React + Tailwind</span>
          </div>
          <div className="flex justify-between p-2 bg-secondary/20 rounded-sm">
            <span className="text-muted-foreground">Database</span>
            <span className="font-mono">MongoDB</span>
          </div>
        </div>
      </div>
    </div>
  );
}
