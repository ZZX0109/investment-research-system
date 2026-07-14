import http from "node:http";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const port = Number(process.env.CUSTOMER_PORTAL_FIXTURE_PORT ?? 4185);
const markerPath = process.env.CUSTOMER_PORTAL_FIXTURE_MARKER;
const seededAccount = process.env.CUSTOMER_PORTAL_FIXTURE_ACCOUNT ?? "qa-admin@example.test";

if (markerPath) {
  await mkdir(path.dirname(markerPath), { recursive: true });
  await writeFile(
    markerPath,
    JSON.stringify({
      event: "started",
      port,
      account: seededAccount,
      mode: process.env.CUSTOMER_PORTAL_FIXTURE_MODE ?? "local-fixture"
    }, null, 2),
    "utf8"
  );
}

const orders = [
  { id: "ord-1001", customer: "Acme Co", status: "Ready" },
  { id: "ord-1002", customer: "Globex", status: "Queued" }
];

const customers = [
  { id: "cust-1001", name: "Acme Co", tier: "Enterprise" },
  { id: "cust-1002", name: "Globex", tier: "Growth" }
];

const server = http.createServer((request, response) => {
  const url = new URL(request.url ?? "/", `http://127.0.0.1:${port}`);
  if (url.pathname === "/healthz" || url.pathname === "/api/health") {
    writeJson(response, 204, {});
    return;
  }
  if (url.pathname === "/" || url.pathname === "/signin") {
    writeHtml(response, signinPage());
    return;
  }
  if (url.pathname === "/customers") {
    writeHtml(response, customersPage());
    return;
  }
  if (url.pathname === "/customers/new") {
    writeHtml(response, createCustomerPage());
    return;
  }
  if (url.pathname === "/orders") {
    writeHtml(response, ordersPage());
    return;
  }
  if (url.pathname === "/api/customers") {
    writeJson(response, 200, { customers });
    return;
  }
  if (url.pathname === "/api/orders") {
    writeJson(response, 200, { orders });
    return;
  }

  response.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
  response.end("Not found");
});

server.listen(port, "127.0.0.1", () => {
  process.stdout.write(`Customer Portal Lite fixture ready at http://127.0.0.1:${port}\n`);
});

process.on("SIGTERM", () => {
  server.close(() => process.exit(0));
});

function signinPage() {
  return page("Sign in", `
    <main>
      <h1>Customer Portal Sign in</h1>
      <p>Seeded account: <strong>${escapeHtml(seededAccount)}</strong></p>
      <button data-testid="signin-submit">Sign in</button>
    </main>
  `);
}

function customersPage() {
  return page("Customers", `
    <main>
      <h1>Customers</h1>
      <section data-testid="customer-detail-panel">
        <h2>Customer profile</h2>
        ${customers.map((customer) => `
          <article>
            <strong>${escapeHtml(customer.name)}</strong>
            <span>${escapeHtml(customer.tier)}</span>
            <button data-testid="open-customer-${customer.id}">Open customer</button>
          </article>
        `).join("")}
      </section>
    </main>
  `);
}

function createCustomerPage() {
  return page("Create customer", `
    <main>
      <h1>Create customer</h1>
      <label>
        Customer name
        <input data-testid="customer-name" aria-label="Customer name" value="Northwind Traders" />
      </label>
      <button data-testid="customer-save">Create customer</button>
      <p data-testid="customer-success">Customer created</p>
    </main>
  `);
}

function ordersPage() {
  return page("Orders", `
    <main>
      <h1>Orders</h1>
      <section data-testid="orders-list">
        ${orders.map((order) => `
          <article>
            <strong>${escapeHtml(order.id)}</strong>
            <span>${escapeHtml(order.customer)}</span>
            <span>${escapeHtml(order.status)}</span>
            <button data-testid="ship-order-${order.id}">Ship order</button>
          </article>
        `).join("")}
        <p>Shipped</p>
      </section>
    </main>
  `);
}

function page(title, body) {
  return `<!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>${escapeHtml(title)}</title>
      </head>
      <body>${body}</body>
    </html>`;
}

function writeHtml(response, html) {
  response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  response.end(html);
}

function writeJson(response, status, payload) {
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store"
  });
  response.end(status === 204 ? "" : JSON.stringify(payload));
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
