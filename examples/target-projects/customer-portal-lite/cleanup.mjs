import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const markerPath = process.env.CUSTOMER_PORTAL_FIXTURE_CLEANUP_MARKER;

if (markerPath) {
  await mkdir(path.dirname(markerPath), { recursive: true });
  await writeFile(
    markerPath,
    JSON.stringify({
      event: "cleaned",
      mode: process.env.CUSTOMER_PORTAL_FIXTURE_MODE ?? "local-fixture"
    }, null, 2),
    "utf8"
  );
}
