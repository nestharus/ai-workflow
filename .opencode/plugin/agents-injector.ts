import { readFileSync } from "fs"
import { join } from "path"

export const AgentsInjector = async ({ directory }) => {
  let agentsContent: string | null = null

  try {
    const agentsPath = join(directory, "AGENTS.md")
    agentsContent = readFileSync(agentsPath, "utf-8")
  } catch {
    // AGENTS.md not found, skip injection
  }

  return {
    "experimental.chat.system.transform": async (input, output) => {
      if (agentsContent) {
        output.system.unshift(agentsContent)
      }
    },
  }
}
