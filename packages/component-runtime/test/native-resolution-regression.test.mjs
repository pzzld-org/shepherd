import assert from "node:assert/strict";
import test from "node:test";

import { nativeShepherdBin } from "../src/native-transport.mjs";

test("native Shepherd resolution survives a non-interactive PATH", () => {
  const executable = new Set([
    "/opt/shepherd/bin/shepherd",
    "/Users/joe/.cargo/bin/shepherd",
  ]);
  const isExecutable = (candidate) => executable.has(candidate);

  assert.equal(
    nativeShepherdBin(undefined, {
      PATH: "/usr/bin:/opt/shepherd/bin:/bin",
      HOME: "/Users/joe",
    }, isExecutable),
    "/opt/shepherd/bin/shepherd",
  );

  assert.equal(
    nativeShepherdBin(undefined, {
      PATH: "/usr/bin:/bin",
      HOME: "/Users/joe",
    }, isExecutable),
    "/Users/joe/.cargo/bin/shepherd",
  );
});

test("explicit native binary authority still wins without filesystem probing", () => {
  const never = () => {
    throw new Error("explicit authority must not be probed");
  };
  assert.equal(
    nativeShepherdBin("/embedded/shepherd", { SHEPHERD_NATIVE_BIN: "/ignored" }, never),
    "/embedded/shepherd",
  );
  assert.equal(
    nativeShepherdBin(undefined, { SHEPHERD_NATIVE_BIN: "/configured/shepherd" }, never),
    "/configured/shepherd",
  );
});
