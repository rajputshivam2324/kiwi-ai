import "dotenv/config";
import express from "express";
import cors from "cors";
import { config } from "./config.js";
import { chatRouter } from "./routes/chat.js";
import { getMCPClient, disconnectMCP, getMCPTools } from "./mcp/mcpClient.js";

const app = express();
app.use(cors({ origin: config.corsOrigin }));
app.use(express.json());

app.use("/api/chat", chatRouter);

app.get("/health", (_req, res) => {
  res.json({ status: "ok", service: "ai-trading-assistant-backend" });
});

// Diagnostic: list available MCP tools
app.get("/api/tools", async (_req, res) => {
  try {
    const tools = await getMCPTools();
    res.json({
      count: tools.length,
      tools: tools.map((t) => ({ name: t.name, description: t.description })),
    });
  } catch (err) {
    res.status(500).json({ error: "MCP not connected", details: String(err) });
  }
});

// Graceful shutdown handler
async function shutdown() {
  console.log("\nShutting down...");
  await disconnectMCP();
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

app.listen(config.port, async () => {
  console.log(`Backend listening on http://localhost:${config.port}`);

  if (!config.gemini?.apiKey) {
    console.warn("⚠️  GEMINI_API_KEY is not set. Set it in .env to enable chat.");
  }

  if (config.mcp.useStubTools) {
    console.log("📦 Using stub MCP tools (MCP_USE_STUB_TOOLS=true)");
    console.log("   Set MCP_USE_STUB_TOOLS=false to connect to Groww MCP server.");
  } else {
    console.log("🔌 Attempting to connect to Groww MCP server...");
    console.log("   This will open a browser for authentication on first run.");
    try {
      await getMCPClient();
      console.log("✅ Connected to Groww MCP server successfully!");
    } catch (error) {
      console.error("❌ Failed to connect to Groww MCP:", error);
      console.log("   Falling back to stub tools for this session.");
    }
  }
});
