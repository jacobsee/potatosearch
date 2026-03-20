import { useEffect, useState } from "react";
import { api, type BackendsResponse, type BackendInfo } from "../api/client";

export default function MCP() {
  const [backends, setBackends] = useState<Record<string, BackendInfo>>({});
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    api.get<BackendsResponse>("/api/backends").then(setBackends).catch(() => {});
  }, []);

  const backendList = Object.values(backends);
  const hasBackends = backendList.length > 0;

  const copy = (text: string, id: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(id);
      setTimeout(() => setCopied(null), 2000);
    });
  };

  const mcpConfig = JSON.stringify(
    {
      mcpServers: {
        potatosearch: {
          type: "streamable-http",
          url: "http://your-server:8391/mcp",
        },
      },
    },
    null,
    2,
  );

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-stone-900">MCP Integration</h1>
        <p className="text-stone-500 mt-1">
          Use potatosearch as an MCP server so AI agents can search your indexed
          corpora
        </p>
      </div>

      {/* Overview */}
      <div className="bg-white rounded-xl border border-stone-200 p-6 mb-6">
        <h2 className="text-lg font-semibold text-stone-900 mb-3">
          How it works
        </h2>
        <p className="text-sm text-stone-600 leading-relaxed">
          The{" "}
          <a
            href="https://modelcontextprotocol.io"
            target="_blank"
            rel="noopener noreferrer"
            className="text-amber-600 hover:text-amber-700 underline"
          >
            Model Context Protocol (MCP)
          </a>{" "}
          lets AI assistants discover and use external tools.
          potatosearch serves MCP over Streamable HTTP at{" "}
          <code className="text-xs bg-stone-100 px-1.5 py-0.5 rounded">
            /mcp
          </code>{" "}
          — point your client at the URL and it connects directly. No local
          install, data, or GPU required on the client side.
        </p>
        <div className="mt-4 space-y-3">
          <div className="flex gap-3 p-3 bg-stone-50 rounded-lg">
            <code className="text-sm font-semibold text-amber-700 whitespace-nowrap">
              list_backends
            </code>
            <span className="text-sm text-stone-600">
              Returns all configured backends with their descriptions and index
              stats. The agent calls this first to discover what knowledge is
              available.
            </span>
          </div>
          <div className="flex gap-3 p-3 bg-stone-50 rounded-lg">
            <code className="text-sm font-semibold text-amber-700 whitespace-nowrap">
              search
            </code>
            <span className="text-sm text-stone-600">
              Semantic search across all or a subset of backends. Accepts a
              natural language query, optional backend filter, and top_k
              parameter.
            </span>
          </div>
          <div className="flex gap-3 p-3 bg-stone-50 rounded-lg">
            <code className="text-sm font-semibold text-amber-700 whitespace-nowrap">
              get_document
            </code>
            <span className="text-sm text-stone-600">
              Retrieve the full text of a document by its backend ID and
              locator. Use after searching to read an entire document rather
              than just the matched chunk.
            </span>
          </div>
        </div>
      </div>

      {/* Current backends */}
      {hasBackends && (
        <div className="bg-white rounded-xl border border-stone-200 p-6 mb-6">
          <h2 className="text-lg font-semibold text-stone-900 mb-3">
            Backends visible to agents
          </h2>
          <p className="text-sm text-stone-500 mb-4">
            These backends will be listed when an agent calls{" "}
            <code className="text-xs bg-stone-100 px-1.5 py-0.5 rounded">
              list_backends
            </code>
            . Add descriptions on the Configuration page to help agents
            understand what each backend contains.
          </p>
          <div className="space-y-2">
            {backendList.map((b) => (
              <div
                key={b.name}
                className="flex items-start gap-3 p-3 bg-stone-50 rounded-lg"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <code className="text-sm font-semibold text-stone-800">
                      {b.name}
                    </code>
                    <span className="text-xs text-stone-400">
                      {b.indexed_chunks.toLocaleString()} chunks
                    </span>
                  </div>
                  {b.description ? (
                    <p className="text-sm text-stone-600 mt-0.5">
                      {b.description}
                    </p>
                  ) : (
                    <p className="text-sm text-stone-400 italic mt-0.5">
                      No description — add one in Configuration to help agents
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Setup instructions */}
      <div className="bg-white rounded-xl border border-stone-200 p-6 mb-6">
        <h2 className="text-lg font-semibold text-stone-900 mb-4">Setup</h2>

        <p className="text-sm text-stone-500 mb-6">

          Add to your project&apos;s{" "}
          <code className="text-xs bg-stone-100 px-1.5 py-0.5 rounded">
            .mcp.json
          </code>
          , replacing{" "}
          <code className="text-xs bg-stone-100 px-1.5 py-0.5 rounded">
            your-server:8391
          </code>{" "}
          with the address of your running potatosearch instance.
        </p>

        <div className="space-y-6">
          <div>
            <CodeBlock
              code={mcpConfig}
              id="agent-config"
              copied={copied}
              onCopy={copy}
            />
          </div>
        </div>
      </div>

      {/* Tips */}
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-6">
        <h2 className="text-lg font-semibold text-amber-900 mb-3">Tips</h2>
        <ul className="text-sm text-amber-800 space-y-2 list-disc list-inside">
          <li>
            Add descriptions to your backends so agents understand what each
            corpus contains and can choose which ones to search.
          </li>
          <li>
            The first search query may be slower if the server needs to warm up
            its embedding model.
          </li>
        </ul>
      </div>
    </div>
  );
}

function CodeBlock({
  code,
  id,
  copied,
  onCopy,
}: {
  code: string;
  id: string;
  copied: string | null;
  onCopy: (text: string, id: string) => void;
}) {
  return (
    <div className="relative group">
      <pre className="bg-stone-900 text-stone-300 rounded-lg p-4 text-sm overflow-x-auto">
        <code>{code}</code>
      </pre>
      <button
        onClick={() => onCopy(code, id)}
        className="absolute top-2 right-2 px-2 py-1 text-xs bg-stone-700 text-stone-300 rounded hover:bg-stone-600 transition-colors opacity-0 group-hover:opacity-100"
      >
        {copied === id ? "Copied!" : "Copy"}
      </button>
    </div>
  );
}
