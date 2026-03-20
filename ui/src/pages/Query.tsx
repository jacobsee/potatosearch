import { useEffect, useState } from "react";
import { api, type BackendsResponse, type DocumentResponse, type QueryResponse, type QueryResult } from "../api/client";

export default function Query() {
  const [question, setQuestion] = useState("");
  const [topK, setTopK] = useState(10);
  const [results, setResults] = useState<QueryResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queryTime, setQueryTime] = useState<number | null>(null);

  const [availableBackends, setAvailableBackends] = useState<string[]>([]);
  // null = search all backends; a Set means only those backends are searched
  const [selectedBackends, setSelectedBackends] = useState<Set<string> | null>(null);

  useEffect(() => {
    api.get<BackendsResponse>("/api/backends").then((data) => {
      setAvailableBackends(Object.keys(data));
    }).catch(() => {});
  }, []);

  const toggleBackend = (name: string) => {
    setSelectedBackends((prev) => {
      if (prev === null) {
        // Currently "All" — clicking a backend selects only that one
        return new Set([name]);
      }
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      // If every backend is selected (or none), collapse back to "all"
      return next.size === 0 || next.size === availableBackends.length ? null : next;
    });
  };

  const isSelected = (name: string) =>
    selectedBackends === null || selectedBackends.has(name);

  const handleSearch = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!question.trim()) return;

    setLoading(true);
    setError(null);
    setResults(null);
    setQueryTime(null);

    const start = performance.now();
    try {
      const body: Record<string, unknown> = { question, top_k: topK };
      if (selectedBackends !== null) {
        body.backends = Array.from(selectedBackends);
      }
      const data = await api.post<QueryResponse>("/api/query", body);
      setResults(data.results);
      setQueryTime(Math.round(performance.now() - start));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Query failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-stone-900">Query</h1>
        <p className="text-stone-500 mt-1">
          Test semantic search against your indexed documents
        </p>
      </div>

      <form onSubmit={handleSearch} className="mb-8">
        <div className="bg-white rounded-xl border border-stone-200 p-4">
          <div className="flex gap-3">
            <div className="flex-1 relative">
              <svg
                className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-stone-400"
                fill="none"
                viewBox="0 0 24 24"
                strokeWidth={1.5}
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z"
                />
              </svg>
              <input
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Ask a question..."
                className="w-full pl-10 pr-4 py-3 text-stone-800 bg-stone-50 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 focus:bg-white transition-colors"
                autoFocus
              />
            </div>
            <button
              type="submit"
              disabled={loading || !question.trim()}
              className="px-6 py-3 bg-amber-600 text-white rounded-lg font-medium text-sm hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
            >
              {loading ? "Searching..." : "Search"}
            </button>
          </div>

          <div className="flex items-center gap-3 mt-3 pt-3 border-t border-stone-100">
            <label className="text-sm text-stone-500 shrink-0">
              Results:
            </label>
            <input
              type="range"
              min={1}
              max={50}
              value={topK}
              onChange={(e) => setTopK(parseInt(e.target.value))}
              className="flex-1 h-1.5 bg-stone-200 rounded-lg appearance-none cursor-pointer accent-amber-600"
            />
            <span className="text-sm font-mono text-stone-600 w-8 text-right">
              {topK}
            </span>
          </div>

          {availableBackends.length > 1 && (
            <div className="flex items-center gap-2 mt-3 pt-3 border-t border-stone-100 flex-wrap">
              <span className="text-sm text-stone-500 shrink-0">Backends:</span>
              <button
                type="button"
                onClick={() => setSelectedBackends(null)}
                className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
                  selectedBackends === null
                    ? "bg-amber-600 text-white"
                    : "bg-stone-100 text-stone-500 hover:bg-stone-200"
                }`}
              >
                All
              </button>
              {availableBackends.map((name) => (
                <button
                  key={name}
                  type="button"
                  onClick={() => toggleBackend(name)}
                  className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
                    isSelected(name) && selectedBackends !== null
                      ? "bg-amber-600 text-white"
                      : "bg-stone-100 text-stone-500 hover:bg-stone-200"
                  }`}
                >
                  {name}
                </button>
              ))}
            </div>
          )}
        </div>
      </form>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-16">
          <svg className="w-8 h-8 text-amber-600 animate-spin" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
        </div>
      )}

      {results !== null && !loading && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <p className="text-sm text-stone-500">
              {results.length} result{results.length !== 1 ? "s" : ""}
              {queryTime !== null && (
                <span className="ml-2 text-stone-400">({queryTime}ms)</span>
              )}
            </p>
          </div>

          {results.length === 0 ? (
            <div className="bg-white rounded-xl border border-stone-200 p-12 text-center">
              <p className="text-stone-500">No results found.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {results.map((result, i) => (
                <ResultCard key={i} result={result} rank={i + 1} />
              ))}
            </div>
          )}
        </div>
      )}

      {results === null && !loading && !error && (
        <div className="text-center py-16">
          <svg className="w-16 h-16 text-stone-200 mx-auto mb-4" fill="none" viewBox="0 0 24 24" strokeWidth={1} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
          </svg>
          <p className="text-stone-400">Enter a question to search the index</p>
        </div>
      )}
    </div>
  );
}

function ResultCard({ result, rank }: { result: QueryResult; rank: number }) {
  const [expanded, setExpanded] = useState(false);
  const [fullDoc, setFullDoc] = useState<string | null>(null);
  const [loadingDoc, setLoadingDoc] = useState(false);
  const [docError, setDocError] = useState<string | null>(null);

  const scoreColor =
    result.score >= 0.7
      ? "bg-emerald-100 text-emerald-700"
      : result.score >= 0.5
        ? "bg-amber-100 text-amber-700"
        : result.score >= 0.3
          ? "bg-orange-100 text-orange-700"
          : "bg-red-100 text-red-700";

  const scoreWidth = Math.max(5, Math.min(100, result.score * 100));
  const scoreBarColor =
    result.score >= 0.7
      ? "bg-emerald-400"
      : result.score >= 0.5
        ? "bg-amber-400"
        : result.score >= 0.3
          ? "bg-orange-400"
          : "bg-red-400";

  const showingFullDoc = fullDoc !== null;

  const displayText = showingFullDoc
    ? fullDoc
    : expanded
      ? result.text
      : result.text.length > 300
        ? result.text.slice(0, 300) + "..."
        : result.text;

  const handleViewDocument = async () => {
    if (showingFullDoc) {
      setFullDoc(null);
      return;
    }
    setLoadingDoc(true);
    setDocError(null);
    try {
      const data = await api.get<DocumentResponse>(
        `/api/document/${encodeURIComponent(result.backend)}?locator=${encodeURIComponent(result.locator)}`
      );
      setFullDoc(data.text);
    } catch (err) {
      setDocError(err instanceof Error ? err.message : "Failed to load document");
    } finally {
      setLoadingDoc(false);
    }
  };

  return (
    <div className="bg-white rounded-xl border border-stone-200 p-5">
      <div className="flex items-start gap-4">
        <span className="text-sm font-mono text-stone-400 mt-0.5 w-6 shrink-0">
          {rank}
        </span>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            {result.title && (
              <h3 className="font-semibold text-stone-900">{result.title}</h3>
            )}
            <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${scoreColor}`}>
              {result.score.toFixed(3)}
            </span>
            <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-stone-100 text-stone-600">
              {result.backend}
            </span>
          </div>

          <div className="w-full bg-stone-100 rounded-full h-1 mb-3">
            <div
              className={`h-1 rounded-full ${scoreBarColor}`}
              style={{ width: `${scoreWidth}%` }}
            />
          </div>

          <p className="text-sm text-stone-600 whitespace-pre-wrap leading-relaxed">
            {displayText}
          </p>

          <div className="flex items-center gap-3 mt-2">
            {!showingFullDoc && result.text.length > 300 && (
              <button
                onClick={() => setExpanded(!expanded)}
                className="text-xs text-amber-600 hover:text-amber-700 font-medium"
              >
                {expanded ? "Show less" : "Show more"}
              </button>
            )}
            <button
              onClick={handleViewDocument}
              disabled={loadingDoc}
              className="text-xs text-amber-600 hover:text-amber-700 font-medium disabled:opacity-50"
            >
              {loadingDoc
                ? "Loading..."
                : showingFullDoc
                  ? "Show chunk only"
                  : "View full document"}
            </button>
          </div>

          {docError && (
            <p className="text-xs text-red-600 mt-1">{docError}</p>
          )}

          <p className="text-xs text-stone-400 mt-2 font-mono truncate">
            {result.locator}
          </p>
        </div>
      </div>
    </div>
  );
}
