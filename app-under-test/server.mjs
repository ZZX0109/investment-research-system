import http from "node:http";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const publicDir = path.join(__dirname, "public");
const seedPath = path.join(__dirname, "data", "seed.json");
const port = Number(process.env.APP_UNDER_TEST_PORT ?? 4173);

const routes = new Map([
  ["/", "login.html"],
  ["/login", "login.html"],
  ["/dashboard", "dashboard.html"],
  ["/orders", "orders.html"],
  ["/orders/create-form", "create-form.html"],
  ["/tasks", "tasks.html"],
  ["/styles.css", "styles.css"],
  ["/app.js", "app.js"]
]);

const contentTypeByExtension = new Map([
  [".html", "text/html; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".js", "application/javascript; charset=utf-8"]
]);

const server = http.createServer(async (request, response) => {
  const requestUrl = request.url ?? "/";
  const url = new URL(requestUrl, `http://127.0.0.1:${port}`);
  const pathname = url.pathname;

  if (pathname.startsWith("/api/")) {
    await handleApiRequest({ url, response });
    return;
  }

  const fileName = routes.get(pathname);

  if (!fileName) {
    response.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
    response.end("Not found");
    return;
  }

  const filePath = path.join(publicDir, fileName);
  const extension = path.extname(filePath);
  const contentType =
    contentTypeByExtension.get(extension) ?? "application/octet-stream";

  try {
    const body = await readFile(filePath);
    response.writeHead(200, { "content-type": contentType });
    response.end(body);
  } catch (error) {
    response.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
    response.end(error instanceof Error ? error.message : "Internal error");
  }
});

async function handleApiRequest({ url, response }) {
  if (url.pathname === "/api/tasks") {
    const seed = await readSeed();
    const status = url.searchParams.get("status") ?? "all";
    const keyword = (url.searchParams.get("keyword") ?? "").trim().toLowerCase();
    if (status === "error") {
      writeJson(response, 500, {
        error: "Task service is unavailable",
        recovery: "Retry by returning to All tasks"
      });
      return;
    }

    const preserveIntentionalBug = url.searchParams.get("fixtureBug") !== "0";
    const statusFiltered =
      status === "all" || (status === "completed" && preserveIntentionalBug)
        ? seed.tasks
        : seed.tasks.filter((task) => task.status === status);
    const tasks = keyword
      ? statusFiltered.filter((task) => task.title.toLowerCase().includes(keyword))
      : statusFiltered;
    writeJson(response, 200, { tasks });
    return;
  }

  if (url.pathname === "/api/orders") {
    const seed = await readSeed();
    writeJson(response, 200, { orders: seed.orders });
    return;
  }

  writeJson(response, 404, { error: "API route not found" });
}

async function readSeed() {
  return JSON.parse(await readFile(seedPath, "utf8"));
}

function writeJson(response, status, payload) {
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store"
  });
  response.end(JSON.stringify(payload));
}

server.listen(port, "127.0.0.1", () => {
  process.stdout.write(
    `AI Test Officer demo app is running at http://127.0.0.1:${port}\n`
  );
});
