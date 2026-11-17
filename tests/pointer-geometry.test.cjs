const test = require("node:test");
const assert = require("node:assert/strict");
const Geometry = require("../web/pointer-geometry.js");

const close = (actual, expected, tolerance = 1e-6) => {
  assert.ok(Math.abs(actual - expected) <= tolerance, `expected ${actual} to be close to ${expected}`);
};

test("identity homography keeps all normalized points unchanged", () => {
  const corners = [
    { x: 0.08, y: 0.08 },
    { x: 0.92, y: 0.08 },
    { x: 0.92, y: 0.92 },
    { x: 0.08, y: 0.92 },
  ];
  const matrix = Geometry.solveHomography(corners, corners);
  const center = Geometry.applyHomography(matrix, { x: 0.5, y: 0.5 });
  close(center.x, 0.5);
  close(center.y, 0.5);
});

test("perspective homography maps four captured camera corners to canvas targets", () => {
  const camera = [
    { x: 0.18, y: 0.12 },
    { x: 0.86, y: 0.20 },
    { x: 0.78, y: 0.88 },
    { x: 0.12, y: 0.76 },
  ];
  const targets = [
    { x: 0.08, y: 0.08 },
    { x: 0.92, y: 0.08 },
    { x: 0.92, y: 0.92 },
    { x: 0.08, y: 0.92 },
  ];
  const matrix = Geometry.solveHomography(camera, targets);
  camera.forEach((point, index) => {
    const mapped = Geometry.applyHomography(matrix, point);
    close(mapped.x, targets[index].x);
    close(mapped.y, targets[index].y);
  });
});

test("calibration rejects duplicate, collinear, or crossed corner samples", () => {
  const targets = [
    { x: 0.08, y: 0.08 },
    { x: 0.92, y: 0.08 },
    { x: 0.92, y: 0.92 },
    { x: 0.08, y: 0.92 },
  ];
  const duplicate = [targets[0], targets[0], targets[2], targets[3]];
  const crossed = [targets[0], targets[2], targets[1], targets[3]];
  assert.throws(() => Geometry.solveHomography(duplicate, targets), /四角/);
  assert.throws(() => Geometry.solveHomography(crossed, targets), /四角/);
});

test("normalized pointer mapping applies mirror and homography before viewport scaling", () => {
  const rect = { left: 100, top: 50, width: 800, height: 600 };
  const mapped = Geometry.normalizedToClient({ x: 0.25, y: 0.5 }, rect, true);
  close(mapped.x, 700);
  close(mapped.y, 350);
});

test("client coordinates convert to world coordinates with scroll and zoom", () => {
  const world = Geometry.clientToWorld(
    { x: 350, y: 260 },
    { left: 100, top: 60 },
    200,
    100,
    0.5,
  );
  close(world.x, 900);
  close(world.y, 600);
});

test("node drag preserves the exact grab offset and clamps to canvas bounds", () => {
  const position = Geometry.nodePositionFromPointer(
    { x: 410, y: 260 },
    { x: 24, y: 18 },
    { width: 1900, height: 1100 },
    { width: 236, height: 106 },
  );
  assert.deepEqual(position, { x: 386, y: 242 });
  const clamped = Geometry.nodePositionFromPointer(
    { x: 2500, y: 1500 },
    { x: 0, y: 0 },
    { width: 1900, height: 1100 },
    { width: 236, height: 106 },
  );
  assert.deepEqual(clamped, { x: 1664, y: 994 });
});

test("invalid zoom and singular projective transforms are rejected", () => {
  assert.throws(
    () => Geometry.clientToWorld({ x: 1, y: 1 }, { left: 0, top: 0 }, 0, 0, 0),
    /画布坐标/,
  );
  assert.throws(
    () => Geometry.applyHomography([0, 0, 0, 0, 0, 0, -1, 0], { x: 1, y: 0.5 }),
    /坐标映射/,
  );
});
