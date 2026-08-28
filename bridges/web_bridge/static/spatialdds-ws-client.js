/* SpatialDDS Web Bridge — minimal browser client.
 *
 * Plain ES6, no dependencies. Connects to /ws on the same origin by default.
 *
 * Usage:
 *   const sdds = new SpatialDDSClient();
 *   await sdds.connect();
 *   const subId = sdds.subscribe(
 *     "spatialdds/*\/sensing/detection3d/v1",
 *     (msg) => console.log(msg.payload),
 *     { msgTypes: ["Detection3DSet", "ROS2_DETECTION3D_SET"], maxRateHz: 5 }
 *   );
 *   sdds.publish(
 *     "ROS2_FRAMED_POSE",
 *     "spatialdds/web_client/ego/pose/v1",
 *     { pose: { t: { x: 1, y: 2, z: 0 }, q: { x: 0, y: 0, z: 0, w: 1 } } }
 *   );
 */
class SpatialDDSClient {
  constructor(url) {
    this._url = url || `ws://${location.host}/ws`;
    this._ws = null;
    this._handlers = {};         // sub_id → callback(msg)
    this._oneShot = {};          // type → resolver  (for list_topics, ping)
    this._reconnectMs = 2000;
    this._pingInterval = null;
    this.onConnect = null;
    this.onDisconnect = null;
  }

  connect() {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this._url);
      this._ws = ws;
      ws.onopen = () => {
        this._startPing();
        if (this.onConnect) this.onConnect();
        resolve();
      };
      ws.onclose = () => {
        this._stopPing();
        if (this.onDisconnect) this.onDisconnect();
        // Auto-reconnect; subscriptions need to be re-issued by the caller.
        setTimeout(() => this.connect().catch(() => {}), this._reconnectMs);
      };
      ws.onerror = (err) => reject(err);
      ws.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch (e) { return; }
        this._dispatch(msg);
      };
    });
  }

  subscribe(pattern, callback, options = {}) {
    const id = options.id || `sub_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
    this._handlers[id] = callback;
    const req = { type: "subscribe", id, pattern };
    if (options.msgTypes) req.msg_types = options.msgTypes;
    if (options.maxRateHz != null) req.max_rate_hz = options.maxRateHz;
    this._send(req);
    return id;
  }

  unsubscribe(id) {
    delete this._handlers[id];
    this._send({ type: "unsubscribe", id });
  }

  publish(msgType, logicalTopic, payload) {
    this._send({
      type: "publish",
      msg_type: msgType,
      logical_topic: logicalTopic,
      payload,
    });
  }

  /** Returns Promise<Topic[]>. */
  listTopics() {
    return new Promise((resolve) => {
      this._oneShot["topics"] = resolve;
      this._send({ type: "list_topics" });
    });
  }

  /** Returns Promise<{server_time_ns, clients_connected, messages_dispatched}>. */
  ping() {
    return new Promise((resolve) => {
      this._oneShot["pong"] = resolve;
      this._send({ type: "ping" });
    });
  }

  _dispatch(msg) {
    switch (msg.type) {
      case "data": {
        const cb = this._handlers[msg.sub_id];
        if (cb) cb(msg);
        break;
      }
      case "topics": {
        const r = this._oneShot["topics"];
        if (r) { delete this._oneShot["topics"]; r(msg.topics); }
        break;
      }
      case "pong": {
        const r = this._oneShot["pong"];
        if (r) { delete this._oneShot["pong"]; r(msg); }
        break;
      }
      case "error":
        console.error("[SpatialDDS]", msg.message, msg);
        break;
      // subscribed / unsubscribed / published — silent acks.
      default: break;
    }
  }

  _send(obj) {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify(obj));
    }
  }
  _startPing() {
    this._pingInterval = setInterval(() => this._send({ type: "ping" }), 10000);
  }
  _stopPing() {
    if (this._pingInterval) { clearInterval(this._pingInterval); this._pingInterval = null; }
  }
}

if (typeof window !== "undefined") {
  window.SpatialDDSClient = SpatialDDSClient;
}
if (typeof module !== "undefined") {
  module.exports = SpatialDDSClient;
}
