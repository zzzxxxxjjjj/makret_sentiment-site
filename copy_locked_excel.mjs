import fs from "node:fs/promises";

const [source, output] = process.argv.slice(2);
if (!source || !output) {
  throw new Error("Source and output paths are required");
}
await fs.copyFile(source, output);
