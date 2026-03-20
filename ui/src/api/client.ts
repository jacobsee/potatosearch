class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return body.error || body.detail || res.statusText;
  } catch {
    return res.statusText;
  }
}

export const api = {
  async get<T>(path: string): Promise<T> {
    const res = await fetch(path);
    if (!res.ok) throw new ApiError(res.status, await parseError(res));
    return res.json();
  },

  async post<T>(path: string, body?: unknown): Promise<T> {
    const res = await fetch(path, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) throw new ApiError(res.status, await parseError(res));
    return res.json();
  },

  async put<T>(path: string, body: unknown): Promise<T> {
    const res = await fetch(path, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new ApiError(res.status, await parseError(res));
    return res.json();
  },

  async delete<T>(path: string): Promise<T> {
    const res = await fetch(path, { method: "DELETE" });
    if (!res.ok) throw new ApiError(res.status, await parseError(res));
    return res.json();
  },
};

export interface HealthResponse {
  status: string;
  engine: string;
}

export interface StatsResponse {
  total_chunks: number;
  backends: Record<string, number>;
}

export interface BackendInfo {
  name: string;
  description: string;
  indexed_chunks: number;
  indexed_documents: number;
  index_type: string;
  index_params: Record<string, number>;
  index_size_bytes: number | null;
  refs_size_bytes: number | null;
  total_size_bytes: number;
}

export interface BackendsResponse {
  [key: string]: BackendInfo;
}

export interface QueryResult {
  score: number;
  backend: string;
  locator: string;
  title: string | null;
  text: string;
}

export interface QueryResponse {
  question: string;
  results: QueryResult[];
}

export interface ReloadResponse {
  status: string;
  backends_before: string[];
  backends_after: string[];
  total_chunks: number;
}

export interface IngestResponse {
  backend: string;
  new_chunks: number;
  total_chunks: number;
}

export interface IngestStartResponse {
  status: string;
  backend: string;
}

export interface IngestProgress {
  backend: string;
  phase: string;
  detail: string;
  docs_processed: number;
  docs_total: number | null;
  chunks_new: number;
  chunks_skipped: number;
  chunks_target: number | null;
  total_chunks: number | null;
  elapsed_seconds: number;
  error: string | null;
}

export interface IngestStatusResponse {
  jobs: Record<string, IngestProgress>;
}

export interface BackendConfig {
  id: string;
  type: "zim" | "plaintext";
  paths: string[];
  description?: string;
  min_text_length?: number;
}

export interface DropBackendResponse {
  status: string;
  backend_id: string;
}

export interface ConfigResponse {
  backends: BackendConfig[];
}

export interface ValidateResponse {
  valid: boolean;
  errors: string[];
}

export interface DocumentResponse {
  backend: string;
  locator: string;
  text: string;
}
