import { Router, type Request, type Response } from "express";
import { chatStream } from "../services/nvidiaChat.js";
import { z } from "zod";

const ChatBodySchema = z.object({
  messages: z.array(
    z.object({
      role: z.enum(["user", "model"]),
      content: z.string().min(1),
    })
  ).min(1),
});

export const chatRouter = Router();

// ── Request deduplication ──────────────────────────────────────────────────
// Tracks in-flight requests by a hash of the last user message.
// Prevents duplicate API calls from frontend retries or double-clicks.
const inFlightRequests = new Set<string>();

function getRequestKey(messages: Array<{ role: string; content: string }>): string {
  const last = [...messages].reverse().find((m) => m.role === "user");
  return last ? `${messages.length}:${last.content.substring(0, 200)}` : "";
}

chatRouter.post("/", async (req: Request, res: Response): Promise<void> => {
  try {
    const parsed = ChatBodySchema.safeParse(req.body);
    if (!parsed.success) {
      res.status(400).json({
        error: "Invalid request",
        details: parsed.error.flatten(),
      });
      return;
    }

    // Deduplicate: reject if an identical request is already in-flight
    const requestKey = getRequestKey(parsed.data.messages);
    if (requestKey && inFlightRequests.has(requestKey)) {
      console.warn(`[Chat] Duplicate request rejected: "${requestKey.substring(0, 60)}..."`);
      res.status(429).json({ error: "Request already in progress. Please wait." });
      return;
    }

    if (requestKey) inFlightRequests.add(requestKey);

    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive"
    });
    
    try {
      for await (const chunk of chatStream(parsed.data)) {
        res.write(`data: ${JSON.stringify(chunk)}\n\n`);
      }
      res.write('data: [DONE]\n\n');
      res.end();
    } finally {
      // Always clean up, even on error
      if (requestKey) inFlightRequests.delete(requestKey);
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : "Chat failed";
    console.error("[SSE Stream Error]:", message);
    if (!res.headersSent) {
      const status = message.includes("GEMINI_API_KEY") ? 503 : 500;
      res.status(status).json({ error: message });
    } else {
      res.write(`data: {"error": ${JSON.stringify(message)}}\n\n`);
      res.write('data: [DONE]\n\n');
      res.end();
    }
  }
});
