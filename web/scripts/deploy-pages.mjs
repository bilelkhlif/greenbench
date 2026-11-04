// Publish the dashboard to GitHub Pages: https://<owner>.github.io/<repo>/
//
// 1. builds the app in static mode under /<repo>/ (vite --mode pages, see .env.pages);
// 2. snapshots the API from the committed results (`greenbench export-static`) into data/;
// 3. adds the GitHub Pages details: 404.html so deep links open the app, .nojekyll;
// 4. force-pushes that folder as a one-commit `gh-pages` branch of the `origin` repository.
//
// usage (from web/): npm run deploy:pages      or  npm run build:pages  to build web/dist-pages only
import { execFileSync } from "node:child_process";
import { copyFileSync, cpSync, existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const web = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const root = resolve(web, "..");
const out = join(web, "dist-pages");
const push = !process.argv.includes("--no-push");
const sh = (cmd, args, opts = {}) => execFileSync(cmd, args, { stdio: "inherit", ...opts });
const git = (...args) => execFileSync("git", args, { cwd: root, encoding: "utf8" }).trim();

const remote = git("remote", "get-url", "origin");
const match = remote.match(/github\.com[:/]([^/]+)\/([^/]+?)(?:\.git)?\/?$/);
if (!match) throw new Error(`origin is not a GitHub repository: ${remote}`);
const [, owner, repo] = match;

// 1. the app
sh(process.execPath, [join(web, "scripts/clean-static.mjs"), out]);
sh(process.execPath, [join(web, "node_modules/vite/bin/vite.js"), "build", "--mode", "pages", "--base", `/${repo}/`], {
  cwd: web,
  env: { ...process.env, VITE_REPO_URL: `https://github.com/${owner}/${repo}` },
});

// 2. the data
const python = process.env.PYTHON
  ?? [join(root, ".venv/Scripts/python.exe"), join(root, ".venv/bin/python")].find((p) => existsSync(p))
  ?? "python";
sh(python, ["-m", "greenbench", "export-static", join(out, "data")], { cwd: root });

// 3. unknown paths serve 404.html, which boots the app on the requested route
copyFileSync(join(out, "index.html"), join(out, "404.html"));
writeFileSync(join(out, ".nojekyll"), "");

if (!push) {
  console.log(`\nBuilt ${out} for https://${owner}.github.io/${repo}/`);
  process.exit(0);
}

// 4. publish
let identity;
try {
  identity = ["-c", `user.name=${git("config", "user.name")}`, "-c", `user.email=${git("config", "user.email")}`];
} catch {
  throw new Error("set git user.name and user.email first (git config user.name ...)");
}
let auth = [];
try {
  execFileSync("gh", ["--version"], { stdio: "ignore" });
  auth = ["-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential"]; // push with the GitHub CLI login
} catch {
  /* no GitHub CLI: plain git credentials */
}
const tmp = mkdtempSync(join(tmpdir(), "greenbench-pages-"));
try {
  cpSync(out, tmp, { recursive: true });
  const g = (...args) => sh("git", [...identity, ...auth, ...args], { cwd: tmp });
  g("init", "-q", "-b", "gh-pages");
  g("add", "-A");
  g("commit", "-q", "-m", `Dashboard snapshot of ${git("rev-parse", "--short", "HEAD")}`);
  g("push", "-q", "-f", remote, "gh-pages");
} finally {
  try { rmSync(tmp, { recursive: true, force: true }); } catch { /* leave the temp copy */ }
}
console.log(`\nPublished to gh-pages: https://${owner}.github.io/${repo}/ (live within a minute or two)`);
