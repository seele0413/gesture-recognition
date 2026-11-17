(function attachPointerEventBuffer(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    root.PointerEventBuffer = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function createPointerEventBufferModule() {
  function stateSignature(event) {
    return [
      Boolean(event.active),
      Boolean(event.pressed),
      event.identity_confirmed !== false,
      event.controller_id || "",
      event.track_id || "",
      event.hand_track_id || "",
    ].join("\u0000");
  }

  class PointerEventBuffer {
    constructor() {
      this.sequence = 0;
      this.lastSignature = null;
      this.pendingEdges = [];
      this.latest = null;
      this.coalescedCount = 0;
    }

    push(event) {
      if (!event || typeof event !== "object") {
        throw new TypeError("pointer event must be an object");
      }
      const snapshot = { ...event, _pointerSequence: ++this.sequence };
      const signature = stateSignature(snapshot);
      const isEdge = this.lastSignature === null || signature !== this.lastSignature;
      const latestIsQueuedEdge = this.latest
        && this.pendingEdges.length
        && this.pendingEdges[this.pendingEdges.length - 1]._pointerSequence === this.latest._pointerSequence;
      if (this.latest && !latestIsQueuedEdge) this.coalescedCount += 1;
      if (isEdge) this.pendingEdges.push(snapshot);
      this.latest = snapshot;
      this.lastSignature = signature;
      return { sequence: snapshot._pointerSequence, edge: isEdge };
    }

    drain() {
      const events = this.pendingEdges.slice();
      const lastEdge = events[events.length - 1];
      if (this.latest && (!lastEdge || lastEdge._pointerSequence !== this.latest._pointerSequence)) {
        events.push(this.latest);
      }
      const batch = {
        events,
        coalesced: this.coalescedCount,
        edgeCount: this.pendingEdges.length,
      };
      this.pendingEdges = [];
      this.latest = null;
      this.coalescedCount = 0;
      return batch;
    }

    clear() {
      const discarded = this.pendingEdges.length + (this.latest
        && (!this.pendingEdges.length
          || this.pendingEdges[this.pendingEdges.length - 1]._pointerSequence !== this.latest._pointerSequence) ? 1 : 0);
      this.pendingEdges = [];
      this.latest = null;
      this.coalescedCount = 0;
      this.lastSignature = null;
      return discarded;
    }
  }

  return { PointerEventBuffer };
});
