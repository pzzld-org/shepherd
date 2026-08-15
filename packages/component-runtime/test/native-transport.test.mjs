import assert from "node:assert/strict";
import test from "node:test";

import {
  invokeNativeDispatch,
  nativeShepherdBin,
} from "../src/native-transport.mjs";

test("native Shepherd resolution has one explicit override and PATH fallback", () => {
  assert.equal(nativeShepherdBin("/opt/shepherd/bin/shepherd", {
    SHEPHERD_NATIVE_BIN: "/ignored/shepherd",
  }), "/opt/shepherd/bin/shepherd");
  assert.equal(nativeShepherdBin(undefined, {
    SHEPHERD_NATIVE_BIN: "/configured/shepherd",
  }), "/configured/shepherd");
  assert.equal(nativeShepherdBin(undefined, {}), "shepherd");
  assert.equal(nativeShepherdBin("", { SHEPHERD_NATIVE_BIN: "" }), "shepherd");
});

test("native dispatch defaults to the canonical CLI name", () => {
  let command;
  const result = invokeNativeDispatch({
    operation: "resolve",
    request: { harness: "claude" },
    environment: {},
    spawn(binary, args, options) {
      command = { binary, args, input: options.input };
      return { status: 0, stdout: "{}\n", stderr: "" };
    },
  });
  assert.deepEqual(result, { ok: true, value: {} });
  assert.deepEqual(command, {
    binary: "shepherd",
    args: ["dispatch", "resolve"],
    input: '{"harness":"claude"}\n',
  });
});
