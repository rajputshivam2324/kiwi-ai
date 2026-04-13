import OpenAI from "openai";
import { config } from "../config.js";
import {
  getMCPTools,
  executeMCPTool,
  isMCPConnected,
  type MCPTool,
} from "../mcp/mcpClient.js";
import { routeToAgent } from "../agents/agentRouter.js";
import { getDefaultAgent, type AgentDef } from "../agents/agents.js";

// ── Singleton OpenAI instance ─────────
let _aiInstance: OpenAI | null = null;
function getAI(): OpenAI {
  if (!_aiInstance) {
    if (!config.nvidia.apiKey) throw new Error("NVIDIA_API_KEY is not set");
    _aiInstance = new OpenAI({
      apiKey: config.nvidia.apiKey,
      baseURL: config.nvidia.baseURL,
    });
  }
  return _aiInstance;
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
 * Convert a tool definition to OpenAI function declaration format.
 */
function toolToOpenAIDeclaration(t: MCPTool) {
  return {
    type: "function" as const,
    function: {
      name: t.name,
      description: t.description ?? "",
      parameters: {
        type: "object",
        properties: t.inputSchema.properties,
        required: t.inputSchema.required ?? [],
      },
    },
  };
}

/**
 * Filter tools to only include those allowed by the agent.
 */
function filterToolsForAgent<T extends { name: string }>(
  tools: T[],
  agent: AgentDef
): T[] {
  if (agent.allowedTools.length === 0) return tools;
  return tools.filter((t) => agent.allowedTools.includes(t.name));
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
  const model = config.nvidia.model;

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

  const tools = [
    ...toolDefinitions.map(toolToOpenAIDeclaration),
    {
      type: "function" as const,
      function: {
        name: "render_finance_card",
        description: "Renders a visually stunning metallic card in the user's UI with strictly the most important numerical financial metrics.",
        parameters: {
          type: "object",
          properties: {
            title: { type: "string" },
            data: { type: "object" }
          },
          required: ["title", "data"]
        }
      }
    }
  ];

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
  const globalToolResults: Array<{ name: string; data: any }> = [];

  while (round < maxToolRounds) {
    const completion = await ai.chat.completions.create({
      model,
      messages: conversation as any,
      temperature: 0.4,
      stream: true,
      tools: tools as any,
    });

    let currentText = "";
    let currentReasoning = "";
    let streamToolCalls: Record<number, any> = {};

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
          if (!streamToolCalls[tc.index]) {
            streamToolCalls[tc.index] = {
              id: tc.id,
              type: "function",
              function: { name: tc.function?.name || "", arguments: tc.function?.arguments || "" }
            };
          } else {
            if (tc.function?.arguments) {
              streamToolCalls[tc.index].function.arguments += tc.function.arguments;
            }
          }
        }
      }
    }

    const functionCalls = Object.values(streamToolCalls);

    if (currentReasoning || currentText || functionCalls.length > 0) {
      lastText = displayed;

      const assistantMessage: ChatMessage = {
        role: "assistant",
        content: currentText || undefined,
      };

      if (functionCalls.length > 0) {
        assistantMessage.tool_calls = functionCalls;
      }

      conversation.push(assistantMessage);
    }

    if (functionCalls.length === 0) {
      if (globalToolResults.length > 0) {
        yield { type: "tools", toolResults: globalToolResults };
      }
      return;
    }

    // ── Execute tool calls in parallel ──────────────────────
    const toolPromises = functionCalls.map(async (fc: any) => {
      const name = fc.function.name;
      const argsStr = fc.function.arguments;
      let args: Record<string, unknown> = {};
      try {
        args = argsStr ? JSON.parse(argsStr) : {};
      } catch (e) {
        console.error("Failed to parse tool arguments:", argsStr);
      }

      if (name === "render_finance_card") {
        globalToolResults.push({ name: (args.title as string) || "FINANCE DETAILS", data: args.data });
        return {
          tool_call_id: fc.id,
          name,
          resultText: "Card successfully rendered on the user's screen.",
        };
      }

      const result = await executeTool(name, args);
      const resultText =
        result.content
          .filter((c): c is { type: "text"; text: string } => c.type === "text")
          .map((c) => c.text)
          .join("\\n") || JSON.stringify({ isError: result.isError });

      return { tool_call_id: fc.id, name, resultText };
    });

    const toolResponses = await Promise.all(toolPromises);

    for (const tr of toolResponses) {
      conversation.push({
        role: "tool",
        tool_call_id: tr.tool_call_id,
        name: tr.name,
        content: tr.resultText,
      } as ChatMessage);
    }

    round++;
  }

  if (globalToolResults.length > 0) {
    yield { type: "tools", toolResults: globalToolResults };
  }
}
