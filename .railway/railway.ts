// Railway project: PostgreSQL and the web app. The web app also runs the data
// collection on its own schedule (src/nordic_signals/scheduler.py): pump.fun every
// 5 minutes (and the fake-money positions' prices every minute), and the Nordic
// collectors at set times on weekdays. No separate cron services are needed.
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
import { defineRailway, github, postgres, preserve, project, service } from "railway/iac";

const REPO = "andreovstedal/Trading";

export default defineRailway(() => {
  const db = postgres("postgres");

  // The web app, which also runs the collection schedule. Set in the dashboard;
  // preserve() keeps whatever value is there:
  //   APP_PASSWORD (required) and SECRET_KEY;
  //   SCHEDULER=off to stop the automatic collection;
  //   SOLANA_RPC_URL (optional): a private Solana RPC node, for the pump.fun
  //   measurement's holder-concentration check;
  //   GITHUB_TOKEN and LOG_REPO (optional): push the small pump.fun log to the
  //   branch LOG_BRANCH (default pumpfun-logg) every hour, see src/nordic_signals/logpush.py.
  // Generate a public domain under Settings -> Networking after the first deploy.
  const web = service("web", {
    source: github(REPO),
    build: {
      builder: "DOCKERFILE",
      dockerfilePath: "Dockerfile",
      watchPatterns: ["src/**", "pyproject.toml", "Dockerfile"],
    },
    deploy: { startCommand: "nordic-signals web --host 0.0.0.0", healthcheckPath: "/health" },
    env: {
      DATABASE_URL: db.env.DATABASE_URL,
      APP_PASSWORD: preserve(),
      SECRET_KEY: preserve(),
      SCHEDULER: preserve(),
      SOLANA_RPC_URL: preserve(),
      GITHUB_TOKEN: preserve(),
      LOG_REPO: preserve(),
      LOG_BRANCH: preserve(),
    },
  });

  return project("nordic-signals", {
    resources: [db, web],
  });
});
