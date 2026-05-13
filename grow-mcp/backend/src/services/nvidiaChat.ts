import OpenAI, { APIError } from "openai";
import { config } from "../config.js";
import {
  getMCPTools,
  executeMCPTool,
  isMCPConnected,
  type MCPTool,
} from "../mcp/mcpClient.js";
import { routeToAgent } from "../agents/agentRouter.js";
import { getDefaultAgent, type AgentDef } from "../agents/agents.js";

// ── Singleton OpenAI instance (pointing at Gemini OpenAI-compatible API) ─────────
let _aiInstance: OpenAI | null = null;
function getAI(): OpenAI {
  if (!_aiInstance) {
    if (!config.gemini.apiKey) throw new Error("GEMINI_API_KEY is not set");
    _aiInstance = new OpenAI({
      apiKey: config.gemini.apiKey,
      baseURL: config.gemini.baseURL,
    });
  }
  return _aiInstance;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isRetryableGeminiError(err: unknown): boolean {
  if (err instanceof APIError) {
    const s = err.status;
    if (s === 429 || s === 503 || s === 502 || s === 500) return true;
  }
  const msg = err instanceof Error ? err.message : String(err ?? "");
  return /\b429\b|rate limit|RESOURCE_EXHAUSTED|overloaded|unavailable/i.test(msg);
}

function parseRetryAfterMs(err: unknown): number | null {
  if (!(err instanceof APIError) || !err.headers) return null;
  const raw = err.headers.get("retry-after");
  if (!raw) return null;
  const sec = parseInt(raw.trim(), 10);
  if (!Number.isFinite(sec) || sec < 0) return null;
  return sec * 1000;
}

function clipToolContent(text: string, maxChars: number): string {
  if (text.length <= maxChars) return text;
  return `${text.slice(0, maxChars)}\n\n[Truncated: tool output exceeded ${maxChars} characters.]`;
}

/**
 * Gemini chat with exponential backoff on 429 / transient 5xx (Google rate limits).
 */
async function createGeminiChatStream(
  ai: OpenAI,
  params: {
    model: string;
    messages: unknown;
    temperature: number;
    stream: true;
    tools?: unknown;
  }
): Promise<AsyncIterable<OpenAI.Chat.Completions.ChatCompletionChunk>> {
  const maxRetries = config.gemini.maxRetries;
  const baseMs = config.gemini.initialBackoffMs;
  const capMs = config.gemini.maxBackoffMs;
  let lastErr: unknown;

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      const stream = (await ai.chat.completions.create(
        params as OpenAI.Chat.ChatCompletionCreateParamsStreaming
      )) as AsyncIterable<OpenAI.Chat.Completions.ChatCompletionChunk>;
      return stream;
    } catch (err) {
      lastErr = err;
      if (!isRetryableGeminiError(err) || attempt >= maxRetries - 1) {
        throw err;
      }
      let waitMs = Math.min(capMs, baseMs * 2 ** attempt) + Math.floor(Math.random() * 500);
      const raMs = parseRetryAfterMs(err);
      if (raMs != null) {
        waitMs = Math.max(waitMs, raMs);
      }
      console.warn(
        `[Chat] Gemini rate-limit or transient error; backing off ${Math.round(waitMs)}ms (retry ${attempt + 2}/${maxRetries})`
      );
      await delay(waitMs);
    }
  }
  throw lastErr;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system" | "tool";
  content?: string;
  name?: string;
  tool_call_id?: string;
  tool_calls?: Array<{
    id: string;
    type: "function";
    function: { name: string; arguments: string };
  }>;
}

export interface ChatRequest {
  messages: Array<{ role: "user" | "model" | "assistant"; content: string }>;
}

/**
 * Resolve $ref references in a JSON Schema by inlining definitions from $defs.
 * Then sanitize for Gemini compatibility (strip unsupported fields).
 */
function resolveAndSanitize(schema: any, defs: Record<string, any>): any {
  if (!schema || typeof schema !== "object") return schema;
  if (Array.isArray(schema)) return schema.map((item) => resolveAndSanitize(item, defs));

  // Resolve $ref by inlining the definition
  if (schema["$ref"] && typeof schema["$ref"] === "string") {
    const refPath = schema["$ref"]; // e.g. "#/$defs/EntityType"
    const match = refPath.match(/^#\/\$defs\/(.+)$/);
    if (match && defs[match[1]]) {
      // Merge the resolved def with any sibling fields (like description)
      const resolved = { ...defs[match[1]] };
      const { $ref, ...siblings } = schema;
      return resolveAndSanitize({ ...resolved, ...siblings }, defs);
    }
    // If we can't resolve, just strip the $ref and treat as string
    return { type: "string", description: schema.description ?? "" };
  }

  const STRIP_KEYS = new Set([
    "additionalProperties", "$schema", "$defs", "default", "examples",
    "title", "minLength", "maxLength", "minItems", "maxItems",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "pattern", "format", "uniqueItems",
  ]);

  const cleaned: any = {};
  for (const [key, value] of Object.entries(schema)) {
    if (STRIP_KEYS.has(key)) continue;
    cleaned[key] = resolveAndSanitize(value, defs);
  }

  // Ensure object types always have a properties field
  if (cleaned.type === "object" && !cleaned.properties) {
    cleaned.properties = {};
  }

  return cleaned;
}

/**
 * Convert a tool definition to OpenAI function declaration format.
 * Resolves $ref and sanitizes schema for Gemini compatibility.
 */
function toolToOpenAIDeclaration(t: MCPTool) {
  const fullSchema = t.inputSchema as any;
  const defs = fullSchema["$defs"] ?? fullSchema["definitions"] ?? {};
  const sanitizedProps = resolveAndSanitize(fullSchema.properties ?? {}, defs);
  return {
    type: "function" as const,
    function: {
      name: t.name,
      description: t.description ?? "",
      parameters: {
        type: "object",
        properties: sanitizedProps,
        required: t.inputSchema.required ?? [],
      },
    },
  };
}

/**
 * Parse model-emitted function arguments. Gemini sometimes concatenates multiple
 * JSON objects when parallel tool deltas share the same `index`; we recover the
 * first well-formed object so the correct tool still receives usable params.
 */
function parseToolArguments(argsStr: string): Record<string, unknown> {
  const trimmed = argsStr.trim();
  if (!trimmed) return {};
  try {
    return JSON.parse(trimmed) as Record<string, unknown>;
  } catch {
    const first = extractFirstJsonObject(trimmed);
    if (first) {
      try {
        return JSON.parse(first) as Record<string, unknown>;
      } catch {
        /* fall through */
      }
    }
    console.error("Failed to parse tool arguments:", argsStr);
    return {};
  }
}

function extractFirstJsonObject(s: string): string | null {
  const start = s.indexOf("{");
  if (start === -1) return null;
  let depth = 0;
  let inString = false;
  let escape = false;
  for (let i = start; i < s.length; i++) {
    const c = s[i];
    if (escape) {
      escape = false;
      continue;
    }
    if (c === "\\" && inString) {
      escape = true;
      continue;
    }
    if (c === '"') {
      inString = !inString;
      continue;
    }
    if (inString) continue;
    if (c === "{") depth++;
    else if (c === "}") {
      depth--;
      if (depth === 0) return s.slice(start, i + 1);
    }
  }
  return null;
}

type AggregatedToolCall = {
  id: string;
  type: "function";
  function: { name: string; arguments: string };
};

/**
 * Accumulate streaming tool_call deltas. OpenAI streams by `index` with a stable
 * `id` per call; Gemini's OpenAI shim occasionally reuses `index` for distinct
 * tools, which must not share one arguments buffer.
 */
function createToolCallAggregator() {
  const byId = new Map<string, AggregatedToolCall>();
  const lastIdByIndex = new Map<number, string>();
  let synth = 0;
  const synthId = () => `call_${Date.now().toString(36)}_${(synth++).toString(36)}`;

  return {
    addDelta(tc: {
      index?: number;
      id?: string;
      function?: { name?: string; arguments?: string };
    }) {
      const idx = typeof tc.index === "number" ? tc.index : 0;
      const nameFrag = tc.function?.name ?? "";
      const argsFrag = tc.function?.arguments ?? "";

      let callId = tc.id;

      if (!callId) {
        const mapped = lastIdByIndex.get(idx);
        if (mapped) {
          const prev = byId.get(mapped);
          if (
            nameFrag &&
            prev?.function.name &&
            prev.function.name !== nameFrag &&
            prev.function.arguments.length > 0
          ) {
            // Same stream index, new tool — do not append to the previous call.
            callId = synthId();
            lastIdByIndex.set(idx, callId);
          } else {
            callId = mapped;
          }
        }
      }

      if (!callId) {
        callId = tc.id ?? synthId();
        lastIdByIndex.set(idx, callId);
      }

      if (tc.id && tc.id !== callId) {
        callId = tc.id;
        lastIdByIndex.set(idx, callId);
      }

      let agg = byId.get(callId);
      if (!agg) {
        agg = {
          id: callId,
          type: "function",
          function: { name: nameFrag, arguments: "" },
        };
        byId.set(callId, agg);
        lastIdByIndex.set(idx, callId);
      }

      if (nameFrag) {
        if (!agg.function.name) agg.function.name = nameFrag;
        else if (agg.function.name !== nameFrag && agg.function.arguments.length > 0) {
          const splitId = synthId();
          lastIdByIndex.set(idx, splitId);
          const next: AggregatedToolCall = {
            id: splitId,
            type: "function",
            function: { name: nameFrag, arguments: argsFrag },
          };
          byId.set(splitId, next);
          return;
        }
      }

      if (argsFrag) agg.function.arguments += argsFrag;
    },
    toArray(): AggregatedToolCall[] {
      return [...byId.values()];
    },
  };
}

/**
 * Filter tools to only include those allowed by the agent.
 * If the allowlist uses outdated names vs the MCP server, the intersection can be
 * empty — fall back to all tools so the assistant stays usable (with a loud log).
 */
function filterToolsForAgent<T extends { name: string }>(
  tools: T[],
  agent: AgentDef
): T[] {
  if (agent.allowedTools.length === 0) return tools;
  const filtered = tools.filter((t) => agent.allowedTools.includes(t.name));
  if (filtered.length === 0 && tools.length > 0) {
    console.warn(
      `[Chat] Agent "${agent.id}" allowlist matched 0 of ${tools.length} MCP tools; ` +
        `using all tools. Update agents.ts allowedTools to match Groww tool names.`
    );
    return tools;
  }
  return filtered;
}

/**
 * Execute a tool via MCP.
 */
async function executeTool(
  name: string,
  args: Record<string, unknown>
): Promise<{ content: Array<{ type: "text"; text: string }>; isError?: boolean }> {
  if (!isMCPConnected()) {
    return {
      content: [{ type: "text", text: "Error: Groww MCP is not connected. Cannot execute tool." }],
      isError: true,
    };
  }

  const result = await executeMCPTool(name, args);
  const textContent = result.content
    .filter((c): c is { type: "text"; text: string } => c.type === "text" && "text" in c)
    .map((c) => ({ type: "text" as const, text: c.text }));

  if (textContent.length === 0) {
    textContent.push({
      type: "text",
      text: JSON.stringify(result.content),
    });
  }

  return { content: textContent, isError: result.isError };
}

export async function* chatStream(request: ChatRequest) {
  if (!request.messages?.length) {
    throw new Error("At least one message is required");
  }

  const ai = getAI();
  const model = config.gemini.model;

  // ── Step 1: Route to the best agent ──
  const lastUserMsg = [...request.messages].reverse().find((m) => m.role === "user");
  const agent = routeToAgent(lastUserMsg?.content ?? "");
  console.log(`[Chat] Routed to agent: ${agent.emoji} ${agent.name} (${agent.id})`);

  yield { type: "agent", agent: { id: agent.id, name: agent.name, emoji: agent.emoji } };

  // ── Step 2: Get tools from Groww MCP ───────────────
  let toolDefinitions: MCPTool[];

  try {
    const mcpTools = await getMCPTools();
    if (mcpTools.length === 0) {
      throw new Error("Groww MCP server returned no tools.");
    }
    toolDefinitions = filterToolsForAgent(mcpTools, agent);
    console.log(`[Chat] Using ${toolDefinitions.length}/${mcpTools.length} MCP tools for ${agent.id}`);
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    console.error("[Chat] MCP tools unavailable:", msg);
    throw new Error(`Groww MCP is not connected. Error: ${msg}`);
  }

  const tools = toolDefinitions.map(toolToOpenAIDeclaration);

  // ── Step 3: Build conversation ──────────────
  const conversation: ChatMessage[] = [
    { role: "system", content: agent.systemPrompt }
  ];

  for (const msg of request.messages) {
    const mappedRole = msg.role === 'model' ? 'assistant' : msg.role;
    conversation.push({ role: mappedRole as "user" | "assistant", content: msg.content });
  }

  // ── Step 4: Agentic tool loop ────────────────────────────────────────
  const maxToolRounds = 10;
  let round = 0;
  let lastText = "";


  while (round < maxToolRounds) {
    if (round > 0 && config.gemini.toolRoundDelayMs > 0) {
      await delay(config.gemini.toolRoundDelayMs);
    }

    if (round === 0) {
      console.log(`[Chat] Sending ${tools.length} tools to Gemini (model: ${model})`);
    }

    let completion;
    try {
      completion = await createGeminiChatStream(ai, {
        model,
        messages: conversation as any,
        temperature: 0.4,
        stream: true,
        tools: tools as any,
      });
    } catch (apiError: any) {
      console.error("[Chat] Gemini API error:", {
        status: apiError?.status,
        message: apiError?.message,
        error: apiError?.error,
        body: apiError?.body,
      });
      throw apiError;
    }

    let currentText = "";
    let currentReasoning = "";
    const toolAgg = createToolCallAggregator();

    let displayed = lastText ? lastText + "\\n\\n" : "";
    let isThinking = false;

    for await (const chunk of completion) {
      const delta = chunk.choices[0]?.delta as any;

      const reasoning = delta?.reasoning_content;
      if (reasoning) {
        if (!isThinking) {
          displayed += "_Thinking..._\\n\\n> ";
          isThinking = true;
        }
        currentReasoning += reasoning;
        const newLines = reasoning.replace(/\\n/g, '\\n> ');
        displayed += newLines;
        yield { type: "text", content: displayed, overwrite: true };
      }

      if (delta?.content) {
        if (isThinking && currentText === "") {
          displayed += "\\n\\n---\\n\\n";
          isThinking = false;
        }
        currentText += delta.content;

        // Simulating the typewriter effect for fast connections
        displayed += delta.content;
        yield { type: "text", content: displayed, overwrite: true };
      }

      if (delta?.tool_calls) {
        for (const tc of delta.tool_calls) {
          toolAgg.addDelta(tc);
        }
      }
    }

    const functionCalls = toolAgg.toArray();

    if (currentReasoning || currentText || functionCalls.length > 0) {
      lastText = displayed;

      const assistantMessage: ChatMessage = {
        role: "assistant",
        content: currentText || "",
      };

      if (functionCalls.length > 0) {
        assistantMessage.tool_calls = functionCalls;
      }

      conversation.push(assistantMessage);
    }

    if (functionCalls.length === 0) {
      return;
    }

    // ── Execute tool calls in parallel ──────────────────────
    const toolPromises = functionCalls.map(async (fc: any) => {
      const name = fc.function.name;
      const argsStr = fc.function.arguments;
      const args = parseToolArguments(argsStr);


      const result = await executeTool(name, args);
      const joined =
        result.content
          .filter((c): c is { type: "text"; text: string } => c.type === "text")
          .map((c) => c.text)
          .join("\\n") || JSON.stringify({ isError: result.isError });
      const resultText = clipToolContent(joined, config.gemini.maxToolResultChars);

      return { tool_call_id: fc.id, name, resultText };
    });

    const toolResponses = await Promise.all(toolPromises);

    for (const tr of toolResponses) {
      conversation.push({
        role: "tool",
        tool_call_id: tr.tool_call_id,
        content: tr.resultText,
      } as ChatMessage);
    }

    round++;
  }


}
