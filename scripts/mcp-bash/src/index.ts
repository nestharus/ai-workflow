#!/usr/bin/env node
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { spawn } from "child_process";
import { resolve } from "path";

interface ExecuteArgs {
  command: string;
  cwd?: string;
  stdin?: string;
}

async function executeBash(
  command: string,
  cwd: string,
  stdin?: string
): Promise<{ stdout: string; stderr: string; exitCode: number }> {
  return new Promise((resolve) => {
    const proc = spawn("bash", ["-c", command], {
      cwd,
      env: { ...process.env },
    });

    let stdout = "";
    let stderr = "";

    proc.stdout.on("data", (data) => {
      const chunk = data.toString();
      stdout += chunk;
      // Stream stdout to console in real-time for human visibility
      process.stderr.write(`[stdout] ${chunk}`);
    });

    proc.stderr.on("data", (data) => {
      const chunk = data.toString();
      stderr += chunk;
      // Stream stderr to console in real-time for human visibility
      process.stderr.write(`[stderr] ${chunk}`);
    });

    if (stdin) {
      proc.stdin.write(stdin);
      proc.stdin.end();
    }

    proc.on("close", (code) => {
      resolve({ stdout, stderr, exitCode: code ?? 0 });
    });

    proc.on("error", (err) => {
      resolve({
        stdout,
        stderr: stderr + `\nProcess error: ${err}`,
        exitCode: 1,
      });
    });
  });
}

async function main() {
  const baseDir = process.argv[2] || process.cwd();

  const server = new Server(
    {
      name: "mcp-bash",
      version: "1.0.0",
    },
    {
      capabilities: {
        tools: {},
      },
    }
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => {
    return {
      tools: [
        {
          name: "execute",
          description: "Execute a bash command with a 10-hour timeout. Useful for long-running scripts.",
          inputSchema: {
            type: "object" as const,
            properties: {
              command: {
                type: "string",
                description: "The bash command to execute",
              },
              cwd: {
                type: "string",
                description: "Working directory (relative to base or absolute)",
              },
              stdin: {
                type: "string",
                description: "Input to pipe to the command's stdin",
              },
            },
            required: ["command"],
          },
        },
      ],
    };
  });

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    if (request.params.name !== "execute") {
      throw new Error(`Unknown tool: ${request.params.name}`);
    }

    const args = request.params.arguments as unknown as ExecuteArgs;
    const { command, cwd, stdin } = args;
    const workingDir = cwd ? resolve(baseDir, cwd) : baseDir;

    const result = await executeBash(command, workingDir, stdin);

    const output = [
      `Exit code: ${result.exitCode}`,
      "",
      "STDOUT:",
      result.stdout || "(empty)",
      "",
      "STDERR:",
      result.stderr || "(empty)",
    ].join("\n");

    return {
      content: [
        {
          type: "text",
          text: output,
        },
      ],
    };
  });

  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch(console.error);
