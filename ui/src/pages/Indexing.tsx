import { useEffect, useRef, useState } from "react";
import {
  api,
  type BackendInfo,
  type BackendsResponse,
  type DropBackendResponse,
  type IngestProgress,
  type IngestStartResponse,
  type IngestStatusResponse,
  type StatsResponse,
} from "../api/client";

interface JobConfig {
  trainIvfpq: boolean;
  forceTrain: boolean;
}

function phaseLabel(phase: string): string {
  switch (phase) {
    case "starting":
      return "Starting\u2026";
    case "collecting_sample":
      return "Collecting training sample";
    case "embedding_sample":
      return "Embedding training sample";
    case "training_index":
      return "Training IVF-PQ index";
    case "ingesting":
      return "Indexing documents";
    case "pruning":
      return "Pruning stale chunks";
    case "saving":
      return "Saving index";
    case "done":
      return "Complete";
    case "error":
      return "Failed";
    default:
      return phase;
  }
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}m ${secs}s`;
}

function isActivePhase(phase: string): boolean {
  return !["done", "error"].includes(phase);
}

function formatBytes(bytes: number | null): string {
  if (bytes == null || bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let val = bytes;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i++;
  }
  return `${val.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function indexTypeLabel(type: string): string {
  switch (type) {
    case "ivfpq":
      return "IVF-PQ";
    case "flat":
      return "Flat";
    case "none":
      return "Not indexed";
    default:
      return type;
  }
}

function Tooltip({ text }: { text: string }) {
  return (
    <span className="relative group inline-flex items-center">
      <svg
        className="w-3.5 h-3.5 text-stone-400 cursor-help"
        fill="none"
        viewBox="0 0 24 24"
        strokeWidth={2}
        stroke="currentColor"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M12 18h.01"
        />
        <circle cx="12" cy="12" r="10" strokeWidth={2} />
      </svg>
      <span className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 rounded-lg bg-stone-800 px-3 py-2 text-xs text-stone-100 leading-relaxed opacity-0 group-hover:opacity-100 transition-opacity shadow-lg z-10">
        {text}
      </span>
    </span>
  );
}

export default function Indexing() {
  const [backends, setBackends] = useState<BackendsResponse>({});
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [config, setConfig] = useState<Record<string, JobConfig>>({});
  const [progress, setProgress] = useState<Record<string, IngestProgress>>({});
  const [loading, setLoading] = useState(true);
  const pollingRef = useRef<number | null>(null);

  const startPolling = () => {
    if (pollingRef.current) return;
    pollingRef.current = window.setInterval(async () => {
      try {
        const status = await api.get<IngestStatusResponse>(
          "/api/ingest/status",
        );
        setProgress(status.jobs);

        const anyRunning = Object.values(status.jobs).some((j) =>
          isActivePhase(j.phase),
        );
        if (!anyRunning && pollingRef.current) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
          // Refresh stats + backends when all jobs finish
          const [b, s] = await Promise.all([
            api.get<BackendsResponse>("/api/backends"),
            api.get<StatsResponse>("/api/stats"),
          ]);
          setBackends(b);
          setStats(s);
        }
      } catch {
        // ignore polling errors
      }
    }, 2000);
  };

  const stopPolling = () => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  };

  const fetchData = async () => {
    setLoading(true);
    try {
      const [b, s, status] = await Promise.all([
        api.get<BackendsResponse>("/api/backends"),
        api.get<StatsResponse>("/api/stats"),
        api.get<IngestStatusResponse>("/api/ingest/status"),
      ]);
      setBackends(b);
      setStats(s);
      setProgress(status.jobs);

      setConfig((prev) => {
        const next = { ...prev };
        for (const name of Object.keys(b)) {
          if (!next[name]) {
            next[name] = { trainIvfpq: false, forceTrain: false };
          }
        }
        return next;
      });

      const anyRunning = Object.values(status.jobs).some((j) =>
        isActivePhase(j.phase),
      );
      if (anyRunning) startPolling();
    } catch {
      // backends not available
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    return () => stopPolling();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const updateConfig = (name: string, patch: Partial<JobConfig>) => {
    setConfig((prev) => ({
      ...prev,
      [name]: { ...prev[name]!, ...patch },
    }));
  };

  const runIngest = async (name: string) => {
    const cfg = config[name]!;
    try {
      await api.post<IngestStartResponse>("/api/ingest", {
        backend: name,
        train_ivfpq: cfg.trainIvfpq,
        force_train: cfg.forceTrain,
      });
      startPolling();
    } catch (err) {
      setProgress((prev) => ({
        ...prev,
        [name]: {
          backend: name,
          phase: "error",
          detail: "",
          docs_processed: 0,
          docs_total: null,
          chunks_new: 0,
          chunks_skipped: 0,
          chunks_target: null,
          total_chunks: null,
          elapsed_seconds: 0,
          error: err instanceof Error ? err.message : "Failed to start ingest",
        },
      }));
    }
  };

  const [dropping, setDropping] = useState<string | null>(null);
  const [confirmDrop, setConfirmDrop] = useState<string | null>(null);

  const dropBackend = async (name: string) => {
    setDropping(name);
    try {
      await api.delete<DropBackendResponse>(
        `/api/backends/${encodeURIComponent(name)}`,
      );
      setConfirmDrop(null);
      await fetchData();
    } catch (err) {
      setProgress((prev) => ({
        ...prev,
        [name]: {
          backend: name,
          phase: "error",
          detail: "",
          docs_processed: 0,
          docs_total: null,
          chunks_new: 0,
          chunks_skipped: 0,
          chunks_target: null,
          total_chunks: null,
          elapsed_seconds: 0,
          error: err instanceof Error ? err.message : "Drop failed",
        },
      }));
    } finally {
      setDropping(null);
    }
  };

  const backendEntries = Object.entries(backends);

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-stone-900">Indexing</h1>
        <p className="text-stone-500 mt-1">
          Trigger document ingestion from configured backends
        </p>
      </div>

      {stats && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-8">
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
            <p className="text-xs font-medium text-amber-600 uppercase tracking-wider">
              Total Chunks
            </p>
            <p className="text-xl font-bold text-amber-700 mt-1">
              {stats.total_chunks.toLocaleString()}
            </p>
          </div>
          <div className="bg-stone-50 border border-stone-200 rounded-xl p-4">
            <p className="text-xs font-medium text-stone-500 uppercase tracking-wider">
              Backends
            </p>
            <p className="text-xl font-bold text-stone-700 mt-1">
              {backendEntries.length}
            </p>
          </div>
        </div>
      )}

      {loading ? (
        <div className="animate-pulse space-y-4">
          <div className="h-40 bg-stone-200 rounded-xl" />
          <div className="h-40 bg-stone-200 rounded-xl" />
        </div>
      ) : backendEntries.length === 0 ? (
        <div className="bg-white rounded-xl border border-stone-200 p-12 text-center">
          <svg
            className="w-12 h-12 text-stone-300 mx-auto mb-4"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={1.5}
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375"
            />
          </svg>
          <p className="text-stone-500">
            No backends registered. Configure backends and reload the engine
            first.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {backendEntries.map(([name, rawInfo]) => {
            const info = rawInfo as BackendInfo;
            const cfg = config[name];
            const prog = progress[name];
            const running = prog ? isActivePhase(prog.phase) : false;

            return (
              <div
                key={name}
                className="bg-white rounded-xl border border-stone-200 p-6"
              >
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <div className="flex items-center gap-3">
                      <h3 className="text-lg font-semibold text-stone-900">
                        {name}
                      </h3>
                      <span
                        className={`px-2 py-0.5 rounded text-xs font-medium ${
                          info.index_type === "ivfpq"
                            ? "bg-violet-100 text-violet-700"
                            : info.index_type === "flat"
                              ? "bg-sky-100 text-sky-700"
                              : "bg-stone-100 text-stone-500"
                        }`}
                      >
                        {indexTypeLabel(info.index_type)}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => runIngest(name)}
                      disabled={running || dropping === name}
                      className="px-4 py-2 bg-amber-600 text-white rounded-lg font-medium text-sm hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      {running ? (
                        <span className="flex items-center gap-2">
                          <svg
                            className="w-4 h-4 animate-spin"
                            viewBox="0 0 24 24"
                            fill="none"
                          >
                            <circle
                              className="opacity-25"
                              cx="12"
                              cy="12"
                              r="10"
                              stroke="currentColor"
                              strokeWidth="4"
                            />
                            <path
                              className="opacity-75"
                              fill="currentColor"
                              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                            />
                          </svg>
                          Ingesting...
                        </span>
                      ) : (
                        "Ingest"
                      )}
                    </button>
                    {confirmDrop === name ? (
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => dropBackend(name)}
                          disabled={dropping === name}
                          className="px-3 py-2 bg-red-600 text-white rounded-lg font-medium text-sm hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                          {dropping === name ? "Dropping..." : "Confirm"}
                        </button>
                        <button
                          onClick={() => setConfirmDrop(null)}
                          className="px-3 py-2 text-stone-600 border border-stone-300 rounded-lg text-sm hover:bg-stone-100 transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirmDrop(name)}
                        disabled={running || dropping === name}
                        className="px-3 py-2 text-red-600 border border-red-300 rounded-lg font-medium text-sm hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        title="Drop shard data"
                      >
                        Drop
                      </button>
                    )}
                  </div>
                </div>

                {/* Shard details grid */}
                <div className="grid grid-cols-3 gap-3 mb-4">
                  <div>
                    <p className="text-xs text-stone-400 uppercase tracking-wider">
                      Documents
                    </p>
                    <p className="text-sm font-medium text-stone-700">
                      {info.indexed_documents.toLocaleString()}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-stone-400 uppercase tracking-wider">
                      Chunks
                    </p>
                    <p className="text-sm font-medium text-stone-700">
                      {info.indexed_chunks.toLocaleString()}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-stone-400 uppercase tracking-wider">
                      Disk Usage
                    </p>
                    <p className="text-sm font-medium text-stone-700">
                      {formatBytes(info.total_size_bytes)}
                    </p>
                  </div>
                </div>

                {/* IVF-PQ params (only when applicable) */}
                {info.index_type === "ivfpq" &&
                  Object.keys(info.index_params).length > 0 && (
                    <div className="flex flex-wrap gap-x-4 gap-y-1 mb-4 text-xs text-stone-500">
                      {info.index_params.nlist != null && (
                        <span className="inline-flex items-center gap-1">
                          nlist: {info.index_params.nlist.toLocaleString()}
                          <Tooltip text="Number of clusters the index is divided into. More clusters = faster search but slightly less accurate. Vectors are grouped into these clusters during training, and only a subset are searched at query time." />
                        </span>
                      )}
                      {info.index_params.pq_m != null && (
                        <span className="inline-flex items-center gap-1">
                          pq_m: {info.index_params.pq_m}
                          <Tooltip text="Number of sub-quantizers used to compress each vector. Higher values preserve more detail (better accuracy) but use more disk space. Each vector is split into this many pieces for compact storage." />
                        </span>
                      )}
                      {info.index_params.nprobe != null && (
                        <span className="inline-flex items-center gap-1">
                          nprobe: {info.index_params.nprobe}
                          <Tooltip text="Number of clusters checked per search query. Higher values give more accurate results but slower searches. This is the main accuracy vs. speed tradeoff at query time." />
                        </span>
                      )}
                      {info.index_size_bytes != null && (
                        <span className="inline-flex items-center gap-1">
                          index: {formatBytes(info.index_size_bytes)}
                          <Tooltip text="Size of the FAISS index file on disk. This contains the compressed vectors and cluster structure used for search." />
                        </span>
                      )}
                      {info.refs_size_bytes != null && (
                        <span className="inline-flex items-center gap-1">
                          refs: {formatBytes(info.refs_size_bytes)}
                          <Tooltip text="Size of the SQLite reference database on disk. This maps each vector back to its source document and chunk position for retrieving text at query time." />
                        </span>
                      )}
                    </div>
                  )}

                {cfg && (
                  <div className="space-y-3">
                    <div className="flex items-center gap-6">
                      <label className="flex items-center gap-2 text-sm text-stone-600 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={cfg.trainIvfpq}
                          onChange={(e) =>
                            updateConfig(name, {
                              trainIvfpq: e.target.checked,
                            })
                          }
                          disabled={running}
                          className="rounded border-stone-300 text-amber-600 focus:ring-amber-500"
                        />
                        Train IVF-PQ index
                        <Tooltip text="Replaces the default Flat index with an IVF-PQ index. Pro: uses much less memory and disk for large datasets. Con: search results become approximate instead of exact, and training takes extra time upfront." />
                      </label>
                      <label className="flex items-center gap-2 text-sm text-stone-600 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={cfg.forceTrain}
                          onChange={(e) =>
                            updateConfig(name, {
                              forceTrain: e.target.checked,
                            })
                          }
                          disabled={running}
                          className="rounded border-stone-300 text-amber-600 focus:ring-amber-500"
                        />
                        Force re-train
                        <Tooltip text="By default, training only uses new (unindexed) documents. Enable this to retrain the index from scratch using all documents, which can improve search quality if the dataset has changed significantly." />
                      </label>
                    </div>

                    {/* Progress display */}
                    {prog && <ProgressPanel progress={prog} />}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ProgressPanel({ progress: p }: { progress: IngestProgress }) {
  const running = isActivePhase(p.phase);

  if (p.phase === "done") {
    return (
      <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg text-sm text-emerald-700">
        <div className="flex items-center gap-2 font-medium">
          <svg
            className="w-4 h-4"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={2}
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M4.5 12.75l6 6 9-13.5"
            />
          </svg>
          Ingestion complete
        </div>
        <p className="mt-1">
          {p.chunks_new.toLocaleString()} new chunks
          {p.total_chunks != null &&
            ` (${p.total_chunks.toLocaleString()} total)`}
          {" \u00B7 "}
          {formatDuration(p.elapsed_seconds)}
        </p>
      </div>
    );
  }

  if (p.phase === "error") {
    return (
      <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
        {p.error || "Ingestion failed"}
      </div>
    );
  }

  if (!running) return null;

  const hasChunkTarget =
    (p.phase === "collecting_sample" || p.phase === "embedding_sample") &&
    p.chunks_target != null &&
    p.chunks_target > 0;
  const hasDocTarget =
    p.phase === "ingesting" &&
    p.docs_total != null &&
    p.docs_total > 0;
  const pct = hasChunkTarget
    ? Math.min(100, (p.chunks_new / p.chunks_target!) * 100)
    : hasDocTarget
      ? Math.min(100, (p.docs_processed / p.docs_total!) * 100)
      : null;

  return (
    <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg space-y-2">
      {/* Phase label with spinner */}
      <div className="flex items-center gap-2">
        <svg
          className="w-4 h-4 animate-spin text-amber-600"
          viewBox="0 0 24 24"
          fill="none"
        >
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
          />
        </svg>
        <span className="text-sm font-medium text-amber-700">
          {phaseLabel(p.phase)}
        </span>
      </div>

      {/* Detail text */}
      {p.detail && (
        <p className="text-xs text-amber-600">{p.detail}</p>
      )}

      {/* Progress bar */}
      {pct != null && (
        <div className="space-y-1">
          <div className="w-full bg-amber-200 rounded-full h-2">
            <div
              className="bg-amber-500 h-2 rounded-full transition-all duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="text-xs text-amber-600">
            {hasChunkTarget
              ? `${p.chunks_new.toLocaleString()} / ${p.chunks_target!.toLocaleString()} chunks`
              : `${p.docs_processed.toLocaleString()} / ~${p.docs_total!.toLocaleString()} documents`}
          </p>
        </div>
      )}

      {/* Counters for ingesting phase */}
      {p.phase === "ingesting" && (
        <div className="flex gap-4 text-xs text-amber-600">
          <span>{p.chunks_new.toLocaleString()} new chunks</span>
          <span>{p.chunks_skipped.toLocaleString()} skipped</span>
          <span>{p.docs_processed.toLocaleString()} documents processed</span>
        </div>
      )}

      {/* Elapsed time */}
      <p className="text-xs text-amber-500">
        {formatDuration(p.elapsed_seconds)} elapsed
      </p>
    </div>
  );
}
