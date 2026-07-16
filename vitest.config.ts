import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/ai-test-officer-adapter.test.ts", "tests/workbench*.test.ts"]
  }
});
