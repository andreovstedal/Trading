// Railway project: PostgreSQL, the web app, and the scheduled collector jobs.
//
// Apply with the Railway CLI (5.42.1 or newer) from the repository root:
//   npm install --prefix .railway    # once: installs the "railway" SDK this file imports
//   railway link                     # choose the project and environment
//   railway config plan              # preview the changes
//   railway config apply             # create or update the services
//
// The file describes the whole project: anything in the Railway project that is
// not listed here is proposed for deletion, so start from an empty project or
// review the plan carefully.
//
// Railway runs cron schedules in UTC. Oslo and Stockholm are UTC+2 in summer and
// UTC+1 in winter, so each time below is chosen to work in both.
import { defineRailway, github, group, postgres, preserve, project, service } from "railway/iac";

const REPO = "andreovstedal/Trading";

export default defineRailway(() => {
  const db = postgres("postgres");

  const build = {
    builder: "DOCKERFILE" as const,
    dockerfilePath: "Dockerfile",
    watchPatterns: ["src/**", "pyproject.toml", "Dockerfile"],
  };

  // The web app. APP_PASSWORD (required) and SECRET_KEY are set in the dashboard;
  // preserve() keeps whatever value is there. Generate a public domain under
  // Settings -> Networking after the first deploy.
  const web = service("web", {
    source: github(REPO),
    build,
    deploy: { startCommand: "nordic-signals web --host 0.0.0.0", healthcheckPath: "/health" },
    env: { DATABASE_URL: db.env.DATABASE_URL, APP_PASSWORD: preserve(), SECRET_KEY: preserve() },
  });

  // Every job runs the same image with its own start command, then exits.
  const job = (name: string, cronSchedule: string, startCommand: string) =>
    service(name, {
      source: github(REPO),
      build,
      deploy: { startCommand, cronSchedule, restartPolicyType: "NEVER" },
      env: { DATABASE_URL: db.env.DATABASE_URL },
    });

  const collectors = group("Collectors", [
    // Every 15 minutes on weekdays, 07:00-20:45 Oslo summer time (06:00-19:45 winter):
    // new Oslo announcements and Swedish insider trades.
    job("collect-intraday", "*/15 5-18 * * 1-5", "nordic-signals collect intraday"),
    // 20:30 UTC: after both closes, the 15:30 short-register updates and Nordnet's
    // evening owner counts. Looks back far enough to cover a weekend, then scores
    // past recommendations against the new prices.
    job("collect-daily", "30 20 * * 1-5", "nordic-signals nightly"),
    // Swedish press releases for the whole universe. The first run matches company
    // names to MFN pages (about 30 minutes); later runs reuse the matches.
    job("collect-mfn", "0 21 * * 1-5", "nordic-signals collect mfn --universe SE --days 3 --max-pages 1"),
    // End-of-day prices for every tradable Norwegian and Swedish share, about 4 s per
    // symbol (roughly 90 minutes) to stay under Yahoo's rate limit.
    job("collect-prices", "30 21 * * 1-5", "nordic-signals collect yahoo --universe NO --universe SE --range 5d"),
  ]);

  return project("nordic-signals", {
    resources: [db, web, collectors],
  });
});
