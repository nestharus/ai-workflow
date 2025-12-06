#!/usr/bin/env node
import { Command } from "commander";
import { getLinearClient, respond, success, error } from "./client.js";

const program = new Command();

program
  .name("list-teams")
  .description("List available Linear teams")
  .option("--include-archived", "Include archived teams", false)
  .parse();

const options = program.opts();

async function main() {
  try {
    const client = getLinearClient();

    const filter: {
      includeArchived?: boolean;
    } = {};

    if (options.includeArchived) {
      filter.includeArchived = true;
    }

    const teamsConnection = await client.teams(filter);

    const teams = await Promise.all(
      teamsConnection.nodes.map(async (team) => {
        return {
          id: team.id,
          name: team.name,
          key: team.key,
          description: team.description,
          createdAt: team.createdAt,
          updatedAt: team.updatedAt,
          archivedAt: team.archivedAt,
          private: team.private,
          timezone: team.timezone,
        };
      })
    );

    respond(
      success({
        teams,
        totalCount: teams.length,
      })
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    respond(error("LIST_TEAMS_FAILED", message));
  }
}

main();
