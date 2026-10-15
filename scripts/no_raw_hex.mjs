import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../apps/web/src/", import.meta.url));
const hex = /#[0-9a-fA-F]{3,8}\b/;
const allow = new Set(["globals.css"]);

function walk(dir, hits) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      walk(path, hits);
      continue;
    }
    if (!name.endsWith(".ts") && !name.endsWith(".tsx") && !name.endsWith(".css")) {
      continue;
    }
    if (allow.has(name)) {
      continue;
    }
    const text = readFileSync(path, "utf8");
    if (hex.test(text)) {
      hits.push(path);
    }
  }
}

const hits = [];
walk(root, hits);
if (hits.length) {
  console.error(hits.join("\n"));
  process.exit(1);
}
console.log("no raw hex");
