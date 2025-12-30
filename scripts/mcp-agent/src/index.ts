#!/usr/bin/env node
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { spawn } from "child_process";
import { readFileSync, readdirSync, existsSync } from "fs";
import { join, resolve } from "path";
import * as TOML from "toml";

interface AgentConfig {
  command: string;
  args?: string[];
  system_prompt?: string;
}

interface AgentRegistry {
  [key: string]: AgentConfig;
}

function loadAgents(baseDir: string): AgentRegistry {
  const agentsDir = join(baseDir, ".agents");
  const agents: AgentRegistry = {};

  if (!existsSync(agentsDir)) {
    return agents;
  }

  const files = readdirSync(agentsDir).filter((f) => f.endsWith(".toml"));

  for (const file of files) {
    const agentId = file.replace(".toml", "");
    const content = readFileSync(join(agentsDir, file), "utf-8");
    try {
      const config = TOML.parse(content) as AgentConfig;
      agents[agentId] = config;
    } catch {
      console.error(`Failed to parse ${file}`);
    }
  }

  return agents;
}

async function executeAgent(
  config: AgentConfig,
  prompt: string,
  cwd: string
): Promise<string> {
  return new Promise((resolve, reject) => {
    let fullPrompt = prompt;
    if (config.system_prompt) {
      fullPrompt = `${config.system_prompt}\n\n${prompt}`;
    }

    const args = config.args || [];
    console.error(`[mcp-agent] Executing: ${config.command} ${args.join(' ')} (prompt via stdin)`);

    const proc = spawn(config.command, args, {
      cwd,
      env: { ...process.env, PATH: process.env.PATH },
      shell: true,
    });

    let stdout = "";
    let stderr = "";

    // Send prompt to stdin
    proc.stdin.write(fullPrompt);
    proc.stdin.end();

    proc.stdout.on("data", (data) => {
      stdout += data.toString();
    });

    proc.stderr.on("data", (data) => {
      const chunk = data.toString();
      stderr += chunk;
      // Stream stderr to console in real-time for human visibility
      process.stderr.write(chunk);
    });

    proc.on("close", (code) => {
      if (code === 0) {
        resolve(stdout);
      } else {
        resolve(`Exit code: ${code}\n\nSTDOUT:\n${stdout}\n\nSTDERR:\n${stderr}`);
      }
    });

    proc.on("error", (err) => {
      reject(err);
    });
  });
}

async function main() {
  const baseDir = process.argv[2] || process.cwd();

  const server = new Server(
    {
      name: "mcp-agent",
      version: "1.0.0",
    },
    {
      capabilities: {
        tools: {},
      },
    }
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => {
    const currentAgents = loadAgents(baseDir);
    const agentIds = Object.keys(currentAgents).sort();

    return {
      tools: [
        {
          name: "execute",
          description: `Execute an AI agent. Agent IDs: ${agentIds.join(", ")}`,
          inputSchema: {
            type: "object" as const,
            properties: {
              agent: { type: "string", description: "Agent ID" },
              prompt: { type: "string", description: "The prompt to send to the agent" },
              cwd: { type: "string", description: "Working directory (relative or absolute)" },
            },
            required: ["agent", "prompt"],
          },
        },
      ],
    };
  });

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    if (request.params.name !== "execute") {
      throw new Error(`Unknown tool: ${request.params.name}`);
    }

    const { agent, prompt, cwd } = request.params.arguments as {
      agent: string;
      prompt: string;
      cwd?: string;
    };

    const agents = loadAgents(baseDir);
    const config = agents[agent];

    if (!config) {
      return {
        content: [
          {
            type: "text",
            text: `Unknown agent: ${agent}\nAvailable agents: ${Object.keys(agents).join(", ")}`,
          },
        ],
      };
    }

    const workingDir = cwd ? resolve(baseDir, cwd) : baseDir;

    try {
      const result = await executeAgent(config, prompt, workingDir);
      return {
        content: [
          {
            type: "text",
            text: result,
          },
        ],
      };
    } catch (err) {
      return {
        content: [
          {
            type: "text",
            text: `Error executing agent: ${err}`,
          },
        ],
      };
    }
  });

  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch(console.error);
