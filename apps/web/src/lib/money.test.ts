import { describe, expect, it } from "vitest";

import { money, pct } from "./contracts";

describe("formatters", () => {
  it("formats a paper balance with cents", () => {
    expect(money(9955)).toBe("$9,955.00");
  });

  it("formats a signed return", () => {
    expect(pct(111.63)).toBe("+111.63%");
    expect(pct(-4.2)).toBe("-4.20%");
  });
});
