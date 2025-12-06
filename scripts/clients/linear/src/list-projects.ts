#!/usr/bin/env node
import { Command } from "commander";
import { getLinearClient, respond, success, error } from "./client.js";

const program = new Command();

program
  .name("list-projects")
  .description("List available Linear projects")
  .option("--team <team>", "Filter by team ID")
  .option("--include-archived", "Include archived projects", false)
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

    const projectsConnection = await client.projects(filter);

    const projects = await Promise.all(
      projectsConnection.nodes.map(async (project) => {
        const teamsConnection = await project.teams();
        const lead = await project.lead;

        // If team filter is specified, check if project belongs to that team
        if (options.team && teamsConnection) {
          const teamIds = teamsConnection.nodes.map((t: any) => t.id);
          if (!teamIds.includes(options.team)) {
            return null;
          }
        }

        return {
          id: project.id,
          name: project.name,
          description: project.description,
          url: project.url,
          slugId: project.slugId,
          startedAt: project.startedAt,
          completedAt: project.completedAt,
          targetDate: project.targetDate,
          createdAt: project.createdAt,
          updatedAt: project.updatedAt,
          archivedAt: project.archivedAt,
          lead: lead
            ? {
                id: lead.id,
                name: lead.name,
                email: lead.email,
              }
            : null,
          state: project.state || null,
          teams: teamsConnection
            ? teamsConnection.nodes.map((t: any) => ({
                id: t.id,
                name: t.name,
                key: t.key,
              }))
            : [],
        };
      })
    );

    // Filter out null entries (projects that didn't match team filter)
    const filteredProjects = projects.filter((p) => p !== null);

    respond(
      success({
        projects: filteredProjects,
        totalCount: filteredProjects.length,
      })
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    respond(error("LIST_PROJECTS_FAILED", message));
  }
}

main();
