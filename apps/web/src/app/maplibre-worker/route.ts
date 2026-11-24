import { readFile } from "node:fs/promises";
import path from "node:path";

// MapLibre 6 looks for its worker next to its own bundle, which the dev bundler moves, so the
// lookup 404s and the map stays blank. Serve the installed worker from one fixed local URL.
export async function GET() {
  const file = path.join(process.cwd(), "node_modules", "maplibre-gl", "dist", "maplibre-gl-worker.mjs");
  return new Response(await readFile(file), {
    headers: { "Content-Type": "text/javascript; charset=utf-8", "Cache-Control": "no-store" },
  });
}
