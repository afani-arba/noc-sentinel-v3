import { useState } from "react";
import api from "@/lib/api";
import { FileText, Download, BarChart3, TrendingUp, Server, Activity } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line, Legend } from "recharts";
import { toast } from "sonner";
import jsPDF from "jspdf";
import autoTable from "jspdf-autotable";

const ttStyle = { contentStyle: { backgroundColor: "#121214", borderColor: "#27272a", borderRadius: "4px", color: "#fafafa", fontSize: "12px", fontFamily: "'JetBrains Mono', monospace" } };

export default function ReportsPage() {
  const [period, setPeriod] = useState("daily");
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);

  const generateReport = async () => {
    setLoading(true);
    try {
      const r = await api.post("/reports/generate", { period });
      setReport(r.data);
      toast.success("Report generated");
    } catch (e) { toast.error("Failed to generate report"); }
    setLoading(false);
  };

  const exportPDF = () => {
    if (!report) return;
    const doc = new jsPDF();
    const pw = doc.internal.pageSize.getWidth();

    doc.setFontSize(20); doc.setTextColor(59,130,246); doc.text("NOC-SENTINEL", 14, 20);
    doc.setFontSize(10); doc.setTextColor(120,120,120); doc.text("MikroTik Monitoring Report", 14, 27);
    doc.setFontSize(16); doc.setTextColor(30,30,30); doc.text(report.label, 14, 40);
    doc.setFontSize(9); doc.setTextColor(100,100,100);
    doc.text(`Generated: ${new Date(report.generated_at).toLocaleString()}`, 14, 48);
    doc.text(`Period: ${new Date(report.start_date).toLocaleDateString()} - ${new Date(report.end_date).toLocaleDateString()}`, 14, 54);
    doc.setDrawColor(200,200,200); doc.line(14, 58, pw-14, 58);

    doc.setFontSize(12); doc.setTextColor(30,30,30); doc.text("Summary", 14, 66);
    const s = report.summary;
    autoTable(doc, { startY:70, head:[["Metric","Value"]], body:[
      ["Devices Online", `${s.devices.online} / ${s.devices.total}`],
      ["Avg Download", `${s.avg_bandwidth.download} Mbps`], ["Avg Upload", `${s.avg_bandwidth.upload} Mbps`],
      ["Peak Download", `${s.peak_bandwidth.download} Mbps`], ["Peak Upload", `${s.peak_bandwidth.upload} Mbps`],
      ["Avg Ping", `${s.avg_ping} ms`], ["Avg Jitter", `${s.avg_jitter} ms`],
    ], theme:"striped", headStyles:{fillColor:[59,130,246]}, styles:{fontSize:9} });

    if (report.device_summary?.length) {
      const y = doc.lastAutoTable.finalY + 10;
      doc.setFontSize(12); doc.text("Device Summary", 14, y);
      autoTable(doc, { startY:y+4, head:[["Device","IP","Model","Status","CPU","Memory","Uptime"]],
        body: report.device_summary.map(d => [d.name, d.ip_address, d.model, d.status, `${d.cpu}%`, `${d.memory}%`, d.uptime]),
        theme:"striped", headStyles:{fillColor:[16,185,129]}, styles:{fontSize:8} });
    }

    const pc = doc.internal.getNumberOfPages();
    for (let i=1; i<=pc; i++) { doc.setPage(i); doc.setFontSize(8); doc.setTextColor(150,150,150); doc.text(`NOC-SENTINEL | Page ${i}/${pc}`, pw/2, doc.internal.pageSize.getHeight()-10, {align:"center"}); }
    doc.save(`noc-sentinel-${report.period}-report.pdf`);
    toast.success("PDF exported");
  };

  return (
    <div className="space-y-4 pb-16" data-testid="reports-page">
      <div><h1 className="text-xl sm:text-2xl md:text-3xl font-bold font-['Rajdhani'] tracking-tight">Reports</h1><p className="text-xs sm:text-sm text-muted-foreground">Generate and export network reports</p></div>

      <div className="bg-card border border-border rounded-sm p-3 sm:p-5">
        <h3 className="text-sm sm:text-base font-semibold font-['Rajdhani'] mb-3 sm:mb-4">Report Configuration</h3>
        <div className="flex flex-col sm:flex-row gap-2 sm:gap-3">
          <div className="space-y-1.5 flex-1">
            <label className="text-[10px] sm:text-xs text-muted-foreground uppercase tracking-wider">Period</label>
            <Select value={period} onValueChange={setPeriod}>
              <SelectTrigger className="rounded-sm bg-background h-9 text-xs" data-testid="report-period-select"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="daily">Daily (24 Hours)</SelectItem>
                <SelectItem value="weekly">Weekly (7 Days)</SelectItem>
                <SelectItem value="monthly">Monthly (30 Days)</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex gap-2 sm:items-end">
            <Button onClick={generateReport} disabled={loading} size="sm" className="rounded-sm gap-2 flex-1 sm:flex-none" data-testid="generate-report-btn"><BarChart3 className="w-4 h-4" />{loading?"...":"Generate"}</Button>
            {report && <Button onClick={exportPDF} variant="outline" size="sm" className="rounded-sm gap-2" data-testid="export-pdf-btn"><Download className="w-4 h-4" /> PDF</Button>}
          </div>
        </div>
      </div>

      {report && (
        <div className="space-y-3 sm:space-y-4 animate-fade-in">
          <div className="bg-card border border-border rounded-sm p-3 sm:p-5">
            <div className="flex items-center justify-between mb-3 sm:mb-4">
              <div className="flex items-center gap-2 sm:gap-3"><FileText className="w-4 h-4 sm:w-5 sm:h-5 text-primary" /><div><h3 className="text-base sm:text-lg font-semibold font-['Rajdhani']">{report.label}</h3><p className="text-[10px] sm:text-xs text-muted-foreground font-mono">{new Date(report.start_date).toLocaleDateString()} - {new Date(report.end_date).toLocaleDateString()}</p></div></div>
              <Badge variant="outline" className="rounded-sm capitalize text-[10px] sm:text-xs">{report.period}</Badge>
            </div>
            <div className="grid grid-cols-2 gap-2 sm:gap-3">
              {[
                { label: "Devices", value: `${report.summary.devices.online}/${report.summary.devices.total}`, icon: Server, color: "text-purple-500" },
                { label: "Avg BW", value: `${report.summary.avg_bandwidth.download}`, sub: `Up: ${report.summary.avg_bandwidth.upload}`, icon: TrendingUp, color: "text-blue-500", suffix: " Mbps" },
                { label: "Peak BW", value: `${report.summary.peak_bandwidth.download}`, sub: `Up: ${report.summary.peak_bandwidth.upload}`, icon: BarChart3, color: "text-green-500", suffix: " Mbps" },
                { label: "Ping/Jitter", value: `${report.summary.avg_ping}`, sub: `Jitter: ${report.summary.avg_jitter} ms`, icon: Activity, color: "text-cyan-500", suffix: " ms" },
              ].map(s => (
                <div key={s.label} className="p-2 sm:p-3 bg-secondary/30 rounded-sm border border-border/50">
                  <div className="flex items-center gap-1 sm:gap-2 mb-1 sm:mb-2"><s.icon className={`w-3 h-3 sm:w-4 sm:h-4 ${s.color}`} /><span className="text-[9px] sm:text-xs text-muted-foreground">{s.label}</span></div>
                  <p className="text-base sm:text-xl font-bold font-['Rajdhani']">{s.value}{s.suffix||""}</p>
                  {s.sub && <p className="text-[10px] sm:text-xs text-muted-foreground">{s.sub}</p>}
                </div>
              ))}
            </div>
          </div>

          {report.traffic_trend.length > 0 ? (
            <>
              <div className="bg-card border border-border rounded-sm p-5" data-testid="report-traffic-chart">
                <h3 className="text-base font-semibold font-['Rajdhani'] mb-4">Traffic Trend</h3>
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={report.traffic_trend}>
                      <defs>
                        <linearGradient id="rDl" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3}/><stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/></linearGradient>
                        <linearGradient id="rUl" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#10b981" stopOpacity={0.3}/><stop offset="95%" stopColor="#10b981" stopOpacity={0}/></linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#27272a" /><XAxis dataKey="time" tick={{fill:"#a1a1aa",fontSize:10}} tickLine={false} axisLine={{stroke:"#27272a"}} /><YAxis tick={{fill:"#a1a1aa",fontSize:10}} tickLine={false} axisLine={{stroke:"#27272a"}} /><Tooltip {...ttStyle} />
                      <Area type="monotone" dataKey="download" stroke="#3b82f6" fill="url(#rDl)" strokeWidth={2} name="Download (Mbps)" />
                      <Area type="monotone" dataKey="upload" stroke="#10b981" fill="url(#rUl)" strokeWidth={2} name="Upload (Mbps)" />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>
              <div className="bg-card border border-border rounded-sm p-5" data-testid="report-ping-chart">
                <h3 className="text-base font-semibold font-['Rajdhani'] mb-4">Ping & Jitter Trend</h3>
                <div className="h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={report.traffic_trend}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#27272a" /><XAxis dataKey="time" tick={{fill:"#a1a1aa",fontSize:10}} tickLine={false} axisLine={{stroke:"#27272a"}} /><YAxis tick={{fill:"#a1a1aa",fontSize:10}} tickLine={false} axisLine={{stroke:"#27272a"}} /><Tooltip {...ttStyle} />
                      <Legend iconType="line" wrapperStyle={{fontSize:"11px",color:"#a1a1aa"}} />
                      <Line type="monotone" dataKey="ping" stroke="#06b6d4" strokeWidth={2} dot={false} name="Ping (ms)" />
                      <Line type="monotone" dataKey="jitter" stroke="#f43f5e" strokeWidth={2} dot={false} strokeDasharray="5 3" name="Jitter (ms)" />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </>
          ) : (
            <div className="bg-card border border-border rounded-sm p-8 text-center"><Activity className="w-10 h-10 mx-auto mb-3 text-muted-foreground/30" /><p className="text-muted-foreground">No traffic data available for this period</p><p className="text-xs text-muted-foreground mt-1">Traffic data is collected via SNMP polling. Make sure devices are configured and online.</p></div>
          )}

          {report.device_summary?.length > 0 && (
            <div className="bg-card border border-border rounded-sm overflow-hidden" data-testid="report-device-summary">
              <div className="p-5 border-b border-border"><h3 className="text-base font-semibold font-['Rajdhani']">Device Summary</h3></div>
              <Table>
                <TableHeader><TableRow className="hover:bg-transparent"><TableHead>Device</TableHead><TableHead>IP</TableHead><TableHead>Model</TableHead><TableHead>Status</TableHead><TableHead>CPU</TableHead><TableHead>Memory</TableHead><TableHead>Uptime</TableHead></TableRow></TableHeader>
                <TableBody>
                  {report.device_summary.map(d => (
                    <TableRow key={d.name}>
                      <TableCell className="font-semibold text-xs">{d.name}</TableCell>
                      <TableCell className="font-mono text-xs">{d.ip_address}</TableCell>
                      <TableCell className="text-xs">{d.model || "-"}</TableCell>
                      <TableCell><Badge className={`rounded-sm text-xs border ${d.status==="online"?"bg-green-500/10 text-green-500 border-green-500/20":"bg-red-500/10 text-red-500 border-red-500/20"}`}>{d.status}</Badge></TableCell>
                      <TableCell className="font-mono text-xs">{d.cpu}%</TableCell>
                      <TableCell className="font-mono text-xs">{d.memory}%</TableCell>
                      <TableCell className="font-mono text-xs">{d.uptime || "-"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
