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
  gemini: {
    apiKey: process.env.GEMINI_API_KEY,
    baseURL: process.env.GEMINI_BASE_URL ?? "https://generativelanguage.googleapis.com/v1beta/openai/",
    model: process.env.GEMINI_MODEL ?? "gemini-2.5-flash",
    /** Retries for 429 / 5xx on each chat.completions.create (streaming). */
    maxRetries: Math.max(1, Number(process.env.GEMINI_MAX_RETRIES ?? 8)),
    initialBackoffMs: Math.max(200, Number(process.env.GEMINI_BACKOFF_INITIAL_MS ?? 1500)),
    maxBackoffMs: Math.max(1000, Number(process.env.GEMINI_BACKOFF_MAX_MS ?? 120_000)),
    /** Pause before a follow-up Gemini call after tools run (reduces 429 bursts). */
    toolRoundDelayMs: Math.max(0, Number(process.env.GEMINI_TOOL_ROUND_DELAY_MS ?? 600)),
    maxToolResultChars: Math.max(8_000, Number(process.env.GEMINI_MAX_TOOL_RESULT_CHARS ?? 120_000)),
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
