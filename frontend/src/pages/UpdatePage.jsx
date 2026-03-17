import { useState, useEffect, useRef } from "react";
import api from "@/lib/api";
import { toast } from "sonner";
import {
  RefreshCw, Download, CheckCircle2, AlertTriangle,
  GitBranch, Clock, Terminal, Zap, CloudOff, Package,
  Info, ArrowUpCircle, Loader2, History, Wifi, Users
} from "lucide-react";

// ── Komponen helper ────────────────────────────────────────────────────────────
function Card({ children, className = "" }) {
  return (
    <div className={`rounded-xl border border-white/10 bg-white/[0.03] backdrop-blur p-5 ${className}`}>
      {children}
    </div>
  );
}

function StatusBadge({ status }) {
  const map = {
    idle:    { cls: "bg-slate-700 text-slate-300",  label: "Idle" },
    checking:{ cls: "bg-blue-500/20 text-blue-300", label: "Memeriksa..." },
    running: { cls: "bg-yellow-500/20 text-yellow-300 animate-pulse", label: "Updating..." },
    success: { cls: "bg-green-500/20 text-green-300", label: "Berhasil" },
    failed:  { cls: "bg-red-500/20 text-red-300",   label: "Gagal" },
  };
  const s = map[status] || map.idle;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${s.cls}`}>
      {status === "running" && <Loader2 className="w-3 h-3 animate-spin" />}
      {s.label}
    </span>
  );
}

// ── Halaman utama ─────────────────────────────────────────────────────────────
export default function UpdatePage() {
  const [appInfo, setAppInfo]       = useState(null);
  const [updateInfo, setUpdateInfo] = useState(null);
  const [status, setStatus]         = useState("idle"); // idle | checking | running | success | failed
  const [log, setLog]               = useState([]);
  const [elapsed, setElapsed]       = useState(0);
  const [checking, setChecking]     = useState(false);
  const [reloadCountdown, setReloadCountdown] = useState(0); // countdown detik sebelum reload
  const logRef  = useRef(null);
  const pollRef = useRef(null);
  const cdRef   = useRef(null); // countdown interval

  // Ambil info versi aplikasi saat mount
  useEffect(() => {
    fetchAppInfo();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (cdRef.current)   clearInterval(cdRef.current);
    };
  }, []);

  // Auto-scroll log ke bawah
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [log]);

  const fetchAppInfo = async () => {
    try {
      const r = await api.get("/system/app-info");
      setAppInfo(r.data);
    } catch (e) {
      console.error("app-info error", e);
    }
  };

  const checkUpdate = async () => {
    setChecking(true);
    setUpdateInfo(null);
    setStatus("checking");
    try {
      const r = await api.get("/system/check-update");
      setUpdateInfo(r.data);
      setStatus("idle");
    } catch (e) {
      setUpdateInfo({ has_update: false, message: "Gagal mengecek update: " + (e.response?.data?.detail || e.message) });
      setStatus("idle");
    } finally {
      setChecking(false);
    }
  };

  const startUpdate = async () => {
    if (status === "running") return;

    // Set initial state
    const initLog = ["🚀 Memulai proses update..."];
    setStatus("running");
    setLog(initLog);
    setElapsed(0);

    // Kecil delay agar React sempat render initial state sebelum blocking request
    await new Promise(r => setTimeout(r, 200));

    try {
      await api.post("/system/perform-update");
    } catch (e) {
      setLog(prev => [...prev, "❌ Gagal memulai update: " + (e.response?.data?.detail || e.message)]);
      setStatus("failed");
      return;
    }

    setLog(prev => [...prev, "⏳ Update berjalan di background..."]);

    // Catat waktu mulai di sisi frontend (independen dari server)
    const localStartTime = Date.now();
    let errCount = 0;
    let lastLogLength = 0;       // deteksi state reset
    let restartMsgShown = false; // cegah pesan restart duplikat
    const MAX_ERR = 6;           // 12 detik error jaringan = server restart

    const doSuccess = () => {
      clearInterval(pollRef.current);
      setStatus("success");
      toast.success("✅ Update berhasil! Halaman akan di-reload dalam 5 detik.", { duration: 8000 });
      setTimeout(fetchAppInfo, 1500);
      setTimeout(checkUpdate, 2500);
      let cd = 5;
      setReloadCountdown(cd);
      cdRef.current = setInterval(() => {
        cd -= 1;
        setReloadCountdown(cd);
        if (cd <= 0) { clearInterval(cdRef.current); window.location.reload(); }
      }, 1000);
    };

    const doFailed = (msg = "") => {
      clearInterval(pollRef.current);
      setStatus("failed");
      if (msg) setLog(prev => [...prev, msg]);
      toast.error("❌ Update gagal! Periksa log untuk detail.", { duration: 10000 });
    };

    pollRef.current = setInterval(async () => {
      const localElapsed = Math.round((Date.now() - localStartTime) / 1000);
      setElapsed(localElapsed);

      try {
        const r = await api.get("/system/update-status");
        const d = r.data;
        errCount = 0; // reset error counter — server masih up

        // ── Skenario 3: State reset setelah service restart ──────────────
        // Backend restart → _update_state kembali ke awal (running=F, done=F, log=[], elapsed≈0)
        // Deteksi: server elapsed sangat kecil tapi kita sudah jalan > 30 detik lokal
        const serverElapsed = d.elapsed || 0;
        if (
          !d.running && !d.done &&
          serverElapsed < 5 &&         // server baru saja restart (elapsed reset)
          localElapsed > 30 &&         // kita sudah jalan cukup lama
          d.log?.length === 0          // log kosong = state fresh
        ) {
          setLog(prev => [...prev, "✅ Server berhasil di-restart! Update selesai."]);
          doSuccess();
          return;
        }

        // Update log dari server jika ada data baru
        if (Array.isArray(d.log) && d.log.length > 0) {
          setLog(d.log);
          lastLogLength = d.log.length;
        }

        // ── Skenario 1: Update selesai normal ────────────────────────────
        if (d.done) {
          if (d.success) {
            setLog(prev => [...prev, "✅ Update selesai!"]);
            doSuccess();
          } else {
            doFailed(`❌ Update gagal: ${d.error || "Lihat log di atas"}`);
          }
          return;
        }

        // Masih running — update elapsed dari server jika lebih akurat
        if (serverElapsed > 0) setElapsed(serverElapsed);

      } catch {
        // ── Skenario 2: Server mati/restart (network error) ──────────────
        errCount += 1;

        if (errCount === 2 && !restartMsgShown) {
          restartMsgShown = true;
          setLog(prev => {
            const last = prev[prev.length - 1] || "";
            if (last.includes("Menunggu")) return prev;
            return [...prev, "⏳ Menunggu server restart... (ini normal)"];
          });
        }

        if (errCount >= MAX_ERR) {
          setLog(prev => [...prev, "✅ Server berhasil di-restart! Update selesai."]);
          doSuccess();
        }
      }
    }, 2000);
  };

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div
      className="min-h-screen p-4 sm:p-6 space-y-5"
      style={{ background: "linear-gradient(135deg, #020817 0%, #0a1628 100%)" }}
    >
      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-blue-500/20 border border-blue-500/40 flex items-center justify-center">
            <Package className="w-5 h-5 text-blue-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">Update Aplikasi</h1>
            <p className="text-xs text-slate-400">NOC Sentinel v3 — update dari GitHub</p>
          </div>
        </div>
        <StatusBadge status={status} />
      </div>

      {/* ── Versi Saat Ini ── */}
      <Card>
        <div className="flex items-center gap-2 mb-4">
          <Info className="w-4 h-4 text-blue-400" />
          <h2 className="text-sm font-semibold text-white">Versi Terpasang</h2>
        </div>
        {appInfo ? (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="rounded-lg bg-white/[0.03] border border-white/10 p-3">
              <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">Versi</p>
              <p className="text-lg font-bold font-mono text-blue-300">{appInfo.version || "v3.0"}</p>
            </div>
            <div className="rounded-lg bg-white/[0.03] border border-white/10 p-3">
              <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1 flex items-center gap-1">
                <GitBranch className="w-3 h-3" /> Commit
              </p>
              <p className="text-xs font-mono text-slate-300 break-all">{appInfo.commit?.slice(0, 12) || "—"}</p>
              <p className="text-[10px] text-slate-500 mt-0.5 truncate">{appInfo.message}</p>
            </div>
            <div className="rounded-lg bg-white/[0.03] border border-white/10 p-3">
              <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1 flex items-center gap-1">
                <Clock className="w-3 h-3" /> Tanggal Deploy
              </p>
              <p className="text-xs font-mono text-slate-300">{appInfo.date ? new Date(appInfo.date).toLocaleString("id-ID") : "—"}</p>
            </div>
          </div>
        ) : (
          <div className="animate-pulse flex gap-3">
            {[1,2,3].map(i => <div key={i} className="h-16 flex-1 rounded-lg bg-white/[0.05]" />)}
          </div>
        )}
      </Card>

      {/* ── Cek Update ── */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <CloudOff className="w-4 h-4 text-purple-400" />
            <h2 className="text-sm font-semibold text-white">Ketersediaan Update</h2>
          </div>
          <button
            onClick={checkUpdate}
            disabled={checking || status === "running"}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
              bg-blue-500/20 hover:bg-blue-500/30 text-blue-300 border border-blue-500/30
              disabled:opacity-40 disabled:cursor-not-allowed transition-all"
          >
            {checking ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            {checking ? "Memeriksa..." : "Cek Update"}
          </button>
        </div>

        {updateInfo ? (
          <div className={`rounded-lg border p-4 ${
            updateInfo.has_update
              ? "bg-yellow-500/10 border-yellow-500/30"
              : "bg-green-500/10 border-green-500/30"
          }`}>
            <div className="flex items-start gap-3">
              {updateInfo.has_update
                ? <ArrowUpCircle className="w-5 h-5 text-yellow-400 flex-shrink-0 mt-0.5" />
                : <CheckCircle2 className="w-5 h-5 text-green-400 flex-shrink-0 mt-0.5" />
              }
              <div className="flex-1 min-w-0">
                <p className={`font-semibold text-sm ${updateInfo.has_update ? "text-yellow-300" : "text-green-300"}`}>
                  {updateInfo.message}
                </p>
                {updateInfo.has_update && (
                  <div className="mt-2 space-y-1 text-xs text-slate-400">
                    {updateInfo.commits_behind > 0 && (
                      <p>📦 <span className="text-yellow-300 font-bold">{updateInfo.commits_behind}</span> commit di belakang</p>
                    )}
                    {updateInfo.latest_message && (
                      <p>🔖 Update terbaru: <span className="text-slate-300">{updateInfo.latest_message}</span></p>
                    )}
                    {updateInfo.latest_date && (
                      <p>📅 {new Date(updateInfo.latest_date).toLocaleString("id-ID")}</p>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : (
          <div className="rounded-lg bg-white/[0.02] border border-white/10 p-4 text-center text-slate-500 text-sm">
            Klik "Cek Update" untuk memeriksa versi terbaru dari GitHub
          </div>
        )}
      </Card>

      {/* ── Tombol Update & Log ── */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Terminal className="w-4 h-4 text-green-400" />
            <h2 className="text-sm font-semibold text-white">Update Sekarang</h2>
          </div>
          <button
            onClick={startUpdate}
            disabled={status === "running" || status === "checking"}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all
              ${status === "running"
                ? "bg-yellow-500/20 text-yellow-300 border border-yellow-500/30 cursor-not-allowed"
                : "bg-green-500/20 hover:bg-green-500/30 text-green-300 border border-green-500/30 hover:shadow-lg hover:shadow-green-500/10"
              } disabled:opacity-50`}
          >
            {status === "running"
              ? <><Loader2 className="w-4 h-4 animate-spin" /> Updating ({elapsed}s)</>
              : <><Download className="w-4 h-4" /> Jalankan Update</>
            }
          </button>
        </div>

        {/* Info proses */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4 text-[11px]">
          {[
            { icon: "1", label: "Git Pull" },
            { icon: "2", label: "Install Dependencies" },
            { icon: "3", label: "Build Frontend" },
            { icon: "4", label: "Restart Service" },
          ].map((step, i) => (
            <div key={i} className="rounded-lg bg-white/[0.02] border border-white/[0.07] p-2 text-center">
              <div className="w-5 h-5 rounded-full bg-blue-500/20 text-blue-300 text-xs font-bold flex items-center justify-center mx-auto mb-1">
                {step.icon}
              </div>
              <p className="text-slate-400">{step.label}</p>
            </div>
          ))}
        </div>

        {/* Log output */}
        <div
          ref={logRef}
          className="rounded-lg bg-black/50 border border-white/10 p-3 h-56 overflow-y-auto font-mono text-[11px] space-y-0.5"
          style={{ scrollBehavior: "smooth" }}
        >
          {log.length === 0 ? (
            <p className="text-slate-600 text-center pt-4">
              {status === "idle" ? "Log update akan tampil di sini..." : "Memulai..."}
            </p>
          ) : (
            log.map((line, i) => {
              const isSuccess = line.startsWith("✅");
              const isError   = line.startsWith("❌") || line.startsWith("⚠️");
              const isHeader  = line.startsWith("[");
              return (
                <p key={i} className={
                  isSuccess ? "text-green-400" :
                  isError   ? "text-red-400" :
                  isHeader  ? "text-blue-300 font-bold" :
                  "text-slate-400"
                }>
                  {line || "\u00a0"}
                </p>
              );
            })
          )}
          {status === "running" && (
            <p className="text-yellow-400 animate-pulse">▋</p>
          )}
        </div>

        {/* Status akhir */}
        {(status === "success" || status === "failed") && (
          <div className={`mt-3 rounded-lg border p-3 flex items-center gap-2 text-sm ${
            status === "success"
              ? "bg-green-500/10 border-green-500/30 text-green-300"
              : "bg-red-500/10 border-red-500/30 text-red-300"
          }`}>
            {status === "success"
              ? <><CheckCircle2 className="w-4 h-4 flex-shrink-0" />
                  <span>
                    Update berhasil! Aplikasi sudah diperbarui.
                    {reloadCountdown > 0 && (
                      <span className="ml-2 text-yellow-300 font-semibold">
                        Reload otomatis dalam {reloadCountdown}s...
                      </span>
                    )}
                  </span>
                </>
              : <><AlertTriangle className="w-4 h-4 flex-shrink-0" /> Update gagal. Cek log di atas untuk detail.</>
            }
          </div>
        )}
      </Card>

      {/* ── Tips ── */}
      <Card>
        <div className="flex items-start gap-2">
          <Zap className="w-4 h-4 text-yellow-400 flex-shrink-0 mt-0.5" />
          <div className="text-xs text-slate-400 space-y-1">
            <p className="text-slate-300 font-semibold">Tips Update</p>
            <p>• Update akan otomatis pull dari GitHub, install dependencies, build frontend, dan restart service.</p>
            <p>• Proses memerlukan 2–5 menit tergantung kecepatan server.</p>
            <p>• Aplikasi tidak akan offline sepenuhnya selama update — hanya restart service (+30 detik).</p>
            <p>• Atau update manual via terminal: <code className="bg-black/40 px-1 rounded">cd /opt/noc-sentinel-v3 &amp;&amp; git pull &amp;&amp; sudo bash update.sh</code></p>
          </div>
        </div>
      </Card>

      {/* ── Changelog ── */}
      <Card>
        <div className="flex items-center gap-2 mb-4">
          <History className="w-4 h-4 text-purple-400" />
          <h2 className="text-sm font-semibold text-white">Changelog</h2>
          <span className="text-[10px] text-slate-500">Riwayat perubahan fitur &amp; bugfix</span>
        </div>
        <div className="space-y-4">

          {/* v3.3.0 */}
          <div className="rounded-lg border border-purple-500/20 bg-purple-500/[0.04] p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold font-mono text-purple-300 bg-purple-500/15 px-2 py-0.5 rounded">v3.3.0</span>
                <span className="text-[11px] font-semibold text-white">PPPoE &amp; Hotspot Active Badges</span>
              </div>
              <span className="text-[10px] text-slate-500">Mar 2026</span>
            </div>
            <ul className="space-y-1 text-[11px] text-slate-400">
              <li className="flex items-start gap-1.5">
                <Users className="w-3 h-3 text-cyan-400 mt-0.5 flex-shrink-0" />
                <span>Wall Display: badge <span className="text-cyan-300 font-mono">PPPoE Active</span> dan <span className="text-orange-300 font-mono">Hotspot Active</span> di setiap device card</span>
              </li>
              <li className="flex items-start gap-1.5">
                <Users className="w-3 h-3 text-cyan-400 mt-0.5 flex-shrink-0" />
                <span>Header Wall Display: badge akumulasi total PPPoE + Hotspot dari semua device online</span>
              </li>
              <li className="flex items-start gap-1.5">
                <CheckCircle2 className="w-3 h-3 text-green-400 mt-0.5 flex-shrink-0" />
                <span>Data diambil dari <span className="font-mono text-slate-300">ppp/active</span> dan <span className="font-mono text-slate-300">ip/hotspot/active</span> via REST API MikroTik secara paralel saat polling</span>
              </li>
            </ul>
          </div>

          {/* v3.2.0 */}
          <div className="rounded-lg border border-blue-500/20 bg-blue-500/[0.04] p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold font-mono text-blue-300 bg-blue-500/15 px-2 py-0.5 rounded">v3.2.0</span>
                <span className="text-[11px] font-semibold text-white">Fix: SFP Interface &amp; Winbox Mobile</span>
              </div>
              <span className="text-[10px] text-slate-500">Mar 2026</span>
            </div>
            <ul className="space-y-1 text-[11px] text-slate-400">
              <li className="flex items-start gap-1.5">
                <CheckCircle2 className="w-3 h-3 text-green-400 mt-0.5 flex-shrink-0" />
                <span><span className="text-green-300 font-semibold">[Bug Fix]</span> SFP interface (CCR2004-16G-2S+) tidak ada data bandwidth di Wall Display — limit polling dinaikkan dari 16 → 64 interface dengan prioritas ISP &gt; SFP &gt; ether</span>
              </li>
              <li className="flex items-start gap-1.5">
                <CheckCircle2 className="w-3 h-3 text-green-400 mt-0.5 flex-shrink-0" />
                <span><span className="text-green-300 font-semibold">[Bug Fix]</span> Winbox Mobile error HTTPS — URL format diubah ke <span className="font-mono text-slate-300">winbox://address/user/pass</span> untuk kompatibilitas Winbox App Android/iOS</span>
              </li>
              <li className="flex items-start gap-1.5">
                <CheckCircle2 className="w-3 h-3 text-green-400 mt-0.5 flex-shrink-0" />
                <span>Endpoint <span className="font-mono text-slate-300">/winbox-url</span> kini dapat diakses semua user (bukan hanya admin)</span>
              </li>
            </ul>
          </div>

          {/* v3.1.0 */}
          <div className="rounded-lg border border-white/10 bg-white/[0.02] p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold font-mono text-slate-400 bg-white/10 px-2 py-0.5 rounded">v3.1.0</span>
                <span className="text-[11px] font-semibold text-white">Wall Display Refactor &amp; Sparkline</span>
              </div>
              <span className="text-[10px] text-slate-500">Feb 2026</span>
            </div>
            <ul className="space-y-1 text-[11px] text-slate-400">
              <li className="flex items-start gap-1.5">
                <Wifi className="w-3 h-3 text-blue-400 mt-0.5 flex-shrink-0" />
                <span>Wall Display: sparkline chart per device card (live 20-point bandwidth history)</span>
              </li>
              <li className="flex items-start gap-1.5">
                <Wifi className="w-3 h-3 text-blue-400 mt-0.5 flex-shrink-0" />
                <span>Header: total bandwidth ISP accumulated, clock real-time, event ticker</span>
              </li>
              <li className="flex items-start gap-1.5">
                <CheckCircle2 className="w-3 h-3 text-green-400 mt-0.5 flex-shrink-0" />
                <span>Halaman Update dengan one-click update dari GitHub</span>
              </li>
            </ul>
          </div>

        </div>
      </Card>
    </div>
  );
}
