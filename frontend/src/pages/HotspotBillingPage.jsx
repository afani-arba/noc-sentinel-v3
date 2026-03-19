import { useState, useEffect, useRef } from "react";
import api from "@/lib/api";
import { useAuth } from "@/App";
import { Ticket, Server, Printer, Loader2, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";

export default function HotspotBillingPage() {
  const { user } = useAuth();
  const isViewer = user?.role === "viewer";
  const [devices, setDevices] = useState([]);
  const [selectedDevice, setSelectedDevice] = useState("");
  const [profiles, setProfiles] = useState([]);
  const [servers, setServers] = useState([]);
  const [profilesLoading, setProfilesLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  
  const [generatedVouchers, setGeneratedVouchers] = useState([]);

  const [form, setForm] = useState({
    count: 10,
    prefix: "VC",
    length: 6,
    profile: "default",
    server: "all",
    price: "2000",
    validity: "1 Hari"
  });

  useEffect(() => {
    api.get("/devices").then(r => {
      setDevices(r.data);
      if (r.data.length === 1) setSelectedDevice(r.data[0].id);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedDevice) { setProfiles([]); setServers([]); return; }
    setProfilesLoading(true);
    Promise.all([
      api.get("/hotspot-profiles", { params: { device_id: selectedDevice } }).then(r => r.data).catch(() => []),
      api.get("/hotspot-servers", { params: { device_id: selectedDevice } }).then(r => r.data).catch(() => []),
    ]).then(([prof, srv]) => {
      setProfiles(prof || []);
      setServers(srv || []);
    }).finally(() => setProfilesLoading(false));
  }, [selectedDevice]);

  const generateRandomString = (length) => {
    const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // Removed similar looking characters
    let result = "";
    for (let i = 0; i < length; i++) {
        result += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return result;
  };

  const handleGenerate = async () => {
    if (!selectedDevice) return toast.error("Pilih router MikroTik terlebih dahulu!");
    if (form.count < 1 || form.count > 100) return toast.error("Jumlah voucher harus antara 1-100");

    setGenerating(true);
    try {
        const usersToCreate = [];
        const newVouchers = [];

        for (let i = 0; i < form.count; i++) {
            const randomCode = generateRandomString(form.length);
            const username = `${form.prefix}${randomCode}`;
            const password = randomCode.substring(0, 4); // simplistic password for vouchers

            usersToCreate.push({
                name: username,
                password: password,
                profile: form.profile,
                server: form.server,
                comment: `Voucher Generated ${new Date().toISOString().split('T')[0]}`
            });

            newVouchers.push({
                username,
                password,
                profile: form.profile,
                price: form.price,
                validity: form.validity
            });
        }

        const res = await api.post(`/hotspot-users/batch?device_id=${selectedDevice}`, { users: usersToCreate });
        toast.success(`Berhasil membuat ${usersToCreate.length} voucher!`);
        setGeneratedVouchers(newVouchers);

    } catch (e) {
        toast.error(e.response?.data?.detail || "Gagal membuat voucher");
    } finally {
        setGenerating(false);
    }
  };

  const handlePrint = () => {
      if (generatedVouchers.length === 0) return toast.info("Belum ada voucher yang digenerate");
      window.print();
  };

  return (
    <div className="space-y-4 pb-16">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 print:hidden">
        <div>
          <h1 className="text-xl sm:text-2xl md:text-3xl font-bold font-['Rajdhani'] tracking-tight">Billing Hotspot</h1>
          <p className="text-xs sm:text-sm text-muted-foreground">Voucher Generator & Management System</p>
        </div>
      </div>

      {!selectedDevice && (
          <div className="bg-card border border-border rounded-sm p-4 print:hidden">
            <label className="text-xs uppercase tracking-widest text-muted-foreground mb-2 block">Pilih Router MikroTik</label>
            <Select value={selectedDevice} onValueChange={setSelectedDevice}>
              <SelectTrigger className="w-full sm:w-64 rounded-sm bg-background text-xs h-10">
                <SelectValue placeholder="Pilih device..." />
              </SelectTrigger>
              <SelectContent>
                {devices.map(d => (
                  <SelectItem key={d.id} value={d.id}>
                    <span className="flex items-center gap-2">
                      <div className={`w-2 h-2 rounded-full ${d.status === "online" ? "bg-green-500" : "bg-red-500"}`} />
                      {d.name}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
      )}

      {selectedDevice && (
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 print:hidden">
            {/* Form Generator */}
            <div className="bg-card border border-border rounded-sm p-5 lg:col-span-1 flex flex-col gap-4">
                <div>
                    <h2 className="text-md font-semibold flex items-center gap-2 mb-1"><Ticket className="w-4 h-4 text-primary"/> Generator Setup</h2>
                    <p className="text-xs text-muted-foreground">Atur parameter batch voucher</p>
                </div>

                <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">Jumlah Voucher (1-100)</Label>
                    <Input type="number" min={1} max={100} value={form.count} onChange={e => setForm({...form, count: parseInt(e.target.value) || 0})} className="h-9 text-sm rounded-sm" />
                </div>

                <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Prefix</Label>
                        <Input value={form.prefix} onChange={e => setForm({...form, prefix: e.target.value})} className="h-9 text-sm rounded-sm uppercase" />
                    </div>
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Length</Label>
                        <Input type="number" min={4} max={12} value={form.length} onChange={e => setForm({...form, length: parseInt(e.target.value) || 4})} className="h-9 text-sm rounded-sm" />
                    </div>
                </div>

                <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">Hotspot Profile</Label>
                    <Select value={form.profile} onValueChange={v => setForm({ ...form, profile: v })}>
                        <SelectTrigger className="rounded-sm bg-background h-9">
                            <SelectValue placeholder="Pilih profile..." />
                        </SelectTrigger>
                        <SelectContent>
                            {profiles.length > 0 ? profiles.map(p => (
                                <SelectItem key={p.name} value={p.name}>{p.name}</SelectItem>
                            )) : <SelectItem value="default">default</SelectItem>}
                        </SelectContent>
                    </Select>
                </div>

                <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Harga Label</Label>
                        <Input value={form.price} onChange={e => setForm({...form, price: e.target.value})} className="h-9 text-sm rounded-sm" />
                    </div>
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Masa Aktif Label</Label>
                        <Input value={form.validity} onChange={e => setForm({...form, validity: e.target.value})} className="h-9 text-sm rounded-sm" />
                    </div>
                </div>

                <Button onClick={handleGenerate} disabled={generating || isViewer} className="w-full mt-2 rounded-sm gap-2">
                    {generating ? <Loader2 className="w-4 h-4 animate-spin"/> : <Plus className="w-4 h-4" />}
                    Generate {form.count} Voucher
                </Button>
            </div>

            {/* Preview & Print Area */}
            <div className="bg-card border border-border rounded-sm lg:col-span-3 flex flex-col min-h-[500px]">
                <div className="p-4 border-b border-border flex justify-between items-center bg-muted/20">
                    <h2 className="text-md font-semibold font-['Rajdhani']">Papan Cetak Voucher</h2>
                    <Button onClick={handlePrint} variant="outline" size="sm" className="gap-2 rounded-sm" disabled={generatedVouchers.length === 0}>
                        <Printer className="w-4 h-4"/> Cetak Sekarang
                    </Button>
                </div>
                
                <div className="p-4 flex-1 bg-neutral-100 dark:bg-neutral-900 overflow-auto">
                    {generatedVouchers.length === 0 ? (
                        <div className="h-full flex flex-col items-center justify-center text-muted-foreground">
                            <Ticket className="w-12 h-12 mb-3 opacity-20" />
                            <p className="text-sm">Silakan generate voucher di panel sebelah kiri</p>
                            <p className="text-xs opacity-70">Hasil voucher siap cetak akan muncul di sini</p>
                        </div>
                    ) : (
                        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3" id="print-area">
                            {generatedVouchers.map((v, i) => (
                                <div key={i} className="bg-white dark:bg-black text-black dark:text-white border-2 border-black dark:border-white rounded p-3 shadow-sm flex flex-col print:break-inside-avoid print:border-black print:text-black">
                                    <div className="text-center font-bold text-sm tracking-widest border-b-2 border-dashed border-black dark:border-white pb-1 mb-2 print:border-black">HOTSPOT</div>
                                    <div className="flex-1 flex flex-col items-center justify-center mb-2">
                                        <span className="text-[10px] uppercase tracking-wider mb-0.5 opacity-80">Kode / Username</span>
                                        <span className="text-lg font-mono font-bold leading-tight tracking-tight">{v.username}</span>
                                        <span className="text-[10px] uppercase tracking-wider mt-1.5 opacity-80">Password</span>
                                        <span className="text-sm font-mono font-bold leading-tight">{v.password}</span>
                                    </div>
                                    <div className="flex justify-between items-end border-t border-black dark:border-white pt-1.5 mt-auto text-[9px] print:border-black">
                                        <div className="font-semibold uppercase truncate pr-1">{v.validity}</div>
                                        <div className="font-bold whitespace-nowrap">Rp {parseInt(v.price).toLocaleString('id-ID')}</div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
          </div>
      )}

      {/* Actual Print Styles Injected Globally for this page */}
      <style dangerouslySetInnerHTML={{__html: `
        @media print {
            body * {
                visibility: hidden;
            }
            #print-area, #print-area * {
                visibility: visible;
            }
            #print-area {
                position: absolute;
                left: 0;
                top: 0;
                width: 100%;
                display: grid !important;
                grid-template-columns: repeat(4, 1fr) !important;
                gap: 10px !important;
                padding: 10px;
                background: white !important;
            }
            @page { margin: 0.5cm; }
        }
      `}} />
    </div>
  );
}
