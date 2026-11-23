const test = require("node:test");
const assert = require("node:assert/strict");
const { PointerEventBuffer } = require("../web/pointer-event-buffer.js");

function event(overrides = {}) {
  return {
    active: true,
    pressed: false,
    identity_confirmed: true,
    controller_id: "controller-a",
    track_id: "person-a",
    hand_track_id: "hand-a",
    x: 0.2,
    y: 0.3,
    ...overrides,
  };
}

test("press and release edges survive coalescing before one animation frame", () => {
  const buffer = new PointerEventBuffer();
  buffer.push(event());
  buffer.push(event({ pressed: true, x: 0.4 }));
  buffer.push(event({ pressed: true, x: 0.5 }));
  buffer.push(event({ pressed: false, x: 0.7 }));

  const batch = buffer.drain();
  assert.deepEqual(batch.events.map((item) => item.pressed), [false, true, false]);
  assert.equal(batch.events[1].x, 0.4);
  assert.equal(batch.events[2].x, 0.7);
  assert.equal(batch.edgeCount, 3);
});

test("movement-only samples coalesce to the latest coordinate", () => {
  const buffer = new PointerEventBuffer();
  buffer.push(event());
  buffer.push(event({ x: 0.4, y: 0.4 }));
  buffer.push(event({ x: 0.6, y: 0.7 }));

  const batch = buffer.drain();
  assert.deepEqual(batch.events.map((item) => [item.x, item.y]), [[0.2, 0.3], [0.6, 0.7]]);
  assert.equal(batch.coalesced, 1);
});

test("identity and active-state changes are preserved as ordered edges", () => {
  const buffer = new PointerEventBuffer();
  buffer.push(event());
  buffer.push(event({ identity_confirmed: false }));
  buffer.push(event({ active: false, identity_confirmed: false, pressed: false }));

  const batch = buffer.drain();
  assert.equal(batch.events.length, 3);
  assert.equal(batch.events[1].identity_confirmed, false);
  assert.equal(batch.events[2].active, false);
});

test("clear discards pending events and resets edge comparison", () => {
  const buffer = new PointerEventBuffer();
  buffer.push(event());
  buffer.push(event({ x: 0.8 }));
  assert.equal(buffer.clear(), 2);
  buffer.push(event({ x: 0.9 }));
  const batch = buffer.drain();
  assert.equal(batch.events.length, 1);
  assert.equal(batch.events[0].x, 0.9);
  assert.equal(batch.edgeCount, 1);
});
