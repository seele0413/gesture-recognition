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


test("calibration sampling uses a stable median and tolerates one isolated outlier", () => {
  const point = Geometry.stableMedianPoint([
    { x: 0.501, y: 0.499 },
    { x: 0.500, y: 0.501 },
    { x: 0.502, y: 0.500 },
    { x: 0.499, y: 0.500 },
    { x: 0.82, y: 0.15 },
  ]);
  close(point.x, 0.501);
  close(point.y, 0.500);
  assert.ok(point.spread < 0.01);
});

test("calibration sampling rejects too few samples and sustained hand movement", () => {
  assert.equal(Geometry.stableMedianPoint([
    { x: 0.5, y: 0.5 },
    { x: 0.501, y: 0.5 },
    { x: 0.499, y: 0.5 },
  ]), null);
  assert.equal(Geometry.stableMedianPoint([
    { x: 0.40, y: 0.50 },
    { x: 0.45, y: 0.50 },
    { x: 0.50, y: 0.50 },
    { x: 0.55, y: 0.50 },
    { x: 0.60, y: 0.50 },
  ]), null);
});

test("calibration sampling rejects malformed parameters and coordinates", () => {
  assert.throws(() => Geometry.stableMedianPoint([], 2, 0.03), /校准采样参数/);
  assert.throws(() => Geometry.stableMedianPoint([{ x: NaN, y: 0.5 }], 1, 0.03), /校准采样参数/);
  assert.throws(() => Geometry.stableMedianPoint([
    { x: NaN, y: 0.5 },
    { x: 0.5, y: 0.5 },
    { x: 0.5, y: 0.5 },
  ], 3, 0.03), /无效坐标/);
});
