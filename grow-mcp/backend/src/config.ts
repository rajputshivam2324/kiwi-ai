import { config as loadEnv } from "dotenv";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootEnv = path.resolve(__dirname, "../../.env");
const localEnv = path.resolve(__dirname, "../.env");
loadEnv({ path: rootEnv });
loadEnv({ path: localEnv }); // backend/.env overrides

export const config = {
  port: Number(process.env.PORT) || 4000,
  nvidia: {
    apiKey: process.env.NVIDIA_API_KEY,
    baseURL: process.env.NVIDIA_BASE_URL,
    model: process.env.NVIDIA_MODEL ?? "moonshotai/kimi-k2-thinking",
  },
  mcp: {
    /**
     * Command to spawn the MCP server bridge.
     * Default: "npx" which will run @anthropic-ai/mcp-remote
     */
    command: process.env.MCP_COMMAND ?? "npx",
    /**
     * Arguments for the MCP command.
     * Default: Connect to Groww's remote MCP server
     */
    args: process.env.MCP_ARGS
      ? process.env.MCP_ARGS.split(",").map((s) => s.trim())
      : ["-y", "mcp-remote", "https://mcp.groww.in/mcp"],
    /**
     * When true, use built-in stub tools instead of connecting to MCP server.
     * Set MCP_USE_STUB_TOOLS=true in .env for development without Groww connection.
     */
    useStubTools: process.env.MCP_USE_STUB_TOOLS === "true",
  },
  corsOrigin: process.env.CORS_ORIGIN ?? "http://localhost:5173",
} as const;
