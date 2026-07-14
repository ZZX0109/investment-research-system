const authStorageKey = "ai-test-officer-demo-auth";
const orderStorageKey = "ai-test-officer-demo-orders";

async function fetchJson(path) {
  const response = await fetch(path, {
    headers: {
      accept: "application/json"
    }
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${path} (${response.status})`);
  }
  return response.json();
}

async function readOrders() {
  const raw = window.localStorage.getItem(orderStorageKey);
  if (!raw) {
    const payload = await fetchJson("/api/orders");
    const orders = Array.isArray(payload.orders) ? payload.orders : [];
    window.localStorage.setItem(orderStorageKey, JSON.stringify(orders));
    return orders;
  }

  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    const payload = await fetchJson("/api/orders");
    return Array.isArray(payload.orders) ? payload.orders : [];
  }
}

function writeOrders(orders) {
  window.localStorage.setItem(orderStorageKey, JSON.stringify(orders));
}

function ensureLoggedIn() {
  const isAuthenticated = window.localStorage.getItem(authStorageKey) === "true";
  if (!isAuthenticated && window.location.pathname !== "/" && window.location.pathname !== "/login") {
    window.location.assign("/login");
  }
}

function setupLogin() {
  const form = document.querySelector('[data-testid="login-form"]');
  if (!(form instanceof HTMLFormElement)) {
    return;
  }

  const status = document.querySelector('[data-testid="login-status"]');
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    window.localStorage.setItem(authStorageKey, "true");
    if (status) {
      status.textContent = "Login accepted. Redirecting to dashboard.";
      status.className = "status good";
    }

    window.setTimeout(() => {
      window.location.assign("/dashboard");
    }, 150);
  });
}

async function setupOrders() {
  const list = document.querySelector('[data-testid="orders-list"]');
  const summary = document.querySelector('[data-testid="orders-summary"]');
  if (!(list instanceof HTMLElement) || !(summary instanceof HTMLElement)) {
    return;
  }

  const orders = await readOrders();
  const pendingCount = orders.filter((order) => order.status === "pending").length;
  summary.textContent = `${orders.length} orders tracked, ${pendingCount} pending`;

  list.innerHTML = "";
  orders.forEach((order) => {
    const item = document.createElement("li");
    item.className = "card";
    item.innerHTML = `
      <header>
        <div>
          <h3>${order.customer}</h3>
          <p class="muted">${order.id} · Owner ${order.owner} · ${order.amount}</p>
        </div>
        <span class="pill ${order.status === "fulfilled" ? "good" : "warn"}">${order.status}</span>
      </header>
      <div class="actions">
        <button
          type="button"
          class="secondary"
          data-testid="ship-order-${order.id}"
          ${order.status === "fulfilled" ? "disabled" : ""}
        >
          Mark as fulfilled
        </button>
      </div>
    `;

    list.appendChild(item);
  });

  list.querySelectorAll("button[data-testid^='ship-order-']").forEach((button) => {
    button.addEventListener("click", async () => {
      const orderId = button.getAttribute("data-testid")?.replace("ship-order-", "");
      const nextOrders = (await readOrders()).map((order) =>
        order.id === orderId ? { ...order, status: "fulfilled" } : order
      );
      writeOrders(nextOrders);
      await setupOrders();
    });
  });
}

function setupOrderForm() {
  const form = document.querySelector('[data-testid="order-form"]');
  const success = document.querySelector('[data-testid="order-success"]');
  const validationError = document.querySelector('[data-testid="order-validation-error"]');
  if (
    !(form instanceof HTMLFormElement) ||
    !(success instanceof HTMLElement) ||
    !(validationError instanceof HTMLElement)
  ) {
    return;
  }

  form.addEventListener("invalid", (event) => {
    event.preventDefault();
    validationError.hidden = false;
    validationError.textContent = "Customer name is required.";
    success.hidden = true;
  }, true);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    if (!String(data.get("customer") ?? "").trim()) {
      validationError.hidden = false;
      validationError.textContent = "Customer name is required.";
      success.hidden = true;
      return;
    }
    const nextOrder = {
      id: `ord-${Date.now()}`,
      customer: String(data.get("customer") ?? "Unknown customer"),
      status: "pending",
      amount: "$1,000",
      owner: "Taylor"
    };
    const orders = await readOrders();
    orders.unshift(nextOrder);
    writeOrders(orders);
    validationError.hidden = true;
    success.hidden = false;
    success.textContent = `Order saved for ${nextOrder.customer}.`;
    form.reset();
  });
}

function setupTasks() {
  const filterRoot = document.querySelector('[data-testid="task-filter-status"]');
  const taskList = document.querySelector('[data-testid="task-list"]');
  const searchForm = document.querySelector('[data-testid="task-search-form"]');
  const searchInput = document.querySelector('[data-testid="task-search-input"]');
  const emptyState = document.querySelector('[data-testid="task-empty-state"]');
  const errorBanner = document.querySelector('[data-testid="task-error-banner"]');
  if (
    !(filterRoot instanceof HTMLElement) ||
    !(taskList instanceof HTMLElement) ||
    !(searchForm instanceof HTMLFormElement) ||
    !(searchInput instanceof HTMLInputElement) ||
    !(emptyState instanceof HTMLElement) ||
    !(errorBanner instanceof HTMLElement)
  ) {
    return;
  }

  const completedFixtureBug =
    new URLSearchParams(window.location.search).get("fixtureBug") !== "0";

  const render = async (filter, keyword = "") => {
    errorBanner.hidden = filter !== "error";
    emptyState.hidden = true;
    taskList.hidden = filter === "error";
    if (filter === "error") {
      const params = new URLSearchParams();
      params.set("status", "error");
      window.history.replaceState(null, "", `/tasks?${params.toString()}`);
      taskList.innerHTML = "";
      try {
        await fetchJson("/api/tasks?status=error");
      } catch {
        errorBanner.hidden = false;
      }
      return;
    }

    const normalizedKeyword = keyword.trim().toLowerCase();
    const query = new URLSearchParams();
    if (filter !== "all") {
      query.set("status", filter);
    }
    if (normalizedKeyword) {
      query.set("keyword", normalizedKeyword);
    }
    if (!completedFixtureBug) {
      query.set("fixtureBug", "0");
    }
    window.history.replaceState(null, "", query.toString() ? `/tasks?${query.toString()}` : "/tasks");
    taskList.innerHTML = "";
    const payload = await fetchJson(`/api/tasks${query.toString() ? `?${query.toString()}` : ""}`);
    const searchedTasks = Array.isArray(payload.tasks) ? payload.tasks : [];
    if (searchedTasks.length === 0) {
      emptyState.hidden = false;
      emptyState.textContent = `No tasks match ${keyword || "the current filter"}.`;
    }
    searchedTasks.forEach((task) => {
      const item = document.createElement("li");
      item.className = "card";
      item.innerHTML = `
        <header>
          <h3 data-testid="task-title">${task.title}</h3>
          <span class="pill ${task.status === "completed" ? "good" : "warn"}">${task.status}</span>
        </header>
      `;
      taskList.appendChild(item);
    });
  };

  searchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const activeFilter =
      filterRoot.querySelector("button:not(.secondary)")?.getAttribute("data-filter") ?? "all";
    void render(activeFilter, searchInput.value);
  });

  filterRoot.querySelectorAll("button[data-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      filterRoot.querySelectorAll("button[data-filter]").forEach((candidate) => {
        candidate.classList.add("secondary");
      });
      button.classList.remove("secondary");
      void render(button.getAttribute("data-filter") ?? "all", searchInput.value);
    });
  });

  void render("all");
}

ensureLoggedIn();
setupLogin();
void setupOrders();
setupOrderForm();
setupTasks();
