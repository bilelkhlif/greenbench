// Empty the dashboard build directory before `vite build` (or the directory given as argument).
// fs.rmSync(..., { force: true }) silently leaves files in place on Windows paths with
// non-ASCII characters (seen with Node 24), so walk the tree with unlink/rmdir instead.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const target = process.argv[2]
  ? path.resolve(process.argv[2])
  : path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/greenbench/server/static");

function empty(dir) {
  if (!fs.existsSync(dir)) return;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      empty(p);
      fs.rmdirSync(p);
    } else {
      fs.unlinkSync(p);
    }
  }
}

empty(target);
