import { spawn, spawnSync } from "node:child_process";
import path from "node:path";

const PORT = process.env.PLAYWRIGHT_APP_PORT || "3011";
const SERVER_URL = `http://127.0.0.1:${PORT}`;

async function responds() {
  try {
    const response = await fetch(SERVER_URL, { signal: AbortSignal.timeout(2_000) });
    return response.ok;
  } catch {
    return false;
  }
}

async function waitForServer(child) {
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`Next test server exited before readiness (code ${child.exitCode}).`);
    if (await responds()) return;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error("Next test server did not become ready within 120 seconds.");
}

function terminateTree(child) {
  if (child.exitCode !== null) return;
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore", windowsHide: true });
  } else {
    child.kill("SIGTERM");
  }
}

export default async function globalSetup() {
  if (await responds()) return async () => {};

  const nextCli = path.resolve("node_modules", "next", "dist", "bin", "next");
  const child = spawn(process.execPath, [nextCli, "dev", "-p", PORT, "-H", "127.0.0.1"], {
    cwd: process.cwd(),
    env: { ...process.env, NEXT_DIST_DIR: process.env.NEXT_DIST_DIR || ".next-e2e" },
    stdio: "inherit",
    windowsHide: true,
  });

  try {
    await waitForServer(child);
  } catch (error) {
    terminateTree(child);
    throw error;
  }

  return async () => {
    terminateTree(child);
  };
}
