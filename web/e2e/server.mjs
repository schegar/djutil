// Spawn the FastAPI test server: temp DATA_DIR, demo seed, built SPA.
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const webDir = fileURLToPath(new URL("..", import.meta.url));
const repoRoot = join(webDir, "..");
const dataDir = mkdtempSync(join(tmpdir(), "djutil-e2e-"));

const env = {
  ...process.env,
  DJUTIL_DATA_DIR: dataDir,
  DJUTIL_ADMIN_PASSWORD_HASH:
    // argon2 hash of "e2epw"
    "$argon2id$v=19$m=65536,t=3,p=4$7xOc5GiEnwzvA8c23+YvtQ$Zk+R2q3yKwLelIfTebFTeBKdR4e3gkr6eFdMgielr2M",
  DJUTIL_AGENT_TOKEN: "e2e-token",
  DJUTIL_SESSION_SECRET: "e2e-secret",
  DJUTIL_COOKIE_SECURE: "false",
  DJUTIL_STATIC_DIR: join(webDir, "dist"),
};

const uv = process.platform === "win32" ? "uv.exe" : "uv";

const seed = spawnSync(
  uv,
  ["run", "python", "-m", "djutil_server", "seed-demo", "--tracks", "500"],
  { cwd: repoRoot, env, stdio: "inherit" },
);
if (seed.status !== 0) {
  console.error("seed-demo failed");
  process.exit(1);
}

const server = spawn(
  uv,
  [
    "run", "python", "-m", "djutil_server", "serve",
    "--host", "127.0.0.1", "--port", "8877",
  ],
  { cwd: repoRoot, env, stdio: "inherit" },
);
process.on("exit", () => server.kill());
process.on("SIGINT", () => { server.kill(); process.exit(0); });
process.on("SIGTERM", () => { server.kill(); process.exit(0); });
