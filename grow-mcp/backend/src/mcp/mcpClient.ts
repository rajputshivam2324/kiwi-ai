/**
 * MCP Client for connecting to Groww MCP Server.
 *
 * Uses @modelcontextprotocol/sdk to connect via stdio to the mcp-remote bridge,
 * which in turn connects to https://mcp.groww.in/mcp
 *
 * Authentication flow:
 * 1. First run opens browser for Groww OAuth
 * 2. After auth, token is cached locally
 * 3. Subsequent runs use cached token
 */

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { config } from "../config.js";

export interface MCPTool {
    name: string;
    description?: string;
    inputSchema: {
        type: "object";
        properties: Record<string, unknown>;
        required?: string[];
    };
}

export interface MCPToolResult {
    content: Array<{ type: "text"; text: string } | { type: string;[key: string]: unknown }>;
    isError?: boolean;
}

let mcpClient: Client | null = null;
let mcpTransport: StdioClientTransport | null = null;
let cachedTools: MCPTool[] | null = null;
let connectionPromise: Promise<void> | null = null;

/**
 * Get the MCP client, connecting if not already connected.
 * Returns null if MCP is not configured or stub tools should be used.
 */
export async function getMCPClient(): Promise<Client | null> {
    if (config.mcp.useStubTools) {
        console.log("[MCP] Using stub tools (MCP_USE_STUB_TOOLS=true)");
        return null;
    }

    if (mcpClient) {
        return mcpClient;
    }

    // Prevent multiple simultaneous connection attempts
    if (connectionPromise) {
        await connectionPromise;
        return mcpClient;
    }

    connectionPromise = connectMCP();
    await connectionPromise;
    connectionPromise = null;

    return mcpClient;
}

async function connectMCP(): Promise<void> {
    console.log("[MCP] Connecting to Groww MCP server...");

    try {
        // Use mcp-remote to connect to Groww's remote MCP server
        // Command: npx mcp-remote https://mcp.groww.in/mcp
        const command = config.mcp.command || "npx";
        const args = config.mcp.args || [
            "-y",
            "mcp-remote",
            "https://mcp.groww.in/mcp",
        ];

        console.log(`[MCP] Spawning: ${command} ${args.join(" ")}`);

        // Filter out undefined values from process.env
        const envVars: Record<string, string> = {};
        for (const [key, value] of Object.entries(process.env)) {
            if (value !== undefined) {
                envVars[key] = value;
            }
        }

        mcpTransport = new StdioClientTransport({
            command,
            args,
            env: envVars,
        });

        mcpClient = new Client(
            {
                name: "groww-trading-assistant",
                version: "1.0.0",
            }
        );

        await mcpClient.connect(mcpTransport);
        console.log("[MCP] Successfully connected to Groww MCP server");

        // Cache the tools list
        await refreshTools();
    } catch (error) {
        console.error("[MCP] Failed to connect:", error);
        mcpClient = null;
        mcpTransport = null;
        throw error;
    }
}

/**
 * Refresh the cached list of available tools from the MCP server.
 */
async function refreshTools(): Promise<void> {
    if (!mcpClient) {
        cachedTools = null;
        return;
    }

    try {
        const result = await mcpClient.listTools();
        cachedTools = result.tools.map((tool) => ({
            name: tool.name,
            description: tool.description,
            inputSchema: tool.inputSchema as MCPTool["inputSchema"],
        }));
        console.log(
            `[MCP] Loaded ${cachedTools.length} tools:`,
            cachedTools.map((t) => t.name).join(", ")
        );
    } catch (error) {
        console.error("[MCP] Failed to list tools:", error);
        cachedTools = null;
    }
}

/**
 * Get available tools from the MCP server.
 * Returns empty array if not connected.
 */
export async function getMCPTools(): Promise<MCPTool[]> {
    await getMCPClient();
    return cachedTools ?? [];
}

/**
 * Execute a tool on the MCP server.
 */
export async function executeMCPTool(
    name: string,
    args: Record<string, unknown>
): Promise<MCPToolResult> {
    const client = await getMCPClient();

    if (!client) {
        return {
            content: [{ type: "text", text: "MCP not connected. Using stub mode." }],
            isError: true,
        };
    }

    console.log(`[MCP] Calling tool: ${name}`, JSON.stringify(args));

    try {
        const result = await client.callTool({
            name,
            arguments: args,
        });

        const content = (result.content as MCPToolResult["content"]) ?? [];
        console.log(
            `[MCP] Tool ${name} returned:`,
            content.map((c) => {
                if (c.type === "text" && "text" in c) {
                    return (c.text as string).substring(0, 100);
                }
                return c.type;
            }).join(", ")
        );

        return {
            content,
            isError: result.isError as boolean | undefined,
        };
    } catch (error) {
        console.error(`[MCP] Tool ${name} failed:`, error);
        return {
            content: [
                {
                    type: "text",
                    text: `Error calling ${name}: ${error instanceof Error ? error.message : String(error)}`,
                },
            ],
            isError: true,
        };
    }
}

/**
 * Disconnect from the MCP server.
 */
export async function disconnectMCP(): Promise<void> {
    if (mcpClient) {
        try {
            await mcpClient.close();
        } catch {
            // Ignore close errors
        }
        mcpClient = null;
    }

    if (mcpTransport) {
        try {
            await mcpTransport.close();
        } catch {
            // Ignore close errors
        }
        mcpTransport = null;
    }

    cachedTools = null;
    console.log("[MCP] Disconnected");
}

/**
 * Check if MCP is connected.
 */
export function isMCPConnected(): boolean {
    return mcpClient !== null;
}
