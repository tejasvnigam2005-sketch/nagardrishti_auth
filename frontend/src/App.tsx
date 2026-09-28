import { useEffect, useMemo, useState, useCallback } from 'react';
import type {
  Complaint,
  ComplaintStatus,
  DashboardStatistics,
  Department,
  HeatmapPoint,
  HotspotInfo,
} from './types/complaint';
import {
  getComplaints,
  getDashboardHeatmap,
  getDashboardStatistics,
  getDepartments,
  updateComplaintStatus,
} from './services/api';
import { Sidebar, type AuthorityRoute } from './components/Sidebar';
import { Navbar } from './components/Navbar';
import { MobileBottomNav } from './components/MobileBottomNav';
import { ComplaintDrawer } from './components/ComplaintDrawer';
import { AuthorityLanding } from './pages/AuthorityLanding';
import { CommandCenter } from './pages/CommandCenter';
import { ComplaintQueue } from './pages/ComplaintQueue';
import { MapIntelligence } from './pages/MapIntelligence';
import { HotspotIntelligence } from './pages/HotspotIntelligence';
import { LoginPage } from './pages/LoginPage';
import { AccessDeniedPage } from './pages/AccessDeniedPage';
import { AuthProvider, useAuth } from './context/AuthContext';
import type { MapMode } from './components/LeafletMap';
import { Shield } from 'lucide-react';

export type AppRoute = AuthorityRoute | '/login' | '/access-denied';

function AuthorityAppContent() {
  const { session, loading: authLoading, isAuthority, logout } = useAuth();

  // Routing state
  const [currentRoute, setCurrentRoute] = useState<AppRoute>('/dashboard');

  // Backend state
  const [stats, setStats] = useState<DashboardStatistics | null>(null);
  const [complaints, setComplaints] = useState<Complaint[]>([]);
  const [heatmapPoints, setHeatmapPoints] = useState<HeatmapPoint[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [loading, setLoading] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());

  // Master Filter state
  const [categoryFilter, setCategoryFilter] = useState<string>('');
  const [severityFilter, setSeverityFilter] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [departmentFilter, setDepartmentFilter] = useState<string>('');
  const [dateHorizon, setDateHorizon] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Map and Selection state
  const [mapMode, setMapMode] = useState<MapMode>('markers');
  const [focusedHotspot, setFocusedHotspot] = useState<HotspotInfo | null>(null);
  const [selectedComplaint, setSelectedComplaint] = useState<Complaint | null>(null);

  // Responsive Navigation State
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  // Navigate helper
  const navigateTo = useCallback((route: AppRoute) => {
    setCurrentRoute(route);
    if (window.location.pathname !== route) {
      window.history.pushState({}, '', route);
    }
  }, []);

  // Sync routing from URL path / hash
  useEffect(() => {
    const parseRoute = (): AppRoute => {
      const path = window.location.pathname;
      const hash = window.location.hash.replace('#', '');
      const target = hash ? `/${hash}` : path;

      if (target === '/login' || target === '/access-denied') {
        return target;
      }
      if (
        target === '/dashboard' ||
        target === '/reports' ||
        target === '/map' ||
        target === '/hotspots'
      ) {
        return target as AuthorityRoute;
      }
      if (target === '/' || target === '') {
        return '/';
      }
      return '/dashboard';
    };

    setCurrentRoute(parseRoute());

    const handlePopState = () => {
      setCurrentRoute(parseRoute());
    };

    window.addEventListener('popstate', handlePopState);
    window.addEventListener('hashchange', handlePopState);
    return () => {
      window.removeEventListener('popstate', handlePopState);
      window.removeEventListener('hashchange', handlePopState);
    };
  }, []);

  // Route guarding based on auth session and role
  useEffect(() => {
    if (authLoading) return;

    if (!session) {
      // Unauthenticated users must be redirected to /login
      if (currentRoute !== '/login') {
        navigateTo('/login');
      }
      return;
    }

    // Authenticated user exists
    if (!isAuthority) {
      // User is authenticated but does NOT possess the authority role (e.g. citizen)
      if (currentRoute !== '/access-denied') {
        navigateTo('/access-denied');
      }
      return;
    }

    // Authenticated authority user
    if (currentRoute === '/login' || currentRoute === '/access-denied') {
      navigateTo('/dashboard');
    }
  }, [authLoading, session, isAuthority, currentRoute, navigateTo]);

  // Fetch backend records (strictly with authority access token)
  const loadData = useCallback(async (showLoadingSpinner = false) => {
    if (!session || !isAuthority) return;

    if (showLoadingSpinner) setLoading(true);
    setIsRefreshing(true);
    try {
      const [statsData, complaintsData, heatmapData, deptsData] = await Promise.all([
        getDashboardStatistics(),
        getComplaints(),
        getDashboardHeatmap(),
        getDepartments(),
      ]);
      setStats(statsData);
      setComplaints(complaintsData);
      setHeatmapPoints(heatmapData);
      setDepartments(deptsData);
      setLastUpdated(new Date());
    } catch (err) {
      console.error('Failed to load authority records', err);
    } finally {
      setLoading(false);
      setIsRefreshing(false);
    }
  }, [session, isAuthority]);

  useEffect(() => {
    if (!authLoading && session && isAuthority) {
      loadData(true);

      // Automated real-time synchronization every 10 seconds
      const pollInterval = setInterval(() => {
        loadData(false);
      }, 10000);

      return () => clearInterval(pollInterval);
    }
  }, [authLoading, session, isAuthority, loadData]);

  // Reset master filters
  const handleResetFilters = () => {
    setCategoryFilter('');
    setSeverityFilter('');
    setStatusFilter('');
    setDepartmentFilter('');
    setDateHorizon('all');
    setSearchQuery('');
    setFocusedHotspot(null);
  };

  // Filter complaints based on master criteria
  const filteredComplaints = useMemo(() => {
    return complaints.filter((c) => {
      if (categoryFilter && c.problem_type.toLowerCase() !== categoryFilter.toLowerCase()) {
        return false;
      }
      if (severityFilter && c.severity.toUpperCase() !== severityFilter.toUpperCase()) {
        return false;
      }
      if (statusFilter && c.status.toUpperCase() !== statusFilter.toUpperCase()) {
        return false;
      }
      if (departmentFilter && c.department !== departmentFilter) {
        return false;
      }
      if (dateHorizon !== 'all') {
        const itemDate = new Date(c.created_at).getTime();
        const now = Date.now();
        const oneDay = 24 * 60 * 60 * 1000;
        if (dateHorizon === 'today' && now - itemDate > oneDay) {
          return false;
        }
        if (dateHorizon === '7d' && now - itemDate > 7 * oneDay) {
          return false;
        }
        if (dateHorizon === '30d' && now - itemDate > 30 * oneDay) {
          return false;
        }
      }
      if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase().trim();
        const matchId = c.report_id.toLowerCase().includes(query);
        const matchLoc = (c.location_name || '').toLowerCase().includes(query);
        const matchDesc = (c.description || '').toLowerCase().includes(query);
        const matchDept = (c.department || '').toLowerCase().includes(query);
        if (!matchId && !matchLoc && !matchDesc && !matchDept) {
          return false;
        }
      }
      return true;
    });
  }, [complaints, categoryFilter, severityFilter, statusFilter, departmentFilter, dateHorizon, searchQuery]);

  // Update status action handler
  const handleUpdateStatus = async (id: string, newStatus: ComplaintStatus) => {
    const updated = await updateComplaintStatus(id, newStatus);
    setComplaints((prev) => prev.map((item) => (item.id === id ? updated : item)));
    if (selectedComplaint && selectedComplaint.id === id) {
      setSelectedComplaint(updated);
    }
    getDashboardStatistics().then((s) => setStats(s)).catch(() => {});
  };

  // Handle Jump to Duplicate Original
  const handleSelectDuplicate = (duplicateReportId: string) => {
    const found = complaints.find(
      (c) => c.report_id === duplicateReportId || c.id === duplicateReportId
    );
    if (found) {
      setSelectedComplaint(found);
    }
  };

  const handleLogout = async () => {
    await logout();
    navigateTo('/login');
  };

  // Render Loading Splash while verifying initial session
  if (authLoading) {
    return (
      <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center text-slate-100">
        <div className="w-14 h-14 rounded-2xl bg-blue-600/20 border border-blue-500/30 flex items-center justify-center text-blue-400 mb-4 animate-pulse">
          <Shield className="w-7 h-7" />
        </div>
        <p className="text-sm font-semibold tracking-wide">NagarDrishti AI Authority</p>
        <p className="text-xs text-slate-500 mt-1">Verifying municipal session security...</p>
      </div>
    );
  }

  // 1. Unauthenticated -> Login Page
  if (!session || currentRoute === '/login') {
    return (
      <LoginPage
        onLoginSuccess={() => navigateTo('/dashboard')}
        onAccessDenied={() => navigateTo('/access-denied')}
      />
    );
  }

  // 2. Authenticated Citizen -> Access Denied Page
  if (!isAuthority || currentRoute === '/access-denied') {
    return <AccessDeniedPage onBackToLogin={() => navigateTo('/login')} />;
  }

  // 3. Authorized Municipal Officer -> Authority Portal Layout
  const getPageTitle = (route: AppRoute) => {
    switch (route) {
      case '/':
        return 'Portal Overview';
      case '/dashboard':
        return 'Command Center';
      case '/reports':
        return 'Complaint Queue';
      case '/map':
        return 'Map Intelligence';
      case '/hotspots':
        return 'Hotspot Intelligence';
      default:
        return 'Authority Portal';
    }
  };

  const authorityRoute: AuthorityRoute =
    currentRoute === '/' ||
    currentRoute === '/dashboard' ||
    currentRoute === '/reports' ||
    currentRoute === '/map' ||
    currentRoute === '/hotspots'
      ? currentRoute
      : '/dashboard';

  return (
    <div className="flex min-h-screen bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 font-sans transition-colors duration-150">
      {/* Sidebar Navigation */}
      <Sidebar
        currentRoute={authorityRoute}
        onRouteChange={(r) => navigateTo(r)}
        onLogout={handleLogout}
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed((prev) => !prev)}
        isOpenMobile={isMobileMenuOpen}
        onCloseMobile={() => setIsMobileMenuOpen(false)}
      />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 bg-slate-50/60 dark:bg-slate-900/30 overflow-y-auto pb-16 lg:pb-0">
        {/* Top Navbar */}
        <Navbar
          title={getPageTitle(currentRoute)}
          subtitle="Municipal Civic Intelligence"
          onRefresh={() => loadData(false)}
          isRefreshing={isRefreshing}
          lastUpdated={lastUpdated}
          onLogout={handleLogout}
          onOpenMobileMenu={() => setIsMobileMenuOpen(true)}
        />

        {/* Route Pages */}
        <main className="flex-1">
          {currentRoute === '/' && (
            <AuthorityLanding
              onOpenDashboard={() => navigateTo('/dashboard')}
              stats={stats}
            />
          )}

          {currentRoute === '/dashboard' && (
            <CommandCenter
              stats={stats}
              complaints={filteredComplaints}
              heatmapPoints={heatmapPoints}
              departments={departments}
              loading={loading}
              onSelectComplaint={(c) => setSelectedComplaint(c)}
              onSelectHotspot={(h) => {
                setFocusedHotspot(h);
                navigateTo('/map');
              }}
              focusedHotspot={focusedHotspot}
              mapMode={mapMode}
              onMapModeChange={setMapMode}
              categoryFilter={categoryFilter}
              onCategoryFilterChange={setCategoryFilter}
              severityFilter={severityFilter}
              onSeverityFilterChange={setSeverityFilter}
              statusFilter={statusFilter}
              onStatusFilterChange={setStatusFilter}
              departmentFilter={departmentFilter}
              onDepartmentFilterChange={setDepartmentFilter}
              dateHorizon={dateHorizon}
              onDateHorizonChange={setDateHorizon}
              searchQuery={searchQuery}
              onSearchQueryChange={setSearchQuery}
              onResetFilters={handleResetFilters}
              onNavigateToReports={() => navigateTo('/reports')}
              onNavigateToHotspots={() => navigateTo('/hotspots')}
            />
          )}

          {currentRoute === '/reports' && (
            <ComplaintQueue
              complaints={filteredComplaints}
              departments={departments}
              loading={loading}
              onSelectComplaint={(c) => setSelectedComplaint(c)}
              categoryFilter={categoryFilter}
              onCategoryFilterChange={setCategoryFilter}
              severityFilter={severityFilter}
              onSeverityFilterChange={setSeverityFilter}
              statusFilter={statusFilter}
              onStatusFilterChange={setStatusFilter}
              departmentFilter={departmentFilter}
              onDepartmentFilterChange={setDepartmentFilter}
              dateHorizon={dateHorizon}
              onDateHorizonChange={setDateHorizon}
              searchQuery={searchQuery}
              onSearchQueryChange={setSearchQuery}
              onResetFilters={handleResetFilters}
            />
          )}

          {currentRoute === '/map' && (
            <MapIntelligence
              complaints={filteredComplaints}
              heatmapPoints={heatmapPoints}
              departments={departments}
              hotspots={stats?.hotspots || []}
              mapMode={mapMode}
              onMapModeChange={setMapMode}
              onSelectComplaint={(c) => setSelectedComplaint(c)}
              focusedHotspot={focusedHotspot}
              onSelectHotspot={setFocusedHotspot}
              categoryFilter={categoryFilter}
              onCategoryFilterChange={setCategoryFilter}
              severityFilter={severityFilter}
              onSeverityFilterChange={setSeverityFilter}
              statusFilter={statusFilter}
              onStatusFilterChange={setStatusFilter}
              departmentFilter={departmentFilter}
              onDepartmentFilterChange={setDepartmentFilter}
              dateHorizon={dateHorizon}
              onDateHorizonChange={setDateHorizon}
              searchQuery={searchQuery}
              onSearchQueryChange={setSearchQuery}
              onResetFilters={handleResetFilters}
            />
          )}

          {currentRoute === '/hotspots' && (
            <HotspotIntelligence
              hotspots={stats?.hotspots || []}
              allComplaints={complaints}
              onSelectHotspot={(h) => {
                setFocusedHotspot(h);
              }}
              onNavigateToMap={() => navigateTo('/map')}
              onSelectComplaint={(c) => setSelectedComplaint(c)}
            />
          )}
        </main>
      </div>

      {/* Complaint Detail Inspection Drawer */}
      <ComplaintDrawer
        complaint={selectedComplaint}
        onClose={() => setSelectedComplaint(null)}
        onUpdateStatus={handleUpdateStatus}
        onSelectDuplicate={handleSelectDuplicate}
      />

      {/* Bottom Navigation Dock for Mobile (Screens < 1024px) */}
      {currentRoute !== '/' && (
        <MobileBottomNav
          currentRoute={authorityRoute}
          onRouteChange={(r) => navigateTo(r)}
        />
      )}
    </div>
  );
}

export function App() {
  return (
    <AuthProvider>
      <AuthorityAppContent />
    </AuthProvider>
  );
}

export default App;
