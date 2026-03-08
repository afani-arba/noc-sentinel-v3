import { useState, useEffect, createContext, useContext, useCallback } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import api from "@/lib/api";
import LoginPage from "@/pages/LoginPage";
import DashboardPage from "@/pages/DashboardPage";
import PPPoEUsersPage from "@/pages/PPPoEUsersPage";
import HotspotUsersPage from "@/pages/HotspotUsersPage";
import ReportsPage from "@/pages/ReportsPage";
import DevicesPage from "@/pages/DevicesPage";
import AdminPage from "@/pages/AdminPage";
import SettingsPage from "@/pages/SettingsPage";
import Layout from "@/components/Layout";
import { Toaster } from "@/components/ui/sonner";

const AuthContext = createContext(null);

export function useAuth() {
  return useContext(AuthContext);
}

function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem("noc_token"));
  const [loading, setLoading] = useState(true);

  const fetchUser = useCallback(async () => {
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      const res = await api.get("/auth/me");
      setUser(res.data);
    } catch {
      localStorage.removeItem("noc_token");
      localStorage.removeItem("noc_user");
      setToken(null);
      setUser(null);
    }
    setLoading(false);
  }, [token]);

  useEffect(() => {
    fetchUser();
  }, [fetchUser]);

  const login = async (username, password) => {
    const res = await api.post("/auth/login", { username, password });
    const { token: t, user: u } = res.data;
    localStorage.setItem("noc_token", t);
    localStorage.setItem("noc_user", JSON.stringify(u));
    setToken(t);
    setUser(u);
    return u;
  };

  const logout = () => {
    localStorage.removeItem("noc_token");
    localStorage.removeItem("noc_user");
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, token, login, logout, loading }}>
      {children}
    </AuthContext.Provider>
  );
}

function ProtectedRoute({ children, allowedRoles }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="flex items-center justify-center min-h-screen bg-background"><div className="text-muted-foreground">Loading...</div></div>;
  if (!user) return <Navigate to="/login" />;
  if (allowedRoles && !allowedRoles.includes(user.role)) return <Navigate to="/" />;
  return children;
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Toaster
          theme="dark"
          toastOptions={{
            classNames: {
              toast: "bg-card border-border text-foreground",
              description: "text-muted-foreground",
            },
          }}
        />
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
            <Route index element={<DashboardPage />} />
            <Route path="pppoe" element={<PPPoEUsersPage />} />
            <Route path="hotspot" element={<HotspotUsersPage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="devices" element={<DevicesPage />} />
            <Route path="settings" element={<ProtectedRoute allowedRoles={["administrator"]}><SettingsPage /></ProtectedRoute>} />
            <Route path="admin" element={<ProtectedRoute allowedRoles={["administrator"]}><AdminPage /></ProtectedRoute>} />
          </Route>
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
