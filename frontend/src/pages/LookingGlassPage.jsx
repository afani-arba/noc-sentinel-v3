import React, { useState } from "react";
import { Search, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import api from "@/lib/api";
import { toast } from "sonner";

export default function LookingGlassPage() {
  const [target, setTarget] = useState("");
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);

  const handleQuery = async (e) => {
    e.preventDefault();
    if (!target.trim()) return toast.error("IP or Prefix required");
    
    setLoading(true);
    setResults(null);
    try {
      const res = await api.get(`/bgp/looking-glass?target=${encodeURIComponent(target)}`);
      setResults(res.data.data);
      if (res.data.data.length === 0) {
        toast.info("No route found for this target");
      } else {
        toast.success("Query successful");
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to query looking glass");
    } finally {
      setLoading(false);
    }
  };

  const getAsPath = (attributes) => {
    if (!attributes) return "N/A";
    const asPathAttr = attributes.find(a => a.type === 2); // type 2 is AS_PATH
    if (!asPathAttr || !asPathAttr.as_paths || asPathAttr.as_paths.length === 0) return "N/A";
    return asPathAttr.as_paths.map(p => p.asns ? p.asns.join(" ") : "").join(" ");
  };

  const getNexthop = (attributes) => {
    if (!attributes) return "N/A";
    const nhAttr = attributes.find(a => a.type === 3 || a.type === 14); // NEXT_HOP or MP_REACH_NLRI
    if (!nhAttr) return "N/A";
    return nhAttr.nexthop || (nhAttr.nexthops ? nhAttr.nexthops.join(", ") : "N/A");
  };

  const getCommunities = (attributes) => {
    if (!attributes) return "N/A";
    const commAttr = attributes.find(a => a.type === 8); // type 8 is COMMUNITY
    if (!commAttr || !commAttr.communities) return "None";
    // Convert integer to standard format logic if needed, but gobgp json usually provides readable if requested,
    // otherwise just output raw integers or basic parsing.
    return commAttr.communities.join(", ");
  };

  const flattenRoutes = (rawResults) => {
    if (!rawResults || !Array.isArray(rawResults)) return [];
    const flat = [];
    rawResults.forEach(item => {
      Object.values(item).forEach(pathArray => {
        if (Array.isArray(pathArray)) {
          flat.push(...pathArray);
        }
      });
    });
    return flat;
  };

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-foreground font-['Rajdhani']">BGP Looking Glass</h1>
        <p className="text-muted-foreground mt-1 text-sm">Query your server's GoBGP routing table in real-time (1.2M+ prefixes)</p>
      </div>

      <Card className="bg-card/50 backdrop-blur border-border/50">
        <CardHeader>
          <CardTitle>Query BGP Route</CardTitle>
          <CardDescription>Enter an IP Address (e.g. 8.8.8.8) or Prefix (e.g. 1.1.1.0/24)</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleQuery} className="flex gap-4">
            <Input
              placeholder="IP Address or CIDR Prefix..."
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              className="max-w-md font-mono"
            />
            <Button type="submit" disabled={loading} className="w-32">
              {loading ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Search className="w-4 h-4 mr-2" />}
              {loading ? "Querying..." : "Execute"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {results && results.length > 0 && (
        <Card className="bg-card/50 backdrop-blur border-border/50">
          <CardHeader>
            <CardTitle>Query Results</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left border-collapse">
                <thead className="bg-secondary/50 text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 font-semibold rounded-tl-sm">Prefix</th>
                    <th className="px-4 py-3 font-semibold">Nexthop</th>
                    <th className="px-4 py-3 font-semibold">AS Path</th>
                    <th className="px-4 py-3 font-semibold rounded-tr-sm">Communities</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                  {flattenRoutes(results).map((route, idx) => (
                    <tr key={idx} className="hover:bg-secondary/20 transition-colors">
                      <td className="px-4 py-4 font-mono text-primary font-medium">{route.nlri?.prefix || "N/A"}</td>
                      <td className="px-4 py-4 font-mono">{getNexthop(route.attrs || route.pattrs || route.paths?.[0]?.pattrs)}</td>
                      <td className="px-4 py-4 font-mono text-muted-foreground">{getAsPath(route.attrs || route.pattrs || route.paths?.[0]?.pattrs)}</td>
                      <td className="px-4 py-4 font-mono text-xs">{getCommunities(route.attrs || route.pattrs || route.paths?.[0]?.pattrs)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            
            <div className="mt-8">
               <p className="text-xs text-muted-foreground mb-2 uppercase font-semibold tracking-wider">Raw Output (JSON)</p>
               <pre className="p-4 bg-background border border-border/50 rounded-sm overflow-x-auto text-xs font-mono text-muted-foreground">
                 {JSON.stringify(results, null, 2)}
               </pre>
            </div>
          </CardContent>
        </Card>
      )}

      {results && results.length === 0 && (
        <Card className="border-dashed border-border/50">
          <CardContent className="flex flex-col items-center justify-center p-12 text-center text-muted-foreground">
            <Search className="w-8 h-8 mb-4 opacity-20" />
            <p className="font-medium">No Route Found</p>
            <p className="text-sm mt-1">The requested target is not present in the routing table, or a default route is used.</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
