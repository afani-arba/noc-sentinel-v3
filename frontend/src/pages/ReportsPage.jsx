import { useState } from "react";
import api from "@/lib/api";
import { FileText, Download, BarChart3, TrendingUp, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar } from "recharts";
import { toast } from "sonner";
import jsPDF from "jspdf";
import autoTable from "jspdf-autotable";

const tooltipStyle = {
  contentStyle: {
    backgroundColor: "#121214",
    borderColor: "#27272a",
    borderRadius: "4px",
    color: "#fafafa",
    fontSize: "12px",
    fontFamily: "'JetBrains Mono', monospace",
  },
};

const formatBytes = (bytes) => {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
};

export default function ReportsPage() {
  const [period, setPeriod] = useState("daily");
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);

  const generateReport = async () => {
    setLoading(true);
    try {
      const res = await api.post("/reports/generate", { period });
      setReport(res.data);
      toast.success("Report generated");
    } catch (err) {
      toast.error("Failed to generate report");
    }
    setLoading(false);
  };

  const exportPDF = () => {
    if (!report) return;

    const doc = new jsPDF();
    const pageWidth = doc.internal.pageSize.getWidth();

    // Header
    doc.setFontSize(20);
    doc.setTextColor(59, 130, 246);
    doc.text("NOC-SENTINEL", 14, 20);
    doc.setFontSize(10);
    doc.setTextColor(120, 120, 120);
    doc.text("MikroTik Monitoring Report", 14, 27);

    // Report title
    doc.setFontSize(16);
    doc.setTextColor(30, 30, 30);
    doc.text(report.label, 14, 40);

    doc.setFontSize(9);
    doc.setTextColor(100, 100, 100);
    doc.text(`Generated: ${new Date(report.generated_at).toLocaleString()}`, 14, 48);
    doc.text(`Period: ${new Date(report.start_date).toLocaleDateString()} - ${new Date(report.end_date).toLocaleDateString()}`, 14, 54);

    // Line
    doc.setDrawColor(200, 200, 200);
    doc.line(14, 58, pageWidth - 14, 58);

    // Summary
    doc.setFontSize(12);
    doc.setTextColor(30, 30, 30);
    doc.text("Summary", 14, 66);

    const summary = report.summary;
    autoTable(doc, {
      startY: 70,
      head: [["Metric", "Total", "Active/Online"]],
      body: [
        ["PPPoE Users", String(summary.pppoe.total), String(summary.pppoe.active)],
        ["Hotspot Users", String(summary.hotspot.total), String(summary.hotspot.active)],
        ["Devices", String(summary.devices.total), String(summary.devices.online)],
      ],
      theme: "striped",
      headStyles: { fillColor: [59, 130, 246] },
      styles: { fontSize: 9 },
    });

    // Bandwidth
    const afterTable1 = doc.lastAutoTable.finalY + 10;
    doc.setFontSize(12);
    doc.text("Bandwidth", 14, afterTable1);

    autoTable(doc, {
      startY: afterTable1 + 4,
      head: [["Metric", "Download (Mbps)", "Upload (Mbps)"]],
      body: [
        ["Average", String(summary.avg_bandwidth.download), String(summary.avg_bandwidth.upload)],
        ["Peak", String(summary.peak_bandwidth.download), String(summary.peak_bandwidth.upload)],
      ],
      theme: "striped",
      headStyles: { fillColor: [16, 185, 129] },
      styles: { fontSize: 9 },
    });

    // Top Users
    if (report.top_users && report.top_users.length > 0) {
      const afterTable2 = doc.lastAutoTable.finalY + 10;
      doc.setFontSize(12);
      doc.text("Top Users by Traffic", 14, afterTable2);

      autoTable(doc, {
        startY: afterTable2 + 4,
        head: [["Username", "Type", "Profile", "Download", "Upload"]],
        body: report.top_users.map((u) => [
          u.username, u.type, u.profile, formatBytes(u.download), formatBytes(u.upload),
        ]),
        theme: "striped",
        headStyles: { fillColor: [139, 92, 246] },
        styles: { fontSize: 9 },
      });
    }

    // Footer
    const pageCount = doc.internal.getNumberOfPages();
    for (let i = 1; i <= pageCount; i++) {
      doc.setPage(i);
      doc.setFontSize(8);
      doc.setTextColor(150, 150, 150);
      doc.text(`NOC-SENTINEL Report | Page ${i} of ${pageCount}`, pageWidth / 2, doc.internal.pageSize.getHeight() - 10, { align: "center" });
    }

    doc.save(`noc-sentinel-${report.period}-report.pdf`);
    toast.success("PDF exported successfully");
  };

  return (
    <div className="space-y-6" data-testid="reports-page">
      <div>
        <h1 className="text-3xl font-bold font-['Rajdhani'] tracking-tight">Reports</h1>
        <p className="text-sm text-muted-foreground mt-1">Generate and export network reports</p>
      </div>

      {/* Config */}
      <div className="bg-card border border-border rounded-sm p-5">
        <h3 className="text-base font-semibold font-['Rajdhani'] mb-4">Report Configuration</h3>
        <div className="flex flex-col sm:flex-row gap-3 items-end">
          <div className="space-y-1.5 flex-1 max-w-xs">
            <label className="text-xs text-muted-foreground uppercase tracking-wider">Period</label>
            <Select value={period} onValueChange={setPeriod}>
              <SelectTrigger className="rounded-sm bg-background" data-testid="report-period-select">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="daily">Daily (24 Hours)</SelectItem>
                <SelectItem value="weekly">Weekly (7 Days)</SelectItem>
                <SelectItem value="monthly">Monthly (30 Days)</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button onClick={generateReport} disabled={loading} className="rounded-sm gap-2" data-testid="generate-report-btn">
            <BarChart3 className="w-4 h-4" />
            {loading ? "Generating..." : "Generate Report"}
          </Button>
          {report && (
            <Button onClick={exportPDF} variant="outline" className="rounded-sm gap-2" data-testid="export-pdf-btn">
              <Download className="w-4 h-4" /> Export PDF
            </Button>
          )}
        </div>
      </div>

      {/* Report Preview */}
      {report && (
        <div className="space-y-4 animate-fade-in">
          {/* Report Header */}
          <div className="bg-card border border-border rounded-sm p-5">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <FileText className="w-5 h-5 text-primary" />
                <div>
                  <h3 className="text-lg font-semibold font-['Rajdhani']">{report.label}</h3>
                  <p className="text-xs text-muted-foreground font-mono">
                    {new Date(report.start_date).toLocaleDateString()} - {new Date(report.end_date).toLocaleDateString()}
                  </p>
                </div>
              </div>
              <Badge variant="outline" className="rounded-sm capitalize">{report.period}</Badge>
            </div>

            {/* Summary Cards */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              {[
                { label: "PPPoE Users", active: report.summary.pppoe.active, total: report.summary.pppoe.total, icon: Users, color: "text-blue-500" },
                { label: "Hotspot Users", active: report.summary.hotspot.active, total: report.summary.hotspot.total, icon: Users, color: "text-green-500" },
                { label: "Avg Bandwidth", active: `${report.summary.avg_bandwidth.download}`, total: `${report.summary.avg_bandwidth.upload} up`, icon: TrendingUp, color: "text-purple-500", suffix: " Mbps" },
                { label: "Peak Bandwidth", active: `${report.summary.peak_bandwidth.download}`, total: `${report.summary.peak_bandwidth.upload} up`, icon: BarChart3, color: "text-orange-500", suffix: " Mbps" },
              ].map((s) => (
                <div key={s.label} className="p-3 bg-secondary/30 rounded-sm border border-border/50">
                  <div className="flex items-center gap-2 mb-2">
                    <s.icon className={`w-4 h-4 ${s.color}`} />
                    <span className="text-xs text-muted-foreground">{s.label}</span>
                  </div>
                  <p className="text-xl font-bold font-['Rajdhani']">{s.active}{s.suffix || ""}</p>
                  <p className="text-xs text-muted-foreground">{s.total}{!s.suffix ? " total" : ""}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Traffic Trend */}
          <div className="bg-card border border-border rounded-sm p-5" data-testid="report-traffic-chart">
            <h3 className="text-base font-semibold font-['Rajdhani'] mb-4">Traffic Trend</h3>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={report.traffic_trend}>
                  <defs>
                    <linearGradient id="rColorDown" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="rColorUp" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                  <XAxis dataKey="time" tick={{ fill: "#a1a1aa", fontSize: 10 }} tickLine={false} axisLine={{ stroke: "#27272a" }} />
                  <YAxis tick={{ fill: "#a1a1aa", fontSize: 10 }} tickLine={false} axisLine={{ stroke: "#27272a" }} />
                  <Tooltip {...tooltipStyle} />
                  <Area type="monotone" dataKey="download" stroke="#3b82f6" fill="url(#rColorDown)" strokeWidth={2} name="Download (Mbps)" />
                  <Area type="monotone" dataKey="upload" stroke="#10b981" fill="url(#rColorUp)" strokeWidth={2} name="Upload (Mbps)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Active Users Bar */}
          <div className="bg-card border border-border rounded-sm p-5" data-testid="report-users-chart">
            <h3 className="text-base font-semibold font-['Rajdhani'] mb-4">Active Users Trend</h3>
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={report.traffic_trend}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                  <XAxis dataKey="time" tick={{ fill: "#a1a1aa", fontSize: 10 }} tickLine={false} axisLine={{ stroke: "#27272a" }} />
                  <YAxis tick={{ fill: "#a1a1aa", fontSize: 10 }} tickLine={false} axisLine={{ stroke: "#27272a" }} />
                  <Tooltip {...tooltipStyle} />
                  <Bar dataKey="active_users" fill="#8b5cf6" radius={[2, 2, 0, 0]} name="Active Users" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Top Users */}
          {report.top_users && report.top_users.length > 0 && (
            <div className="bg-card border border-border rounded-sm overflow-hidden" data-testid="report-top-users">
              <div className="p-5 border-b border-border">
                <h3 className="text-base font-semibold font-['Rajdhani']">Top Users by Traffic</h3>
              </div>
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>#</TableHead>
                    <TableHead>Username</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Profile</TableHead>
                    <TableHead>Download</TableHead>
                    <TableHead>Upload</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {report.top_users.map((u, i) => (
                    <TableRow key={u.username}>
                      <TableCell className="font-mono text-xs">{i + 1}</TableCell>
                      <TableCell className="font-mono text-xs">{u.username}</TableCell>
                      <TableCell><Badge variant="outline" className="rounded-sm text-xs">{u.type}</Badge></TableCell>
                      <TableCell className="text-xs">{u.profile}</TableCell>
                      <TableCell className="font-mono text-xs">{formatBytes(u.download)}</TableCell>
                      <TableCell className="font-mono text-xs">{formatBytes(u.upload)}</TableCell>
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
