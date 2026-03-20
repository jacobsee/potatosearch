import { useEffect, useState, useCallback } from "react";
import {
  api,
  type BackendConfig,
  type ConfigResponse,
  type ValidateResponse,
} from "../api/client";

export default function Configuration() {
  const [backends, setBackends] = useState<BackendConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [rawMode, setRawMode] = useState(false);
  const [rawJson, setRawJson] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [success, setSuccess] = useState<string | null>(null);

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get<ConfigResponse>("/api/config");
      setBackends(data.backends ?? []);
      setRawJson(JSON.stringify(data, null, 2));
      setDirty(false);
      setErrors([]);
    } catch (err) {
      setErrors([err instanceof Error ? err.message : "Failed to load config"]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const addBackend = () => {
    setBackends([...backends, { id: "", type: "plaintext", paths: [] }]);
    setDirty(true);
    setSuccess(null);
  };

  const removeBackend = (index: number) => {
    setBackends(backends.filter((_, i) => i !== index));
    setDirty(true);
    setSuccess(null);
  };

  const updateBackend = (index: number, updated: BackendConfig) => {
    setBackends(backends.map((b, i) => (i === index ? updated : b)));
    setDirty(true);
    setSuccess(null);
  };

  const handleRawChange = (value: string) => {
    setRawJson(value);
    setDirty(true);
    setSuccess(null);
  };

  const save = async () => {
    setSaving(true);
    setErrors([]);
    setSuccess(null);

    try {
      let config: ConfigResponse;
      if (rawMode) {
        try {
          config = JSON.parse(rawJson);
        } catch {
          setErrors(["Invalid JSON syntax"]);
          setSaving(false);
          return;
        }
      } else {
        config = { backends };
      }

      const validation = await api.post<ValidateResponse>(
        "/api/config/validate",
        config,
      );
      if (!validation.valid) {
        setErrors(validation.errors);
        setSaving(false);
        return;
      }

      await api.put("/api/config", config);
      setDirty(false);
      setSuccess("Configuration saved. Remember to reload the engine for changes to take effect.");

      if (rawMode) {
        const parsed = JSON.parse(rawJson) as ConfigResponse;
        setBackends(parsed.backends ?? []);
      } else {
        setRawJson(JSON.stringify(config, null, 2));
      }
    } catch (err) {
      setErrors([err instanceof Error ? err.message : "Save failed"]);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div>
        <h1 className="text-2xl font-bold text-stone-900 mb-8">Configuration</h1>
        <div className="animate-pulse space-y-4">
          <div className="h-32 bg-stone-200 rounded-xl" />
          <div className="h-32 bg-stone-200 rounded-xl" />
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-stone-900">Configuration</h1>
          <p className="text-stone-500 mt-1">
            Manage backend data sources in backends.json
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => {
              if (!rawMode) {
                setRawJson(JSON.stringify({ backends }, null, 2));
              } else {
                try {
                  const parsed = JSON.parse(rawJson) as ConfigResponse;
                  setBackends(parsed.backends ?? []);
                } catch {
                  /* stay in raw mode if JSON is invalid */
                  return;
                }
              }
              setRawMode(!rawMode);
            }}
            className="px-3 py-2 text-sm text-stone-600 border border-stone-300 rounded-lg hover:bg-stone-100 transition-colors"
          >
            {rawMode ? "Form Editor" : "Raw JSON"}
          </button>
          <button
            onClick={save}
            disabled={saving || !dirty}
            className="px-4 py-2 bg-amber-600 text-white rounded-lg font-medium text-sm hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>

      {errors.length > 0 && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-sm font-medium text-red-800 mb-1">Validation errors:</p>
          <ul className="list-disc list-inside text-sm text-red-700 space-y-0.5">
            {errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      {success && (
        <div className="mb-6 p-4 bg-emerald-50 border border-emerald-200 rounded-lg text-sm text-emerald-700">
          {success}
        </div>
      )}

      {dirty && (
        <div className="mb-6 p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-700">
          You have unsaved changes.
        </div>
      )}

      {rawMode ? (
        <div className="bg-white rounded-xl border border-stone-200 overflow-hidden">
          <textarea
            value={rawJson}
            onChange={(e) => handleRawChange(e.target.value)}
            className="w-full h-[500px] p-4 font-mono text-sm text-stone-800 bg-white focus:outline-none resize-none"
            spellCheck={false}
          />
        </div>
      ) : (
        <div className="space-y-4">
          {backends.map((backend, index) => (
            <BackendCard
              key={index}
              backend={backend}
              index={index}
              onUpdate={(b) => updateBackend(index, b)}
              onRemove={() => removeBackend(index)}
            />
          ))}

          <button
            onClick={addBackend}
            className="w-full p-4 border-2 border-dashed border-stone-300 rounded-xl text-stone-500 hover:border-amber-400 hover:text-amber-600 transition-colors text-sm font-medium"
          >
            + Add Backend
          </button>
        </div>
      )}
    </div>
  );
}

function BackendCard({
  backend,
  index,
  onUpdate,
  onRemove,
}: {
  backend: BackendConfig;
  index: number;
  onUpdate: (b: BackendConfig) => void;
  onRemove: () => void;
}) {
  const addPath = () => {
    onUpdate({ ...backend, paths: [...backend.paths, ""] });
  };

  const updatePath = (pathIndex: number, value: string) => {
    onUpdate({
      ...backend,
      paths: backend.paths.map((p, i) => (i === pathIndex ? value : p)),
    });
  };

  const removePath = (pathIndex: number) => {
    onUpdate({
      ...backend,
      paths: backend.paths.filter((_, i) => i !== pathIndex),
    });
  };

  return (
    <div className="bg-white rounded-xl border border-stone-200 p-6">
      <div className="flex items-start justify-between mb-4">
        <h3 className="text-sm font-semibold text-stone-500 uppercase tracking-wider">
          Backend {index + 1}
        </h3>
        <button
          onClick={onRemove}
          className="text-stone-400 hover:text-red-500 transition-colors"
          title="Remove backend"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
          </svg>
        </button>
      </div>

      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-stone-700 mb-1.5">
            ID
          </label>
          <input
            type="text"
            value={backend.id}
            onChange={(e) =>
              onUpdate({ ...backend, id: e.target.value })
            }
            placeholder="my-backend"
            className="w-full px-3 py-2 border border-stone-300 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent"
          />
          <p className="text-xs text-stone-500 mt-1">
            Unique identifier for this backend
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-stone-700 mb-1.5">
            Description
          </label>
          <input
            type="text"
            value={backend.description ?? ""}
            onChange={(e) =>
              onUpdate({ ...backend, description: e.target.value || undefined })
            }
            placeholder="What this backend contains (shown to MCP agents)"
            className="w-full px-3 py-2 border border-stone-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent"
          />
          <p className="text-xs text-stone-500 mt-1">
            Human-readable description — exposed via MCP so agents know what to search
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-stone-700 mb-1.5">
            Type
          </label>
          <select
            value={backend.type}
            onChange={(e) =>
              onUpdate({
                ...backend,
                type: e.target.value as BackendConfig["type"],
                ...(e.target.value === "plaintext" ? { min_text_length: undefined } : {}),
              })
            }
            className="w-full px-3 py-2 border border-stone-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent"
          >
            <option value="plaintext">Plaintext</option>
            <option value="zim">ZIM Archive</option>
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-stone-700 mb-1.5">
            Paths
          </label>
          <div className="space-y-2">
            {backend.paths.map((path, pathIndex) => (
              <div key={pathIndex} className="flex gap-2">
                <input
                  type="text"
                  value={path}
                  onChange={(e) => updatePath(pathIndex, e.target.value)}
                  placeholder="/path/to/data"
                  className="flex-1 px-3 py-2 border border-stone-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent font-mono"
                />
                <button
                  onClick={() => removePath(pathIndex)}
                  className="px-2 text-stone-400 hover:text-red-500 transition-colors"
                  title="Remove path"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            ))}
            <button
              onClick={addPath}
              className="text-sm text-amber-600 hover:text-amber-700 font-medium"
            >
              + Add path
            </button>
          </div>
        </div>

        {backend.type === "zim" && (
          <div>
            <label className="block text-sm font-medium text-stone-700 mb-1.5">
              Minimum Text Length
            </label>
            <input
              type="number"
              value={backend.min_text_length ?? 200}
              onChange={(e) =>
                onUpdate({
                  ...backend,
                  min_text_length: parseInt(e.target.value) || 0,
                })
              }
              className="w-32 px-3 py-2 border border-stone-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent"
            />
            <p className="text-xs text-stone-500 mt-1">
              Skip articles shorter than this many characters
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
