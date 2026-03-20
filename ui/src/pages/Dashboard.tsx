import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  type StatsResponse,
  type HealthResponse,
  type ReloadResponse,
} from "../api/client";

export default function Dashboard() {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloading, setReloading] = useState(false);
  const [reloadResult, setReloadResult] = useState<ReloadResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [h, s] = await Promise.allSettled([
        api.get<HealthResponse>("/api/health"),
        api.get<StatsResponse>("/api/stats"),
      ]);
      setHealth(h.status === "fulfilled" ? h.value : { status: "error", engine: "unreachable" });
      setStats(s.status === "fulfilled" ? s.value : null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleReload = async () => {
    setReloading(true);
    setReloadResult(null);
    try {
      const result = await api.post<ReloadResponse>("/api/reload");
      setReloadResult(result);
      await fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reload failed");
    } finally {
      setReloading(false);
    }
  };

  const engineOk = health?.engine === "connected";
  const backendEntries = stats?.backends ? Object.entries(stats.backends) : [];

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-stone-900">Dashboard</h1>
          <p className="text-stone-500 mt-1">Overview of your potatosearch instance</p>
        </div>
        <button
          onClick={handleReload}
          disabled={reloading}
          className="px-4 py-2 bg-amber-600 text-white rounded-lg font-medium text-sm hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {reloading ? "Reloading..." : "Reload Engine"}
        </button>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {error}
        </div>
      )}

      {reloadResult && (
        <div className="mb-6 p-4 bg-emerald-50 border border-emerald-200 rounded-lg text-emerald-700 text-sm">
          Engine reloaded. Backends: {reloadResult.backends_after.join(", ") || "none"}.
          {" "}{reloadResult.total_chunks.toLocaleString()} chunks indexed.
        </div>
      )}

      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="bg-white rounded-xl border border-stone-200 p-6 animate-pulse">
              <div className="h-4 bg-stone-200 rounded w-20 mb-3" />
              <div className="h-8 bg-stone-200 rounded w-16" />
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
          <StatCard
            label="Engine Status"
            value={engineOk ? "Connected" : "Offline"}
            accent={engineOk ? "emerald" : "red"}
          />
          <StatCard
            label="Total Chunks"
            value={stats?.total_chunks?.toLocaleString() ?? "—"}
            accent="amber"
          />
          <StatCard
            label="Backends"
            value={String(backendEntries.length)}
            accent="stone"
          />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl border border-stone-200 p-6">
          <h2 className="text-sm font-semibold text-stone-900 uppercase tracking-wider mb-4">
            Backends
          </h2>
          {backendEntries.length === 0 ? (
            <p className="text-stone-400 text-sm">
              No backends configured.{" "}
              <Link to="/configuration" className="text-amber-600 hover:text-amber-700 underline">
                Add one
              </Link>
            </p>
          ) : (
            <div className="space-y-3">
              {backendEntries.map(([name, count]) => (
                <div
                  key={name}
                  className="flex items-center justify-between p-3 bg-stone-50 rounded-lg"
                >
                  <div>
                    <span className="font-medium text-stone-800">{name}</span>
                  </div>
                  <span className="text-sm text-stone-500">
                    {(count as number).toLocaleString()} chunks
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="bg-white rounded-xl border border-stone-200 p-6">
          <h2 className="text-sm font-semibold text-stone-900 uppercase tracking-wider mb-4">
            Quick Actions
          </h2>
          <div className="space-y-3">
            <Link
              to="/configuration"
              className="flex items-center gap-3 p-3 bg-stone-50 rounded-lg hover:bg-stone-100 transition-colors"
            >
              <svg className="w-5 h-5 text-stone-400" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
              </svg>
              <div>
                <p className="text-sm font-medium text-stone-800">Edit Configuration</p>
                <p className="text-xs text-stone-500">Manage backend data sources</p>
              </div>
            </Link>
            <Link
              to="/indexing"
              className="flex items-center gap-3 p-3 bg-stone-50 rounded-lg hover:bg-stone-100 transition-colors"
            >
              <svg className="w-5 h-5 text-stone-400" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
              </svg>
              <div>
                <p className="text-sm font-medium text-stone-800">Trigger Indexing</p>
                <p className="text-xs text-stone-500">Ingest documents from backends</p>
              </div>
            </Link>
            <Link
              to="/query"
              className="flex items-center gap-3 p-3 bg-stone-50 rounded-lg hover:bg-stone-100 transition-colors"
            >
              <svg className="w-5 h-5 text-stone-400" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
              </svg>
              <div>
                <p className="text-sm font-medium text-stone-800">Test Queries</p>
                <p className="text-xs text-stone-500">Search the index and review results</p>
              </div>
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent: "emerald" | "red" | "amber" | "stone";
}) {
  const colors = {
    emerald: "bg-emerald-50 text-emerald-700 border-emerald-200",
    red: "bg-red-50 text-red-700 border-red-200",
    amber: "bg-amber-50 text-amber-700 border-amber-200",
    stone: "bg-stone-50 text-stone-700 border-stone-200",
  };

  return (
    <div className={`rounded-xl border p-6 ${colors[accent]}`}>
      <p className="text-xs font-medium uppercase tracking-wider opacity-70">{label}</p>
      <p className="text-2xl font-bold mt-1">{value}</p>
    </div>
  );
}
