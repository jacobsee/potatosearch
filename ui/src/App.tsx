import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Configuration from "./pages/Configuration";
import Indexing from "./pages/Indexing";
import Query from "./pages/Query";
import MCP from "./pages/MCP";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/configuration" element={<Configuration />} />
        <Route path="/indexing" element={<Indexing />} />
        <Route path="/query" element={<Query />} />
        <Route path="/mcp" element={<MCP />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
